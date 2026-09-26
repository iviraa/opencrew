KIND = """CASE
  WHEN name ~* 'capacitor|cap bank' THEN 'capacitor'
  WHEN name ~* 'autobank|auto bank|transformer|\\mbank\\M|mva' THEN 'transformer'
  WHEN name ~* 'reactor' THEN 'reactor'
  WHEN name ~* 'relay' THEN 'relay'
  WHEN name ~* 'breaker|\\mbus|switch' THEN 'breaker/bus'
  WHEN name ~* 'tap|new sub|substation|fold-in|construct' THEN 'new substation/tap'
END"""

SQL = """
WITH raw AS (
  SELECT id, org_id, name, voltage_kv, in_service, TRUE AS placed FROM job WHERE horizon = 'long' AND job_type = 'substation'
  UNION ALL
  SELECT raw->>'id', org_id, raw->>'name', (raw->>'voltage_kv')::int, (raw->>'in_service')::date, FALSE
  FROM job_review WHERE raw->>'job_type' = 'substation'
), sub AS (
  SELECT *, """ + KIND + """ AS kind FROM raw
)
SELECT d.voltage_kv, d.kind, d.id AS desc_id, d.name AS desc_name, d.in_service AS desc_in_service, d.placed AS desc_placed,
       g.id AS gpc_id, g.name AS gpc_name, g.in_service AS gpc_in_service, g.placed AS gpc_placed,
       abs(extract(year FROM d.in_service) - extract(year FROM g.in_service))::int AS year_gap,
       CASE WHEN abs(extract(year FROM d.in_service) - extract(year FROM g.in_service)) <= 1 THEN 'joint procurement' ELSE 'shared spare pool' END AS reason
FROM sub d JOIN sub g ON d.org_id = 'desc' AND g.org_id = 'gpc' AND d.voltage_kv = g.voltage_kv AND d.kind = g.kind
  AND (abs(extract(year FROM d.in_service) - extract(year FROM g.in_service)) <= 1 OR d.name ~* 'spare' OR g.name ~* 'spare')  -- spares help any year
ORDER BY d.voltage_kv DESC, d.in_service, g.in_service
"""


def groups(conn):
    out = {}
    for r in conn.execute(SQL).fetchall():
        key = (r["voltage_kv"], r["desc_id"])
        g = out.setdefault(key, {"voltage_kv": r["voltage_kv"], "kind": r["kind"], "desc": {"id": r["desc_id"], "name": r["desc_name"],
                                 "in_service": r["desc_in_service"], "placed": r["desc_placed"]}, "gpc": []})
        g["gpc"].append({"id": r["gpc_id"], "name": r["gpc_name"], "in_service": r["gpc_in_service"], "placed": r["gpc_placed"], "year_gap": r["year_gap"], "reason": r["reason"]})
    return list(out.values())
