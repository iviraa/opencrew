"""Endpoints for the Crewly app: everything is seen from the logged-in company's side."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import current_user
from app.companies import companies, partner
from app.crewly import agent
from app.crewly import proactive
from app.crewly.app_tools import app_system, app_tools, mine_sql
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


@router.post("/chat")
def chat(body: Chat, user=Depends(current_user), conn=Depends(get_conn)):
    user = {**user, "memories": load_memories(user)}  # the company's saved notes, read once per message
    return agent.run(conn, body.messages[-20:], app_system(user), app_tools(user))


@router.post("/proactive/run")
def proactive_run(user=Depends(current_user), conn=Depends(get_conn)):
    return proactive.scan(conn, user["company"])  # new suggestions land in the bell over realtime
