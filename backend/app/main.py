import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import ASSUMPTIONS, MAX_DRIVE_MIN, STATUSES
from app import app_api, outreach, vendors, weather_api
from app.feasibility import api as feasibility_api
from app.hazards import api as hazards_api
from app.planner import api as planner_api
from app.companies import companies
from app.crewly import agent, brief, proactive, generate_api
from app.db import ROOT, connect, get_conn
from app.engine.cost import savings_for
from app.engine.overlap import recompute
from app.engine import equipment, plan
from app.engine.phases import build_phases
from app.geo.drive import Drive
from app.ingest import filing
from app.queries import JOB_SQL, OPP_SQL, shareable
from app.storm import briefing, helene, live, replay, response

def poll_once():
    with connect() as conn:
        return live.poll(conn)


def suggest_once(company):
    with connect() as conn:
        return proactive.scan(conn, company)


@asynccontextmanager
async def lifespan(_app):
    minutes = float(os.environ.get("LIVE_POLL_MINUTES") or 0)  # off unless set, so tests never hit live feeds

    async def loop():
        while True:
            try:
                await asyncio.to_thread(poll_once)
            except Exception as e:  # a bad poll must not kill the loop
                print("live poll failed:", e)
            await asyncio.sleep(minutes * 60)

    task = asyncio.create_task(loop()) if minutes > 0 else None
    hazard_minutes = float(os.environ.get("HAZARDS_REFRESH_MINUTES") or 0)  # live hazard layers, off unless set

    def hazards_once():
        from app.hazards import layers as hazard_layers
        with connect() as conn:
            return hazard_layers.refresh(conn)

    async def hazards_loop():
        while True:
            try:
                await asyncio.to_thread(hazards_once)
            except Exception as e:  # a bad feed must not kill the loop
                print("hazard refresh failed:", e)
            await asyncio.sleep(hazard_minutes * 60)

    hazard_task = asyncio.create_task(hazards_loop()) if hazard_minutes > 0 else None
    nudge = float(os.environ.get("CREWLY_PROACTIVE_MINUTES") or 0)  # crewly's suggestions, off unless set

    async def suggest():
        while True:
            for company in companies():
                try:
                    await asyncio.to_thread(suggest_once, company)
                except Exception as e:  # one bad scan must not stop the others
                    print("crewly suggestions failed:", company, e)
            await asyncio.sleep(nudge * 60)

    nudger = asyncio.create_task(suggest()) if nudge > 0 else None
    plan_minutes = float(os.environ.get("PLANNER_MINUTES") or 0)  # nightly coordination plans, off unless set

    async def plans():
        from app.planner import nightly
        while True:
            for company in companies():
                try:
                    await asyncio.to_thread(nightly.refresh, company)
                except Exception as e:  # one company's plan must not stop the others
                    print("plan refresh failed:", company, e)
            await asyncio.sleep(plan_minutes * 60)

    planner_task = asyncio.create_task(plans()) if plan_minutes > 0 else None
    news_minutes = float(os.environ.get("NEWS_REFRESH_MINUTES") or 0)  # utility news, off unless set

    def news_once():
        from app.news import feed
        with connect() as conn:
            return feed.run(conn, list(companies()), rebuild_lexicon=False)

    async def news_loop():
        while True:
            try:
                await asyncio.to_thread(news_once)
            except Exception as e:  # a bad source must not kill the loop
                print("news refresh failed:", e)
            await asyncio.sleep(news_minutes * 60)

    news_task = asyncio.create_task(news_loop()) if news_minutes > 0 else None
    yield
    for t in (task, hazard_task, nudger, planner_task, news_task):
        if t:
            t.cancel()


app = FastAPI(title="OpenCrew", lifespan=lifespan)
if os.environ.get("CORS_ORIGINS"):  # the frontend is hosted on another domain, e.g. vercel
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in os.environ["CORS_ORIGINS"].split(",") if o.strip()],
                       allow_methods=["*"], allow_headers=["*"])
api = APIRouter(prefix="/api")


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
            "savings": savings_for(conn, op)}


class Recompute(BaseModel):
    horizon: str = "long"


@api.post("/opportunities/recompute")
def do_recompute(body: Recompute, conn=Depends(get_conn)):
    return recompute(conn, body.horizon)


class Savings(BaseModel):
    assumptions: dict[str, dict[str, float]] = {}


@api.post("/opportunities/{opp_id}/savings")
def estimate(opp_id: int, body: Savings, conn=Depends(get_conn)):
    op = conn.execute("SELECT job_a, job_b, tier, overlap_m, drive_min, time_overlap FROM opportunity WHERE id = %s", (opp_id,)).fetchone()
    if not op:
        raise HTTPException(404, "opportunity not found")
    return savings_for(conn, op, body.assumptions)


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
def storm_frame(at: datetime | None = None, mode: str = "replay", conn=Depends(get_conn)):
    if mode not in ("replay", "live"):
        raise HTTPException(400, "mode must be replay or live")
    return replay.frame(conn, at or datetime.now(timezone.utc), mode)


INCIDENT_COLS = """id, ts, mode, kind, where_text, precision, utility_mentioned, customers_affected, confidence, verified, needs_confirmation,
                   ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon"""


@api.get("/incidents")
def incidents_list(at: datetime | None = None, mode: str = "replay", hours: float = 96, conn=Depends(get_conn)):
    t = at or datetime.now(timezone.utc)
    return conn.execute(f"SELECT {INCIDENT_COLS}, jsonb_array_length(sources) AS n_sources FROM incident "
                        "WHERE mode = %s AND ts <= %s AND ts >= %s ORDER BY verified DESC, confidence DESC, ts",
                        (mode, t, t - timedelta(hours=hours))).fetchall()


@api.get("/incidents/{incident_id}")
def incident_detail(incident_id: int, conn=Depends(get_conn)):
    row = conn.execute(f"SELECT {INCIDENT_COLS}, sources, nearest, ST_NPoints(footprint::geometry) AS n_points FROM incident WHERE id = %s",
                       (incident_id,)).fetchone()
    if not row:
        raise HTTPException(404, "incident not found")
    return row


@api.get("/weather/alerts")
def weather_alerts(conn=Depends(get_conn)):
    rows = conn.execute("""SELECT ts, payload, ST_AsGeoJSON(geom, 4)::json AS geometry FROM storm_event
                           WHERE kind = 'nws_alert' AND payload->>'mode' = 'live' AND (payload->>'expire')::timestamptz > now()""").fetchall()
    return {"type": "FeatureCollection", "features": [replay.feature(r) for r in rows]}


@api.get("/weather/phase_risks")
def weather_phase_risks(conn=Depends(get_conn)):
    return conn.execute("SELECT job_id, site, day, gust_mph, work, alert, fetched_at FROM phase_risk ORDER BY day, gust_mph DESC").fetchall()


@api.get("/live/frame")
def live_frame(at: datetime | None = None, scenario: str = "none", conn=Depends(get_conn)):
    if scenario not in ("none", "helene"):
        raise HTTPException(400, "scenario must be none or helene")
    return live.frame(conn, at, scenario)  # what the map shows at a moment: live feeds, or a planted storm


@api.post("/live/poll")
def live_poll(conn=Depends(get_conn)):
    return live.poll(conn)  # official feeds, latest news, incidents, phase wind risks


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


class PlanConstraints(BaseModel):
    constraints: dict = {}


@api.post("/plan/constraints")
def plan_constraints(body: PlanConstraints, conn=Depends(get_conn)):
    return plan.validate(conn, body.constraints)


@api.post("/plan/solve")
def plan_solve(body: PlanConstraints, conn=Depends(get_conn)):
    checked = plan.validate(conn, body.constraints)
    if not checked["valid"]:
        raise HTTPException(422, "; ".join(checked["errors"]))
    return plan.run(conn, checked["constraints"])


@api.get("/plan")
def plan_latest(conn=Depends(get_conn)):
    return plan.latest(conn)


@api.get("/plan/explain")
def plan_explain(opportunity_id: int | None = None, project: str | None = None, conn=Depends(get_conn)):
    if opportunity_id is None and not project:
        raise HTTPException(400, "give an opportunity_id or a project name")
    return plan.explain(conn, opportunity_id, project)


@api.get("/health")
def health():
    try:
        with connect() as conn:
            return {"ok": True, "jobs": conn.execute("SELECT count(*) AS n FROM job").fetchone()["n"]}
    except Exception as e:  # stay up and say what is wrong with the database, without the url
        from urllib.parse import urlparse
        host = urlparse(os.environ.get("DATABASE_URL", "")).hostname or "not set (using the local default)"
        return {"ok": False, "database_host": host, "database": f"{type(e).__name__}: {str(e)[:200]}"}


# ---------- storm response: pre-storm briefing and restoration crew plan ----------

def storm_time(at, scenario, default_offset_h):
    if at is not None:
        return at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    return helene.LANDFALL + timedelta(hours=default_offset_h) if scenario == "helene" else datetime.now(timezone.utc)


@api.get("/storm/briefing")
def storm_briefing(at: datetime | None = None, scenario: str = "helene", safety_margin_h: float | None = None,
                   crews_per_substation: float | None = None, conn=Depends(get_conn)):
    opts = {k: v for k, v in {"safety_margin_h": safety_margin_h, "crews_per_substation": crews_per_substation}.items() if v is not None}
    return briefing.build(conn, storm_time(at, scenario, -36), scenario, opts)


@api.get("/storm/restoration_plan")
def storm_restoration(at: datetime | None = None, scenario: str = "helene", mutual_aid: bool = True, crews_gpc: int | None = None,
                      crews_desc: int | None = None, repair_h: float | None = None, max_drive_min: float | None = None, conn=Depends(get_conn)):
    opts = {k: v for k, v in {"crews_gpc": crews_gpc, "crews_desc": crews_desc, "repair_h": repair_h, "max_drive_min": max_drive_min}.items() if v is not None}
    return response.build(conn, storm_time(at, scenario, 24), scenario, mutual_aid, opts)


# ---------- forecast outlooks and long-range hazards ----------

import threading  # noqa: E402

from app.storm import hazards, outlook  # noqa: E402  kept with its endpoints

OUTLOOK_REFRESH = {"at": None}


def outlook_stale(conn, hours=3):
    last = OUTLOOK_REFRESH["at"] or conn.execute("SELECT max(issued) AS t FROM outlook WHERE mode = 'live'").fetchone()["t"]
    return last is None or datetime.now(timezone.utc) - last > timedelta(hours=hours)


def refresh_outlooks():
    OUTLOOK_REFRESH["at"] = datetime.now(timezone.utc)  # set first so parallel requests do not pile up
    try:
        with connect() as conn:
            outlook.fetch_live(conn)
    except Exception as e:  # a bad feed must not break the map
        print("outlook refresh failed:", e)


def outlook_clock(at, scenario):
    """(view, known, clock): the map can look ahead of the clock, but only with forecasts issued by then."""
    if scenario not in ("none", "helene"):
        raise HTTPException(400, "scenario must be none or helene")
    clock = replay.REPLAY[1] if scenario == "helene" else datetime.now(timezone.utc)
    view = min(at or clock, clock + timedelta(days=7))
    return view, min(view, clock), clock


@api.get("/outlook/frame")
def outlook_frame(at: datetime | None = None, scenario: str = "none", conn=Depends(get_conn)):
    view, known, clock = outlook_clock(at, scenario)
    mode = "replay" if scenario == "helene" else "live"
    if mode == "live" and os.environ.get("LIVE_POLL_MINUTES") and outlook_stale(conn):
        threading.Thread(target=refresh_outlooks, daemon=True).start()  # next request sees today's outlooks
    return {"outlooks": outlook.frame(conn, view, known, mode), "heads_up": outlook.heads_up(conn, known, mode),
            "view": view.isoformat(), "known": known.isoformat(), "clock": clock.isoformat(), "available": outlook.available(conn, mode)}


@api.post("/outlook/refresh")
def outlook_refresh(conn=Depends(get_conn)):
    return outlook.fetch_live(conn)  # today's spc, wpc and nhc outlooks


@api.get("/hazards")
def hazards_all(conn=Depends(get_conn)):
    return hazards.all_hazards(conn)  # floodplain and hurricane history per long-range job


@api.get("/hazards/{job_id}")
def hazards_one(job_id: str, conn=Depends(get_conn)):
    h = hazards.one(conn, job_id)
    if not h:
        raise HTTPException(404, "no hazard check for this job yet")
    return h


app.include_router(api)
app.include_router(app_api.router)
app.include_router(weather_api.router)
app.include_router(hazards_api.router)
app.include_router(feasibility_api.router)
app.include_router(planner_api.router)
from app.news import api as news_api  # noqa: E402  kept with the other routers
app.include_router(news_api.router)
app.include_router(generate_api.router)

@app.get("/config.js", include_in_schema=False)
def web_config():
    """Public settings for the built frontend, so the image needs no build-time variables."""
    cfg = {"supabaseUrl": os.environ.get("SUPABASE_URL", ""), "supabaseKey": os.environ.get("SUPABASE_PUBLISHABLE_KEY", ""), "apiUrl": ""}
    return Response(f"window.__CREWLY__ = {json.dumps(cfg)};", media_type="application/javascript", headers={"Cache-Control": "no-store"})


STATIC = os.environ.get("STATIC_DIR") or str(ROOT / "frontend/dist")
if os.path.isdir(STATIC):
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="web")  # built react app
