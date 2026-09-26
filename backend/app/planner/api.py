"""Plan endpoints: latest plan, rebuild, edit items, execute accepted items, explain one item."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import current_user
from app.db import get_conn
from app.planner import build, execute, store

router = APIRouter(prefix="/api/app/plan")


def as_json(row):
    return {"id": row["id"], "company_id": row["company_id"], "horizon": row["horizon"], "version": row["version"], "items": row["items"],
            "totals": row["totals"], "status": row["status"], "created_at": row["created_at"], "updated_at": row["updated_at"],
            "changed": row.get("changed")}


def rebuild(conn, company, horizon):
    plan = build.build(conn, company, horizon)
    return store.save(conn, company, plan["horizon"], plan["items"], plan["totals"])


@router.get("")
def latest(horizon: str = "quarter", user=Depends(current_user), conn=Depends(get_conn)):
    horizon = horizon if horizon in build.HORIZONS else "quarter"
    row = store.latest(conn, user["company"], horizon) or rebuild(conn, user["company"], horizon)  # first look builds one
    return as_json(row)


@router.post("/build")
def build_plan(horizon: str = "quarter", user=Depends(current_user), conn=Depends(get_conn)):
    return as_json(rebuild(conn, user["company"], horizon if horizon in build.HORIZONS else "quarter"))


class ItemPatch(BaseModel):
    state: str | None = None
    target_start: str | None = None
    target_end: str | None = None
    note: str | None = None


def owned(conn, plan_id, user):
    plan = store.get(conn, plan_id, user["company"])
    if not plan:
        raise HTTPException(404, "plan not found")
    return plan


@router.get("/{plan_id}")
def one(plan_id: int, user=Depends(current_user), conn=Depends(get_conn)):
    return as_json(owned(conn, plan_id, user))  # a plan card in the chat re-fetches by id


@router.patch("/{plan_id}/items/{item_id}")
def patch_item(plan_id: int, item_id: str, body: ItemPatch, user=Depends(current_user), conn=Depends(get_conn)):
    plan = owned(conn, plan_id, user)
    row = store.update_item(conn, plan, item_id, body.model_dump(exclude_none=True))
    if not row:
        raise HTTPException(404, "item not found")
    row["totals"] = build.totals_for(row["items"], row["totals"].get("considered", 0), row["totals"].get("skipped", {}),
                                     tuple(row["totals"]["period"]) if row["totals"].get("period") else None, row["totals"].get("note", ""))
    return as_json(row)


@router.post("/{plan_id}/execute")
def execute_plan(plan_id: int, user=Depends(current_user), conn=Depends(get_conn)):
    plan = owned(conn, plan_id, user)
    result, updated = execute.execute(user, conn, plan)
    if "error" in result:
        raise HTTPException(409, result["error"])
    return {**result, "plan": as_json(updated)}


@router.get("/{plan_id}/explain/{item_id}")
def explain(plan_id: int, item_id: str, user=Depends(current_user), conn=Depends(get_conn)):
    plan = owned(conn, plan_id, user)
    it = next((i for i in plan["items"] if i["id"] == item_id), None)
    if not it:
        raise HTTPException(404, "item not found")
    return build.explain_item(it)
