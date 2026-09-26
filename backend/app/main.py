from fastapi import APIRouter, Depends, FastAPI, HTTPException
from pydantic import BaseModel

from app.config import ASSUMPTIONS
from app.crewly import agent, brief
from app.db import get_conn
from app.engine.cost import savings
from app.engine.overlap import recompute
from app.queries import JOB_SQL, OPP_SQL, shareable

app = FastAPI(title="OpenCrew")
api = APIRouter(prefix="/api")

STATUSES = ["not_contacted", "drafted", "sent", "replied", "call_scheduled", "agreed", "declined"]

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


@api.post("/opportunities/{opp_id}/brief")
def make_brief(opp_id: int, conn=Depends(get_conn)):
    out = brief.build(conn, opp_id)
    if not out:
        raise HTTPException(404, "opportunity not found")
    return out


@api.get("/assumptions")
def assumptions():
    return ASSUMPTIONS


@api.get("/layers/tracts")
def tracts(conn=Depends(get_conn)):
    rows = conn.execute("SELECT geoid, risk, vulnerability, ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, 0.003), 4)::json AS g FROM tract").fetchall()
    return {"type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": r.pop("g"), "properties": r} for r in rows]}


@api.get("/review")
def review(conn=Depends(get_conn)):
    return conn.execute("SELECT id, org_id, reason, source_page, raw->>'name' AS name FROM job_review ORDER BY id").fetchall()


class Chat(BaseModel):
    messages: list[dict[str, str]]


@api.post("/crewly")
def crewly(body: Chat, conn=Depends(get_conn)):
    return agent.run(conn, body.messages)


app.include_router(api)
