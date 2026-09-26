RADIUS_M = 2000
WINDOW_H = 12

JOBS_SQL = """
WITH hits AS (
  SELECT DISTINCT ON (e.id, a.org_id) e.id AS event_id, e.ts, e.payload, a.id AS asset_id, a.org_id, a.name AS asset_name, a.geom
  FROM storm_event e JOIN asset a ON ST_DWithin(e.geom, a.geom, %(radius)s)
  WHERE e.kind IN ('lsr', 'spc_report')
  ORDER BY e.id, a.org_id, ST_Distance(e.geom, a.geom)
)
INSERT INTO job (id, org_id, name, description, horizon, job_type, geom, geom_quality, work_window, window_basis, in_service,
                 source_doc_id, extraction, confidence, simulated, resources)
SELECT 'em-' || org_id || '-' || replace(asset_id, '/', '-'), org_id,
       'Restore ' || coalesce(min(asset_name), 'substation') || ' area (' || min(payload->>'place') || ', ' || min(payload->>'state') || ')',
       count(*) || ' damage report(s) within 2 km: ' || string_agg(coalesce(payload->>'remark', payload->>'comments', ''), ' | ' ORDER BY ts),
       'emergency', 'restoration', (array_agg(geom))[1], 'matched_point',
       tstzrange(min(ts), max(ts) + make_interval(hours => %(hours)s)), 'derived', min(ts)::date, %(doc)s, 'feed',
       CASE WHEN bool_or((payload->>'power')::bool) THEN 0.9 ELSE 0.7 END, FALSE, ARRAY['crews', 'equipment', 'staging']
FROM hits GROUP BY org_id, asset_id  -- one job per substation, duplicates merged
"""


def build_restoration(conn):
    conn.execute("DELETE FROM job WHERE horizon = 'emergency'")
    if not conn.execute("SELECT 1 FROM storm_event LIMIT 1").fetchone():
        return 0
    doc = conn.execute("INSERT INTO source_doc (title, kind, url) VALUES ('Hurricane Helene storm reports (NWS LSR, SPC), Sep 2024', 'weather', "
                       "'https://mesonet.agron.iastate.edu/lsr/') RETURNING id").fetchone()["id"]
    conn.execute(JOBS_SQL, {"hours": WINDOW_H, "radius": RADIUS_M, "doc": doc})
    return conn.execute("SELECT count(*) AS n FROM job WHERE horizon = 'emergency'").fetchone()["n"]
