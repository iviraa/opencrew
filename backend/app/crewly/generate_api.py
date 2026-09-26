"""Chart, table and report endpoints behind the chat cards: re-request with new options, or open a stored report."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.auth import current_user
from app.crewly import charts, reports
from app.db import get_conn

router = APIRouter(prefix="/api/app")


class ChartReq(BaseModel):
    dataset: str
    options: dict = {}


class DataReq(BaseModel):
    dataset: str
    filters: dict = {}


class ReportReq(BaseModel):
    kind: str
    id: str | None = None
    sections: list[str] | None = None


@router.post("/chart")
def chart(body: ChartReq, user=Depends(current_user), conn=Depends(get_conn)):
    try:
        spec, rows = charts.make(conn, user["company"], body.dataset, body.options)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"chart": spec, "csv": charts.to_csv(rows)}


@router.post("/data")
def data(body: DataReq, user=Depends(current_user), conn=Depends(get_conn)):
    try:
        t = charts.table(conn, user["company"], body.dataset, body.filters, user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {**t, "csv": charts.to_csv(t["rows"])}


@router.post("/report")
def make_report(body: ReportReq, user=Depends(current_user), conn=Depends(get_conn)):
    try:
        r = reports.build(conn, user["company"], body.kind, body.id, body.sections)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {k: r[k] for k in ("id", "kind", "ref_id", "title", "sections", "all_sections", "created_at")}


@router.get("/report/{report_id}", response_class=HTMLResponse)
def open_report(report_id: int, user=Depends(current_user), conn=Depends(get_conn)):
    row = reports.get(conn, report_id, user["company"])
    if not row:
        raise HTTPException(404, "report not found")
    return HTMLResponse(row["html"])
