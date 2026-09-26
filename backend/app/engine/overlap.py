import time

from app.config import OVERLAP_RADIUS_M
from app.engine.cost import savings
from app.engine.scoring import score, tier_for, time_overlap

PAIRS_SQL = """
WITH j AS (
  SELECT id, org_id, horizon, geom, work_window, in_service,
         ST_GeometryType(geom::geometry) = 'ST_LineString' AS is_line
  FROM job WHERE horizon = %(horizon)s
)
SELECT a.id AS job_a, b.id AS job_b,
       ST_Distance(a.geom, b.geom) AS distance_m,
       ST_Distance(ST_Centroid(a.geom::geometry)::geography, ST_Centroid(b.geom::geometry)::geography, false) AS center_distance_m,
       ST_Intersects(a.geom, b.geom) AS touches,
       CASE WHEN a.is_line AND b.is_line AND ST_DWithin(a.geom, b.geom, 1600)
         THEN LEAST(ST_Length(ST_Intersection(a.geom, ST_Buffer(b.geom, 1600))),
                    ST_Length(ST_Intersection(b.geom, ST_Buffer(a.geom, 1600))))
         ELSE 0 END AS overlap_m,
       lower(a.work_window) AS a_start, upper(a.work_window) AS a_end,
       lower(b.work_window) AS b_start, upper(b.work_window) AS b_end,
       abs(a.in_service - b.in_service) AS time_gap_days,
       ST_AsText(ST_ShortestLine(a.geom::geometry, b.geom::geometry)) AS link
FROM j a JOIN j b
  ON a.id < b.id AND a.org_id <> b.org_id AND ST_DWithin(a.geom, b.geom, %(radius)s)
"""

UPSERT_SQL = """
INSERT INTO opportunity (job_a, job_b, horizon, distance_m, center_distance_m, overlap_m, tier,
                         time_overlap, time_gap_days, score, savings_low, savings_high, link)
VALUES (%(job_a)s, %(job_b)s, %(horizon)s, %(distance_m)s, %(center_distance_m)s, %(overlap_m)s, %(tier)s,
        %(time_overlap)s, %(time_gap_days)s, %(score)s, %(savings_low)s, %(savings_high)s, ST_GeogFromText(%(link)s))
ON CONFLICT (job_a, job_b) DO UPDATE SET
  distance_m = EXCLUDED.distance_m, center_distance_m = EXCLUDED.center_distance_m,
  overlap_m = EXCLUDED.overlap_m, tier = EXCLUDED.tier, time_overlap = EXCLUDED.time_overlap,
  time_gap_days = EXCLUDED.time_gap_days, score = EXCLUDED.score,
  savings_low = EXCLUDED.savings_low, savings_high = EXCLUDED.savings_high, link = EXCLUDED.link
"""


def recompute(conn, horizon="long"):
    t0 = time.perf_counter()
    rows = conn.execute(PAIRS_SQL, {"horizon": horizon, "radius": OVERLAP_RADIUS_M}).fetchall()
    out = []
    for r in rows:
        tier = tier_for(r["distance_m"], r["touches"])
        if tier is None:
            continue
        ov = time_overlap(r["a_start"], r["a_end"], r["b_start"], r["b_end"])
        if horizon == "near" and ov == 0:
            continue  # near-term only cares about concurrent field work
        sav = savings(tier, r["overlap_m"])
        out.append({**r, "horizon": horizon, "tier": tier, "time_overlap": ov, "score": score(tier, ov),
                    "savings_low": sav["low"], "savings_high": sav["high"]})
    with conn.cursor() as cur:
        cur.executemany(UPSERT_SQL, out)
    keys = [f"{o['job_a']}|{o['job_b']}" for o in out]
    conn.execute("DELETE FROM opportunity WHERE horizon = %s AND status = 'not_contacted' AND job_a || '|' || job_b <> ALL(%s)",
                 (horizon, keys))  # drop stale pairs nobody has acted on
    return {"horizon": horizon, "pairs": len(out), "ms": round((time.perf_counter() - t0) * 1000)}
