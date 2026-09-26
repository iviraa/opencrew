"""Accepted plan items become one goal: drafted requests the user sends from the goal panel with their own login."""
from datetime import date

from app.crewly.act_tools import _mine, draft_note, rest
from app.planner import store


def month_text(s):
    d = date.fromisoformat(s[:10])
    return f"{d:%b %Y}"


def execute(ctx, conn, plan):
    todo = [i for i in plan["items"] if i.get("state") == "accepted" and not i.get("request_id") and not i.get("goal_id")]
    if not todo:
        return {"error": "no accepted items without a request yet"}, None
    steps = []
    for it in todo:
        o = _mine(conn, ctx, it["opportunity_id"])
        if not o:
            continue
        note = draft_note(ctx, o) + f" We'd aim for {month_text(it['target_start'])} to {month_text(it['target_end'])}."
        if it.get("note"):
            note += f" {it['note'].strip()}"
        steps.append({"opportunity_id": o["id"], "title": f"{it['ours']} × {it['theirs']}", "partner": it["partner"], "note": note[:2000],
                      "request_id": None, "skipped": False, "plan_item": it["id"]})
    if not steps:
        return {"error": "none of the accepted items are our overlaps"}, None
    goal = f"Coordination plan ({plan['horizon']}), version {plan['version']}"
    task = rest(ctx, "POST", "agent_task", json={"goal": goal, "steps": steps}, headers={"Prefer": "return=representation"})[0]
    updated = store.set_goal(conn, plan, [s["plan_item"] for s in steps], task["id"])
    return {"task_id": task["id"], "goal": goal, "drafted": len(steps), "items": [s["plan_item"] for s in steps]}, updated
