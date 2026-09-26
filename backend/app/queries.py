from app.config import SHAREABLE, TIERS
from app.engine.cost import RANK

JOB_SQL = """
SELECT j.id, j.org_id, o.name AS org_name, o.color, j.name, j.ref, j.description, j.horizon, j.job_type, j.voltage_kv,
       j.endpoints, j.geom_quality, j.phase, j.parent_job_id, lower(j.work_window) AS start_at, upper(j.work_window) AS end_at, j.window_basis,
       j.in_service, j.cost_usd, j.confidence, j.simulated, j.extraction, j.source_page,
       d.title AS source_title, d.local_path AS source_path, ST_AsGeoJSON(j.geom)::json AS geometry,
       (SELECT json_agg(json_build_object('observed_at', v.observed_at, 'start_at', lower(v.work_window), 'end_at', upper(v.work_window)) ORDER BY v.observed_at)
        FROM job_version v WHERE v.job_id = coalesce(j.parent_job_id, j.id) AND v.work_window <> j.work_window
          AND j.parent_job_id IS NULL) AS history
FROM job j JOIN org o ON o.id = j.org_id LEFT JOIN source_doc d ON d.id = j.source_doc_id
"""

OPP_SQL = """
SELECT op.id, op.job_a, op.job_b, op.horizon, op.distance_m, op.center_distance_m, op.overlap_m, op.tier,
       op.time_overlap, op.time_gap_days, op.risk, op.vulnerability, op.score, op.flags, op.savings_low, op.savings_high,
       op.status, ST_AsGeoJSON(op.link)::json AS link,
       ja.name AS a_name, ja.phase AS a_phase, lower(ja.work_window) AS a_start, ja.org_id AS a_org, oa.color AS a_color, ja.confidence AS a_conf, ja.geom_quality AS a_quality,
       jb.name AS b_name, jb.phase AS b_phase, lower(jb.work_window) AS b_start, jb.org_id AS b_org, ob.color AS b_color, jb.confidence AS b_conf, jb.geom_quality AS b_quality
FROM opportunity op
JOIN job ja ON ja.id = op.job_a JOIN org oa ON oa.id = ja.org_id
JOIN job jb ON jb.id = op.job_b JOIN org ob ON ob.id = jb.org_id
"""


def shareable(tier):
    return [r for name, _ in TIERS if RANK[name] >= RANK[tier] for r in SHAREABLE[name]]  # closer tiers share everything further ones do
