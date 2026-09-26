"""Endpoints for the Crewly app: everything is seen from the logged-in company's side."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import current_user
from app.crewly import agent
from app.crewly.app_tools import NAMES, app_system, app_tools, mine_sql
from app.db import get_conn
from app.queries import JOB_SQL

router = APIRouter(prefix="/api/app")


def features(rows):
    return {"type": "FeatureCollection",
            "features": [{"type": "Feature", "id": r["id"], "geometry": r.pop("geometry"), "properties": r} for r in rows]}


@router.get("/me")
def me(user=Depends(current_user)):
    return {"company": user["company"], "name": NAMES[user["company"]], "other": user["other"], "other_name": NAMES[user["other"]],
            "username": user["username"]}


@router.get("/projects")
def projects(user=Depends(current_user), conn=Depends(get_conn)):
    rows = conn.execute(JOB_SQL + " WHERE j.horizon = 'long' AND j.org_id = %s ORDER BY lower(j.work_window)", (user["company"],)).fetchall()
    return features(rows)


@router.get("/overlaps")
def overlaps(user=Depends(current_user), conn=Depends(get_conn)):
    opps = conn.execute(mine_sql(user["company"]) + " ORDER BY op.score DESC, op.distance_m").fetchall()
    ids = list({o["job_a"] for o in opps} | {o["job_b"] for o in opps})
    jobs = conn.execute(JOB_SQL + " WHERE j.id = ANY(%s)", (ids,)).fetchall() if ids else []
    return {"overlaps": opps, "jobs": features(jobs)}  # jobs: both sides of every overlap, for the map


class Chat(BaseModel):
    messages: list[dict[str, str]]


@router.post("/chat")
def chat(body: Chat, user=Depends(current_user), conn=Depends(get_conn)):
    return agent.run(conn, body.messages[-20:], app_system(user), app_tools(user))
