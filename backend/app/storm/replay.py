from datetime import timedelta

from app.storm.helene import LANDFALL, REPLAY

MODE = "coalesce(payload->>'mode', 'replay') = %(mode)s"  # replay rows predate the mode marker

FRAME_SQL = {
    "cone": f"""SELECT payload, ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom::geometry, 0.02), 4)::json AS geometry FROM storm_event
               WHERE kind = 'nhc_cone' AND ts <= %(t)s AND {MODE} ORDER BY ts DESC LIMIT 1""",
    "track": f"""SELECT json_build_object('type', 'LineString', 'coordinates', json_agg(json_build_array(ST_X(geom::geometry), ST_Y(geom::geometry)) ORDER BY ts)) AS geometry
                FROM storm_event WHERE kind = 'nhc_track' AND ts <= %(t)s AND {MODE}""",
    "warnings": f"""SELECT payload, ST_AsGeoJSON(geom, 4)::json AS geometry FROM storm_event
                   WHERE kind = 'nws_alert' AND ts <= %(t)s AND (payload->>'expire')::timestamptz > %(t)s AND {MODE}""",
    "reports": f"""SELECT ts, kind, payload, ST_AsGeoJSON(geom, 4)::json AS geometry FROM storm_event
                  WHERE kind IN ('lsr', 'spc_report') AND ts <= %(t)s AND ts >= %(t0)s AND {MODE}""",
    "incidents": """SELECT id, ts, kind, where_text, precision, confidence, verified, needs_confirmation, utility_mentioned, customers_affected,
                           jsonb_array_length(sources) - (SELECT count(*) FROM jsonb_array_elements(sources) s WHERE s->>'type' = 'context') AS n_sources,
                           ST_AsGeoJSON(geom, 5)::json AS geometry
                    FROM incident WHERE mode = %(mode)s AND ts <= %(t)s AND ts >= %(t0)s""",
}

EXPOSURE_SQL = f"""
SELECT a.org_id, count(*) AS n FROM asset a
JOIN (SELECT geom FROM storm_event WHERE kind = 'nhc_cone' AND ts <= %(t)s AND {MODE} ORDER BY ts DESC LIMIT 1) c ON ST_Intersects(c.geom, a.geom)
GROUP BY a.org_id
"""

STAGING_SQL = f"""
WITH hit AS (
  SELECT DISTINCT a.id, a.org_id, a.geom FROM asset a
  JOIN storm_event e ON e.kind IN ('lsr', 'spc_report') AND e.ts <= %(t)s AND e.ts >= %(t0)s AND {MODE.replace('payload', 'e.payload')}
    AND ST_DWithin(e.geom, a.geom, 10000)
), cross_hit AS (
  SELECT h.* FROM hit h WHERE EXISTS (SELECT 1 FROM hit o WHERE o.org_id <> h.org_id AND ST_DWithin(o.geom, h.geom, 40000))
), c AS (
  SELECT *, ST_ClusterDBSCAN(ST_Transform(geom::geometry, 5070), eps := 40000, minpoints := 2) OVER () AS cid FROM cross_hit
)
SELECT cid, count(*) FILTER (WHERE org_id = 'desc') AS desc_n, count(*) FILTER (WHERE org_id = 'gpc') AS gpc_n,
       ST_AsGeoJSON(ST_Centroid(ST_MakeLine(ST_Centroid(ST_Collect(geom::geometry) FILTER (WHERE org_id = 'desc')),
                                            ST_Centroid(ST_Collect(geom::geometry) FILTER (WHERE org_id = 'gpc')))), 5)::json AS geometry  -- midway between the two utilities' damage
FROM c WHERE cid IS NOT NULL GROUP BY cid
HAVING count(*) FILTER (WHERE org_id = 'desc') > 0 AND count(*) FILTER (WHERE org_id = 'gpc') > 0
ORDER BY count(*) DESC
"""


def feature(row):
    geom = row.pop("geometry")
    return {"type": "Feature", "geometry": geom, "properties": {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()}}


def frame(conn, t, mode="replay"):
    t0 = REPLAY[0] if mode == "replay" else t - timedelta(hours=24)  # live shows the last day
    params = {"t": t, "t0": t0, "mode": mode}
    out = {"at": t.isoformat(), "mode": mode, "landfall": LANDFALL.isoformat(), "window": [REPLAY[0].isoformat(), REPLAY[1].isoformat()]}
    for key, sql in FRAME_SQL.items():
        rows = [r for r in conn.execute(sql, params).fetchall() if r["geometry"]]
        out[key] = {"type": "FeatureCollection", "features": [feature(r) for r in rows]}
    out["exposure"] = {r["org_id"]: r["n"] for r in conn.execute(EXPOSURE_SQL, params).fetchall()}
    out["staging"] = {"type": "FeatureCollection", "features": [feature(r) for r in conn.execute(STAGING_SQL, params).fetchall()]}
    return out
