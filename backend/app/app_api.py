"""Endpoints for the Crewly app: everything is seen from the logged-in company's side."""
import math

import os
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import current_user
from app.companies import companies, partner, short
from app.crewly import agent
from app.crewly import proactive
from app.crewly.app_tools import app_system, app_tools, mine_sql
from app.crewly.generate_tools import settle
from app.crewly.memory_tools import load_memories
from app.db import get_conn
from app.queries import JOB_SQL

router = APIRouter(prefix="/api/app")


def features(rows):
    return {"type": "FeatureCollection",
            "features": [{"type": "Feature", "id": r["id"], "geometry": r.pop("geometry"), "properties": r} for r in rows]}


@router.get("/me")
def me(user=Depends(current_user)):
    c = companies()[user["company"]]
    return {"company": c["id"], "name": c["name"], "short": c["short"], "color": c["color"], "state": c["state"], "username": user["username"]}


@router.get("/companies")
def company_list(user=Depends(current_user)):
    return list(companies().values())


@router.get("/directory")
def directory():
    """Who can log in, for the login page's picker (public: names and demo usernames only)."""
    return [{k: c[k] for k in ("id", "name", "short", "state", "login", "color")} for c in companies().values() if c["login"]]


@router.get("/projects")
def projects(user=Depends(current_user), conn=Depends(get_conn)):
    rows = conn.execute(JOB_SQL + " WHERE j.horizon = 'long' AND j.org_id = %s ORDER BY lower(j.work_window)", (user["company"],)).fetchall()
    return features(rows)


@router.get("/context_projects")
def context_projects(bbox: str = "", user=Depends(current_user), conn=Depends(get_conn)):
    """Other utilities' placed long-horizon projects inside a bbox, simplified: the quiet context layer under our map."""
    try:
        w, s, e, n = [float(x) for x in bbox.split(",")]
        if not all(math.isfinite(v) for v in (w, s, e, n)):
            raise ValueError
    except ValueError:
        raise HTTPException(400, "bbox must be west,south,east,north")
    w, s, e, n = max(-180.0, min(w, e)), max(-90.0, min(s, n)), min(180.0, max(w, e)), min(90.0, max(s, n))
    tol = max(0.0005, (e - w) / 2000)  # about a screen pixel at the box width
    rows = conn.execute("""SELECT j.id, j.name, j.org_id, j.voltage_kv, ST_AsGeoJSON(ST_Simplify(j.geom::geometry, %s), 5)::json AS geom,
                                  (j.geom_quality IN ('county_area', 'approx_area') OR j.located_via @> '[{"centroid": true}]') AS dotted
                           FROM job j WHERE j.horizon = 'long' AND j.org_id <> %s AND j.geom IS NOT NULL
                             AND j.geom::geometry && ST_MakeEnvelope(%s, %s, %s, %s, 4326) ORDER BY j.voltage_kv DESC NULLS LAST LIMIT 2500""",
                        (tol, user["company"], w, s, e, n)).fetchall()
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": r["geom"], "properties": {
        "id": r["id"], "name": r["name"], "org_id": r["org_id"], "org": short(r["org_id"]), "kv": r["voltage_kv"], "dotted": bool(r["dotted"])}} for r in rows if r["geom"]]}


@router.get("/overlaps")
def overlaps(user=Depends(current_user), conn=Depends(get_conn)):
    opps = conn.execute(mine_sql(user["company"]) + " ORDER BY op.score DESC, op.distance_m").fetchall()
    for o in opps:
        o["partner"] = partner(o, user["company"])
    ids = list({o["job_a"] for o in opps} | {o["job_b"] for o in opps})
    jobs = conn.execute(JOB_SQL + " WHERE j.id = ANY(%s)", (ids,)).fetchall() if ids else []
    return {"overlaps": opps, "jobs": features(jobs)}  # jobs: both sides of every overlap, for the map


class Chat(BaseModel):
    messages: list[dict[str, str]]


HARD = re.compile(r"\b(plan|what if|what-if|shift|scenario|compare|versus|vs\.?|chart|graph|trend|report|memo|agenda|which|best|most|least|rank|why|explain|"
                  r"replay|storm|sensitivity|all three|these|them|both)\b", re.I)


def tier_for(messages):
    """pro for turns that need judgment or several tools, flash for lookups; CREWLY_MODEL_TIER=pro|flash overrides."""
    forced = os.environ.get("CREWLY_MODEL_TIER", "auto").lower()
    if forced in ("pro", "flash"):
        return forced
    last = next((m["text"] for m in reversed(messages) if m["role"] != "model"), "")
    return "pro" if HARD.search(last) or len(last) > 160 else "flash"


def recent_refs(messages):
    """Overlap ids the conversation just used, newest first, so "these three" and "that one" resolve without guessing."""
    ids = []
    for m in reversed(messages[-8:]):
        for i in re.findall(r"#(\d{1,7})\b", m["text"]):
            if i not in ids:
                ids.append(i)
    return ids[:8]


@router.post("/chat")
def chat(body: Chat, user=Depends(current_user), conn=Depends(get_conn)):
    user = {**user, "memories": load_memories(user)}  # the company's saved notes, read once per message
    msgs = body.messages[-30:]
    refs = recent_refs(msgs)
    system = app_system(user) + (f"\n\nOverlaps referred to in the last few messages, newest first: {', '.join('#' + i for i in refs)}. "
                                 "When the user says 'these', 'them', 'that one' or 'the three', they mean these." if refs else "")
    return settle(conn, user["company"], agent.run(conn, msgs, system, app_tools(user), tier_for(msgs)))


@router.post("/proactive/run")
def proactive_run(user=Depends(current_user), conn=Depends(get_conn)):
    return proactive.scan(conn, user["company"])  # new suggestions land in the bell over realtime
