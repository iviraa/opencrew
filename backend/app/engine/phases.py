from app.config import PHASES

PHASE_SQL = """
INSERT INTO job (id, org_id, name, ref, horizon, job_type, voltage_kv, endpoints, geom, geom_quality, work_window, window_basis,
                 in_service, parent_job_id, phase, source_doc_id, source_page, extraction, confidence, resources)
SELECT j.id || '-p' || %(n)s, j.org_id, j.name, j.ref, 'near', 'phase', j.voltage_kv, j.endpoints, j.geom, j.geom_quality,
       tstzrange(lower(j.work_window) + (upper(j.work_window) - lower(j.work_window)) * %(a)s,
                 lower(j.work_window) + (upper(j.work_window) - lower(j.work_window)) * %(b)s),
       'derived', j.in_service, j.id, %(phase)s, j.source_doc_id, j.source_page, j.extraction, j.confidence, %(resources)s
FROM job j WHERE j.horizon = 'long' AND (%(only)s::text[] IS NULL OR j.id = ANY(%(only)s))
"""

RESOURCES = {"survey & permitting": ["row", "permits"], "clearing": ["crews", "equipment"],
             "construction": ["crews", "cranes", "staging"], "energization": ["outage"]}


def build_phases(conn, only=None):
    """Derive the near-term phases of every long job, or with `only` just of those jobs (a refresh touching a few)."""
    only = list(only) if only is not None else None
    conn.execute("DELETE FROM job WHERE horizon = 'near' AND (%(only)s::text[] IS NULL OR parent_job_id = ANY(%(only)s))", {"only": only})
    start = 0.0
    for n, (phase, share) in enumerate(PHASES, start=1):
        conn.execute(PHASE_SQL, {"n": n, "a": start, "b": start + share, "phase": phase, "resources": RESOURCES[phase], "only": only})
        start += share
    return conn.execute("SELECT count(*) AS n FROM job WHERE horizon = 'near'").fetchone()["n"]
