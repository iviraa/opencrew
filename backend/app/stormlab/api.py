"""Experiment endpoints: a storm, a ten-year replay, a sensitivity run. Each answers with a finding."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import current_user
from app.db import get_conn
from app.stormlab import EXPERIMENTS

router = APIRouter(prefix="/api/app/experiment")


class Storm(BaseModel):
    place: str | None = None
    lon: float | None = None
    lat: float | None = None
    state: str | None = None
    date: str | None = None
    category: int | str | None = None
    max_wind_mph: float | None = None
    historical: str | None = None
    heading_deg: float = 20.0
    speed_mph: float = 15


class Replay(BaseModel):
    opportunity_ids: list[int] = []
    job_ids: list[str] = []
    plan_id: int | None = None
    years: list[int] | None = None
    hazards: list[str] | None = None


class Sensitivity(BaseModel):
    opportunity_id: int
    metric: str = "savings"
    knobs: list[str] | None = None
    month: int | None = None


def run(kind, params, user, conn):
    try:
        return EXPERIMENTS[kind](conn, user["company"], params)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/storm")
def storm(body: Storm, user=Depends(current_user), conn=Depends(get_conn)):
    return run("storm", body.model_dump(), user, conn)


@router.post("/replay")
def replay(body: Replay, user=Depends(current_user), conn=Depends(get_conn)):
    return run("replay", body.model_dump(), user, conn)


@router.post("/sensitivity")
def sensitivity(body: Sensitivity, user=Depends(current_user), conn=Depends(get_conn)):
    return run("sensitivity", body.model_dump(), user, conn)
