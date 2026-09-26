from fastapi import APIRouter, Depends, FastAPI, HTTPException
from pydantic import BaseModel

from app.config import ASSUMPTIONS, SHAREABLE, TIERS
from app.db import get_conn
from app.engine.cost import RANK, savings
from app.engine.overlap import recompute

app = FastAPI(title="OpenCrew")
api = APIRouter(prefix="/api")

STATUSES = ["not_contacted", "drafted", "sent", "replied", "call_scheduled", "agreed", "declined"]

JOB_SQL = """
SELECT j.id, j.org_id, o.name AS org_name, o.color, j.name, j.ref, j.description, j.horizon, j.job_type, j.voltage_kv,
       j.endpoints, j.geom_quality, j.phase, j.parent_job_id, lower(j.work_window) AS start_at, upper(j.work_window) AS end_at, j.window_basis,
       j.in_service, j.cost_usd, j.confidence, j.simulated, j.extraction, j.source_page,
       d.title AS source_title, d.local_path AS source_path, ST_AsGeoJSON(j.geom)::json AS geometry
FROM job j JOIN org o ON o.id = j.org_id LEFT JOIN source_doc d ON d.id = j.source_doc_id
"""

OPP_SQL = """
SELECT op.id, op.job_a, op.job_b, op.horizon, op.distance_m, op.center_distance_m, op.overlap_m, op.tier,
       op.time_overlap, op.time_gap_days, op.risk, op.vulnerability, op.score, op.flags, op.savings_low, op.savings_high,
       op.status, ST_AsGeoJSON(op.link)::json AS link,
       ja.name AS a_name, ja.phase AS a_phase, ja.org_id AS a_org, oa.color AS a_color, ja.confidence AS a_conf, ja.geom_quality AS a_quality,
       jb.name AS b_name, jb.phase AS b_phase, jb.org_id AS b_org, ob.color AS b_color, jb.confidence AS b_conf, jb.geom_quality AS b_quality
FROM opportunity op
JOIN job ja ON ja.id = op.job_a JOIN org oa ON oa.id = ja.org_id
JOIN job jb ON jb.id = op.job_b JOIN org ob ON ob.id = jb.org_id
"""


def shareable(tier):
    return [r for name, _ in TIERS if RANK[name] >= RANK[tier] for r in SHAREABLE[name]]  # closer tiers share everything further ones do


@api.get("/orgs")
def orgs(conn=Depends(get_conn)):
    return conn.execute("SELECT * FROM org ORDER BY id").fetchall()


@api.get("/jobs")
def jobs(horizon: str | None = "long", org: str | None = None, conn=Depends(get_conn)):
    rows = conn.execute(JOB_SQL + " WHERE (%(h)s::text IS NULL OR j.horizon = %(h)s) AND (%(o)s::text IS NULL OR j.org_id = %(o)s) ORDER BY j.id",
                        {"h": horizon, "o": org}).fetchall()
    return {"type": "FeatureCollection",
            "features": [{"type": "Feature", "id": r["id"], "geometry": r.pop("geometry"), "properties": r} for r in rows]}


@api.get("/opportunities")
def opportunities(horizon: str = "long", tier: str | None = None, min_score: float = 0, limit: int = 200, conn=Depends(get_conn)):
    return conn.execute(OPP_SQL + " WHERE op.horizon = %(h)s AND (%(t)s::text IS NULL OR op.tier = %(t)s) AND op.score >= %(m)s"
                        " ORDER BY op.score DESC, op.distance_m LIMIT %(l)s",
                        {"h": horizon, "t": tier, "m": min_score, "l": limit}).fetchall()


@api.get("/opportunities/{opp_id}")
def opportunity(opp_id: int, conn=Depends(get_conn)):
    op = conn.execute(OPP_SQL + " WHERE op.id = %s", (opp_id,)).fetchone()
    if not op:
        raise HTTPException(404, "opportunity not found")
    job_rows = conn.execute(JOB_SQL + " WHERE j.id IN (%s, %s)", (op["job_a"], op["job_b"])).fetchall()
    by_id = {j["id"]: j for j in job_rows}
    return {**op, "a": by_id[op["job_a"]], "b": by_id[op["job_b"]], "shareable": shareable(op["tier"]),
            "savings": savings(op["tier"], op["overlap_m"])}


class Recompute(BaseModel):
    horizon: str = "long"


@api.post("/opportunities/recompute")
def do_recompute(body: Recompute, conn=Depends(get_conn)):
    return recompute(conn, body.horizon)


class Savings(BaseModel):
    assumptions: dict[str, dict[str, float]] = {}


@api.post("/opportunities/{opp_id}/savings")
def estimate(opp_id: int, body: Savings, conn=Depends(get_conn)):
    op = conn.execute("SELECT tier, overlap_m FROM opportunity WHERE id = %s", (opp_id,)).fetchone()
    if not op:
        raise HTTPException(404, "opportunity not found")
    return savings(op["tier"], op["overlap_m"], body.assumptions)


class Status(BaseModel):
    status: str


@api.patch("/opportunities/{opp_id}/status")
def set_status(opp_id: int, body: Status, conn=Depends(get_conn)):
    if body.status not in STATUSES:
        raise HTTPException(400, f"status must be one of {STATUSES}")
    row = conn.execute("UPDATE opportunity SET status = %s WHERE id = %s RETURNING id, status", (body.status, opp_id)).fetchone()
    if not row:
        raise HTTPException(404, "opportunity not found")
    return row


@api.get("/assumptions")
def assumptions():
    return ASSUMPTIONS


@api.get("/review")
def review(conn=Depends(get_conn)):
    return conn.execute("SELECT id, org_id, reason, source_page, raw->>'name' AS name FROM job_review ORDER BY id").fetchall()


app.include_router(api)
