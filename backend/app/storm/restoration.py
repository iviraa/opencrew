RADIUS_M = 2000
WINDOW_H = 12

JOBS_SQL = """
WITH pts AS (
  SELECT i.id AS incident_id, i.ts, i.kind, i.where_text, i.confidence, i.verified, i.sources, d.path[1] AS n, d.geom::geography AS pt
  FROM incident i, ST_DumpPoints(i.footprint::geometry) d WHERE i.mode = 'replay'  -- every merged report location
), hits AS (
  SELECT DISTINCT ON (p.incident_id, p.n, a.org_id) p.incident_id, p.ts, p.kind, p.where_text, p.confidence, p.verified, p.sources,
         a.id AS asset_id, a.org_id, a.name AS asset_name, a.geom
  FROM pts p JOIN asset a ON ST_DWithin(p.pt, a.geom, %(radius)s)
  ORDER BY p.incident_id, p.n, a.org_id, ST_Distance(p.pt, a.geom)
)
INSERT INTO job (id, org_id, name, description, horizon, job_type, geom, geom_quality, work_window, window_basis, in_service,
                 source_doc_id, extraction, confidence, simulated, resources)
SELECT 'em-' || org_id || '-' || replace(asset_id, '/', '-'), org_id,
       'Restore ' || coalesce(min(asset_name), 'substation') || ' area (' || (array_agg(where_text ORDER BY verified DESC, ts))[1] || ')'
         || CASE WHEN bool_or(verified) THEN '' ELSE ' - needs confirmation' END,
       count(DISTINCT incident_id) || ' incident(s) within 2 km: ' || string_agg(DISTINCT kind || ' (' || CASE WHEN verified THEN 'verified' ELSE 'unverified' END
         || ', ' || coalesce(sources->0->>'quote_evidence', '') || ')', ' | '),
       'emergency', 'restoration', (array_agg(geom))[1], 'matched_point',
       tstzrange(min(ts), max(ts) + make_interval(hours => %(hours)s)), 'derived', min(ts)::date, %(doc)s, 'feed',
       CASE WHEN bool_or(verified) THEN max(confidence) ELSE least(max(confidence), 0.4) END,  -- unverified news alone stays low priority
       FALSE, ARRAY['crews', 'equipment', 'staging']
FROM hits GROUP BY org_id, asset_id  -- one job per substation, duplicates merged
"""


def build_restoration(conn):
    conn.execute("DELETE FROM job WHERE horizon = 'emergency'")
    if not conn.execute("SELECT 1 FROM incident WHERE mode = 'replay' LIMIT 1").fetchone():
        return 0
    doc = conn.execute("INSERT INTO source_doc (title, kind, url) VALUES ('Hurricane Helene incidents (NWS LSR, SPC, news), Sep 2024', 'weather', "
                       "'https://mesonet.agron.iastate.edu/lsr/') RETURNING id").fetchone()["id"]
    conn.execute(JOBS_SQL, {"hours": WINDOW_H, "radius": RADIUS_M, "doc": doc})
    return conn.execute("SELECT count(*) AS n FROM job WHERE horizon = 'emergency'").fetchone()["n"]
