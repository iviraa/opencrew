"""Feasibility endpoints: one overlap on demand, or the company's top overlaps in one go."""
from fastapi import APIRouter, Depends, HTTPException

from app.auth import current_user
from app.crewly.app_tools import mine_sql
from app.db import get_conn
from app.feasibility import assess as assess_mod

router = APIRouter(prefix="/api/app/feasibility")


@router.get("/{opportunity_id}")
def feasibility(opportunity_id: int, refresh: bool = False, user=Depends(current_user), conn=Depends(get_conn)):
    out = assess_mod.assess(conn, opportunity_id, user["company"], refresh=refresh)
    if not out:
        raise HTTPException(404, f"overlap {opportunity_id} is not one of your overlaps")
    return out


@router.post("/assess_top")
def assess_top(n: int = 5, refresh: bool = False, user=Depends(current_user), conn=Depends(get_conn)):
    rows = conn.execute(mine_sql(user["company"]) + " ORDER BY op.score DESC, op.distance_m LIMIT %s", (max(1, min(int(n), 20)),)).fetchall()
    out = []
    for op in rows:
        try:
            a = assess_mod.assess(conn, op["id"], user["company"], refresh=refresh)
            if a:
                out.append({k: a[k] for k in ("opportunity_id", "verdict", "score", "narrative", "created_at")})
        except Exception as e:  # one bad pair must not hide the rest
            conn.rollback()
            out.append({"opportunity_id": op["id"], "error": str(e)[:160]})
    return {"count": len(out), "assessments": out}
