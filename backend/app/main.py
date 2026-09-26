import os
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import ASSUMPTIONS, MAX_DRIVE_MIN
from app import outreach, vendors
from app.crewly import agent, brief
from app.db import ROOT, get_conn
from app.engine.cost import savings
from app.engine.overlap import recompute
from app.engine import equipment
from app.engine.phases import build_phases
from app.geo.drive import Drive
from app.ingest import filing
from app.queries import JOB_SQL, OPP_SQL, shareable
from app.storm import replay

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
    return {**op, "a": by_id[op["job_a"]], "b": by_id[op["job_b"]], "shareable": shareable(op["tier"], op["a_phase"], op["b_phase"], op["drive_min"]),
            "savings": savings(op["tier"], op["overlap_m"], drive_min=op["drive_min"])}


class Recompute(BaseModel):
    horizon: str = "long"


@api.post("/opportunities/recompute")
def do_recompute(body: Recompute, conn=Depends(get_conn)):
    return recompute(conn, body.horizon)


class Savings(BaseModel):
    assumptions: dict[str, dict[str, float]] = {}


@api.post("/opportunities/{opp_id}/savings")
def estimate(opp_id: int, body: Savings, conn=Depends(get_conn)):
    op = conn.execute("SELECT tier, overlap_m, drive_min FROM opportunity WHERE id = %s", (opp_id,)).fetchone()
    if not op:
        raise HTTPException(404, "opportunity not found")
    return savings(op["tier"], op["overlap_m"], body.assumptions, op["drive_min"])


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


@api.get("/opportunities/{opp_id}/contacts")
def opp_contacts(opp_id: int, conn=Depends(get_conn)):
    return outreach.contacts(conn, opp_id)


@api.get("/opportunities/{opp_id}/outreach")
def opp_outreach(opp_id: int, conn=Depends(get_conn)):
    return outreach.listing(conn, opp_id)


class Draft(BaseModel):
    opportunity_id: int
    contact_id: int
    kind: str = "utility_intro"


class Edit(BaseModel):
    subject: str
    body: str


class Approve(BaseModel):
    approved_by: str


class Reply(BaseModel):
    summary: str = ""


def found(row, msg="outreach not found or in the wrong state"):
    if not row:
        raise HTTPException(409, msg)
    return row


@api.post("/outreach")
def draft_outreach(body: Draft, conn=Depends(get_conn)):
    return found(outreach.draft(conn, body.opportunity_id, body.contact_id, body.kind), "opportunity or contact not found")


@api.patch("/outreach/{outreach_id}")
def edit_outreach(outreach_id: int, body: Edit, conn=Depends(get_conn)):
    return found(outreach.edit(conn, outreach_id, body.subject, body.body))


@api.post("/outreach/{outreach_id}/approve")
def approve_outreach(outreach_id: int, body: Approve, conn=Depends(get_conn)):
    if not body.approved_by.strip():
        raise HTTPException(400, "approver name required")
    return found(outreach.approve(conn, outreach_id, body.approved_by.strip()))


@api.post("/outreach/{outreach_id}/send")
def send_outreach(outreach_id: int, conn=Depends(get_conn)):
    row, err = outreach.send(conn, outreach_id)
    if err:
        raise HTTPException(409, err)
    return row


@api.post("/outreach/{outreach_id}/replied")
def replied_outreach(outreach_id: int, body: Reply, conn=Depends(get_conn)):
    return found(outreach.mark_replied(conn, outreach_id, body.summary))


@api.get("/assumptions")
def assumptions():
    return ASSUMPTIONS


@api.get("/layers/tracts")
def tracts(conn=Depends(get_conn)):
    rows = conn.execute("SELECT geoid, risk, vulnerability, ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, 0.003), 4)::json AS g FROM tract").fetchall()
    return {"type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": r.pop("g"), "properties": r} for r in rows]}


@api.post("/ingest")
def ingest(file: UploadFile | None = File(None), url: str | None = Form(None), org: str | None = Form(None),
           org_name: str | None = Form(None), state: str = Form("SC"), conn=Depends(get_conn)):
    if not file and not url:
        raise HTTPException(400, "send a PDF file or a url")
    try:
        if file:
            body = file.file.read()
            if body[:4] != b"%PDF":
                raise HTTPException(422, "not a PDF")  # never write non-pdf uploads to disk
            path = filing.save(body, file.filename or "filing.pdf")
        else:
            path = filing.download(url)
        out = filing.ingest(conn, path, org, org_name, state, url=url)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except (ValueError, httpx.HTTPError) as e:
        raise HTTPException(400, f"could not fetch filing: {e}")
    if "error" in out:
        raise HTTPException(422, out["error"])
    return out


@api.get("/vendors")
def find_vendors(opportunity_id: int | None = None, lat: float | None = None, lon: float | None = None,
                 service: str = "crane rental", radius_km: float = 40, conn=Depends(get_conn)):
    if opportunity_id is not None:
        mid = vendors.midpoint(conn, opportunity_id)
        if not mid:
            raise HTTPException(404, "opportunity not found")
        lat, lon = mid["lat"], mid["lon"]
    if lat is None or lon is None:
        raise HTTPException(400, "give an opportunity_id or lat and lon")
    try:
        return {"lat": lat, "lon": lon, "service": service, "vendors": vendors.search(lat, lon, service, radius_km)}
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except httpx.HTTPError as e:
        raise HTTPException(502, f"places error: {e}")


@api.get("/drive/zone")
def drive_zone(opportunity_id: int, minutes: int = MAX_DRIVE_MIN, conn=Depends(get_conn)):
    op = conn.execute("SELECT ST_X(ST_StartPoint(link::geometry)) AS lon, ST_Y(ST_StartPoint(link::geometry)) AS lat FROM opportunity WHERE id = %s",
                      (opportunity_id,)).fetchone()
    if not op:
        raise HTTPException(404, "opportunity not found")
    road = Drive()
    ring = road.zone((op["lon"], op["lat"]), minutes)
    road.save()
    if not ring:
        raise HTTPException(503, "routing service unavailable")
    return {"type": "Feature", "properties": {"minutes": minutes, "from": [op["lon"], op["lat"]], "approx": True},
            "geometry": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}}


@api.get("/procurement")
def procurement(conn=Depends(get_conn)):
    return equipment.groups(conn)


@api.get("/storm/frame")
def storm_frame(at: datetime, conn=Depends(get_conn)):
    return replay.frame(conn, at)


@api.get("/layers/grid")
def grid(conn=Depends(get_conn)):
    rows = conn.execute("""SELECT voltage, ST_AsGeoJSON(ST_Simplify(geom, 0.0005), 4)::json AS g FROM grid_line
                           WHERE voltage >= 100""").fetchall()  # transmission only, lightly simplified
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": r["g"], "properties": {"voltage": r["voltage"]}} for r in rows]}


@api.get("/review")
def review(conn=Depends(get_conn)):
    return conn.execute("""SELECT id, org_id, reason, source_page, raw->>'name' AS name, raw->>'in_service' AS in_service,
                                  raw->'endpoints' AS endpoints FROM job_review ORDER BY org_id, raw->>'in_service'""").fetchall()


class Place(BaseModel):
    lon: float
    lat: float
    placed_by: str = "planner"


@api.post("/review/{review_id}/place")
def place(review_id: int, body: Place, conn=Depends(get_conn)):
    r = conn.execute("SELECT * FROM job_review WHERE id = %s", (review_id,)).fetchone()
    if not r or "id" not in r["raw"]:
        raise HTTPException(404, "review item not found or not a parsed project")
    j = r["raw"]
    conn.execute("""
        INSERT INTO job (id, org_id, name, ref, description, horizon, job_type, voltage_kv, endpoints, geom, geom_quality, work_window,
                         window_basis, in_service, cost_usd, source_doc_id, source_page, extraction, confidence, resources)
        VALUES (%(id)s, %(org_id)s, %(name)s, %(ref)s, %(description)s, 'long', %(job_type)s, %(voltage_kv)s, %(endpoints)s,
                ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography, 'manual', tstzrange(%(start)s::date, %(in_service)s::date),
                %(window_basis)s, %(in_service)s::date, %(cost_usd)s, %(doc)s, %(page)s, 'manual', 0.6, ARRAY['crews', 'row', 'staging'])""",
                 {**j, "lon": body.lon, "lat": body.lat, "doc": r["source_doc_id"], "page": r["source_page"]})
    conn.execute("DELETE FROM job_review WHERE id = %s", (review_id,))
    build_phases(conn)
    return {"job_id": j["id"], "long": recompute(conn, "long"), "near": recompute(conn, "near")}


class Chat(BaseModel):
    messages: list[dict[str, str]]


@api.post("/crewly")
def crewly(body: Chat, conn=Depends(get_conn)):
    return agent.run(conn, body.messages)


@api.get("/health")
def health(conn=Depends(get_conn)):
    return {"ok": True, "jobs": conn.execute("SELECT count(*) AS n FROM job").fetchone()["n"]}


app.include_router(api)

STATIC = os.environ.get("STATIC_DIR") or str(ROOT / "frontend/dist")
if os.path.isdir(STATIC):
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="web")  # built react app
