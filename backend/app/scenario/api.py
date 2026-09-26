"""What-if endpoints behind the finding cards: run, re-run with new knobs, keep, compare."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import current_user
from app.db import get_conn
from app.scenario import calc, experiments

router = APIRouter(prefix="/api/app")


class ExperimentReq(BaseModel):
    kind: str
    params: dict = {}
    question: str | None = None


class CompareReq(BaseModel):
    a: int
    b: int


class CalcReq(BaseModel):
    expression: str
    values: dict = {}


@router.post("/experiment")
def experiment(body: ExperimentReq, user=Depends(current_user), conn=Depends(get_conn)):
    try:
        return experiments.run(conn, user["company"], body.kind, body.params, body.question)
    except ValueError as e:
        conn.rollback()
        raise HTTPException(400, str(e))


@router.post("/calculate")
def calculate(body: CalcReq, user=Depends(current_user)):
    try:
        return calc.calculate(body.expression, body.values)
    except calc.Unsafe as e:
        raise HTTPException(400, str(e))


@router.get("/findings")
def findings(starred: int = 0, user=Depends(current_user), conn=Depends(get_conn)):
    return experiments.listing(conn, user["company"], bool(starred))


@router.get("/finding/{finding_id}")
def finding(finding_id: int, user=Depends(current_user), conn=Depends(get_conn)):
    f = experiments.get(conn, finding_id, user["company"])
    if not f:
        raise HTTPException(404, "finding not found")
    return f


@router.post("/finding/{finding_id}/star")
def star(finding_id: int, on: int = 1, user=Depends(current_user), conn=Depends(get_conn)):
    f = experiments.star(conn, finding_id, user["company"], bool(on))
    if not f:
        raise HTTPException(404, "finding not found")
    return f


@router.delete("/finding/{finding_id}")
def delete(finding_id: int, user=Depends(current_user), conn=Depends(get_conn)):
    if not experiments.delete(conn, finding_id, user["company"]):
        raise HTTPException(404, "finding not found")
    return {"deleted": finding_id}


@router.post("/compare")
def compare(body: CompareReq, user=Depends(current_user), conn=Depends(get_conn)):
    try:
        return experiments.compare(conn, user["company"], body.a, body.b)
    except ValueError as e:
        raise HTTPException(400, str(e))
