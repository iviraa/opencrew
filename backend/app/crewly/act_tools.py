"""Crewly tools that prepare actions: they only return a confirm button; the user's click does the write with their own login."""
import os

import httpx

from app.config import MILE_M
from app.queries import shareable

NAMES = {"desc": "Dominion Energy SC", "gpc": "Georgia Power"}
SHORT = {"desc": "Dominion", "gpc": "Georgia Power"}
OPEN = ("pending", "approved")  # a request in these states means the overlap is already handled
MAX_GOAL = 10


def rest(ctx, method, table, **kw):
    """Supabase REST as the logged-in user, so row security decides what we can read and write."""
    headers = {"apikey": os.environ["SUPABASE_PUBLISHABLE_KEY"], "Authorization": f"Bearer {ctx['token']}", **kw.pop("headers", {})}
    r = httpx.request(method, f"{os.environ['SUPABASE_URL'].rstrip('/')}/rest/v1/{table}", headers=headers, timeout=10, **kw)
    r.raise_for_status()
    return r.json() if r.content else None


def _mine(conn, ctx, opportunity_id):
    from app.crewly.app_tools import mine_sql  # app_tools imports this module
    return conn.execute(mine_sql(ctx["company"]) + " AND op.id = %s", (int(opportunity_id),)).fetchone()


def _sides(ctx, o):
    a = o["a_org"] == ctx["company"]
    return (o["a_name"], o["b_name"]) if a else (o["b_name"], o["a_name"])


def _open_requests(ctx, ids=None):
    q = {"select": "id,opportunity_id,status,from_company", "status": f"in.({','.join(OPEN)})"}
    if ids is not None:
        q["opportunity_id"] = f"in.({','.join(str(int(i)) for i in ids)})"
    return rest(ctx, "GET", "collab_request", params=q)


def draft_note(ctx, o):
    """Template note: every number comes straight from the overlap row."""
    ours, theirs = _sides(ctx, o)
    where = f"{o['distance_m'] / MILE_M:.1f} miles apart"
    if o["drive_min"] is not None:
        where += f" ({round(o['drive_min'])} min drive)"
    when = "build at the same time" if o["time_overlap"] > 0 else "build close together"
    share = [s for s in shareable(o["tier"], o["a_phase"], o["b_phase"], o["drive_min"])][:3]
    ask = f"Could we plan {', '.join(share[:-1]) + ' and ' + share[-1] if len(share) > 1 else share[0]} together?" if share else "Could we plan this work together?"
    return f"Hi from {NAMES[ctx['company']]}! Our {ours} and your {theirs} are {where} and {when}. {ask}"


def propose_request(ctx, conn, opportunity_id, note=None):
    o = _mine(conn, ctx, opportunity_id)
    if not o:
        return {"error": f"#{opportunity_id} is not one of our overlaps"}, []
    taken = _open_requests(ctx, [o["id"]])
    if taken:
        t = taken[0]
        who = "we" if t["from_company"] == ctx["company"] else NAMES[ctx["other"]]
        return {"blocked": True, "reason": f"{who} already have a {t['status']} request for #{o['id']}", "request_id": t["id"]}, []
    ours, theirs = _sides(ctx, o)
    note = (note or "").strip() or draft_note(ctx, o)
    return ({"ready_to_confirm": True, "overlap_id": o["id"], "ours": ours, "theirs": theirs, "to": NAMES[ctx["other"]], "note": note,
             "sent": False, "next_step": "the user must tap Confirm in the chat to send it"},
            [{"type": "confirm", "action": "send_request", "opportunity_id": o["id"], "note": note,
              "label": f"Send {SHORT[ctx['other']]} a request for #{o['id']}", "title": f"{ours} × {theirs}"}])


def propose_answer(ctx, conn, request_id, decision, feedback=None):
    if decision not in ("approved", "declined"):
        return {"error": "decision must be approved or declined"}, []
    rows = rest(ctx, "GET", "collab_request", params={"select": "id,opportunity_id,from_company,to_company,status,summary,note", "id": f"eq.{int(request_id)}"})
    r = rows[0] if rows else None
    if not r or r["to_company"] != ctx["company"]:
        return {"error": f"request {request_id} was not sent to us"}, []
    if r["status"] != "pending":
        return {"blocked": True, "reason": f"request {request_id} is already {r['status']}"}, []
    verb = "Approve" if decision == "approved" else "Decline"
    return ({"ready_to_confirm": True, "request_id": r["id"], "overlap_id": r["opportunity_id"], "decision": decision,
             "their_note": r["note"], "feedback": (feedback or "").strip(), "sent": False, "next_step": "the user must tap Confirm in the chat"},
            [{"type": "confirm", "action": "respond", "request_id": r["id"], "opportunity_id": r["opportunity_id"], "decision": decision,
              "feedback": (feedback or "").strip(), "label": f"{verb} {SHORT[r['from_company']]}'s request for #{r['opportunity_id']}",
              "title": r["summary"].get("title")}])


def start_goal(ctx, conn, goal, count=5, start_date=None, end_date=None, tier=None):
    from app.crewly.app_tools import _day, mine_sql
    s, e = _day(start_date), _day(end_date)
    sql = mine_sql(ctx["company"]) + " AND op.savings_high > 0 AND (%(t)s::text IS NULL OR op.tier = %(t)s)"
    if s or e:
        sql += """ AND ja.work_window && tstzrange(%(s)s::timestamptz, %(e)s::timestamptz)
                   AND jb.work_window && tstzrange(%(s)s::timestamptz, %(e)s::timestamptz)"""
    rows = conn.execute(sql + " ORDER BY op.score DESC, op.distance_m", {"t": tier, "s": s, "e": e}).fetchall()
    taken = {r["opportunity_id"] for r in _open_requests(ctx)}
    pick = [o for o in rows if o["id"] not in taken][:max(1, min(int(count or 5), MAX_GOAL))]
    if not pick:
        return {"drafted": 0, "reason": "no overlaps with savings are left without a pending or approved request"}, []
    steps = [{"opportunity_id": o["id"], "title": " × ".join(_sides(ctx, o)), "note": draft_note(ctx, o), "request_id": None, "skipped": False}
             for o in pick]
    task = rest(ctx, "POST", "agent_task", json={"goal": goal.strip()[:500] or "Line up collaboration", "steps": steps},
                headers={"Prefer": "return=representation"})[0]
    return ({"task_id": task["id"], "goal": task["goal"], "drafted": len(steps), "skipped_already_handled": len(taken & {o["id"] for o in rows}),
             "overlaps": [{"id": st["opportunity_id"], "projects": st["title"]} for st in steps], "sent": False,
             "next_step": "the user reviews the drafts in the goal panel and sends them"},
            [{"type": "goal", "id": task["id"]}, {"type": "show_overlaps", "ids": [st["opportunity_id"] for st in steps]}])


def step_state(step, by_id):
    if step.get("skipped"):
        return "skipped"
    r = by_id.get(step.get("request_id"))
    return r["status"] if r else ("sent" if step.get("request_id") else "draft")


def goal_status(ctx, conn, task_id=None):
    q = {"select": "*", "order": "created_at.desc", "limit": "1"}
    if task_id:
        q["id"] = f"eq.{int(task_id)}"
    tasks = rest(ctx, "GET", "agent_task", params=q)
    if not tasks:
        return {"error": "no goals yet"}, []
    t = tasks[0]
    ids = [st["request_id"] for st in t["steps"] if st.get("request_id")]
    reqs = rest(ctx, "GET", "collab_request", params={"select": "id,status,feedback", "id": f"in.({','.join(map(str, ids))})"}) if ids else []
    by_id = {r["id"]: r for r in reqs}
    steps = [{"overlap_id": st["opportunity_id"], "projects": st["title"], "state": step_state(st, by_id),
              "feedback": (by_id.get(st.get("request_id")) or {}).get("feedback")} for st in t["steps"]]
    counts = {k: sum(1 for x in steps if x["state"] == k) for k in ("draft", "pending", "approved", "declined", "skipped")}
    return ({"task_id": t["id"], "goal": t["goal"], "status": t["status"], "counts": counts, "steps": steps},
            [{"type": "goal", "id": t["id"]}])


def _bind(ctx, fn):
    return lambda conn, **kw: fn(ctx, conn, **kw)


def act_tools(ctx):
    other = NAMES[ctx["other"]]
    return {
        "propose_request": (_bind(ctx, propose_request), f"Prepare a collaboration request to {other} about one of our overlaps. It does NOT "
                            "send anything: it shows the user a Confirm button with the note. If note is empty a friendly note is drafted.", {
            "opportunity_id": {"type": "integer"}, "note": {"type": "string", "description": "short friendly note, optional"}}, ["opportunity_id"]),
        "propose_answer": (_bind(ctx, propose_answer), f"Prepare an approve or decline answer to a pending request {other} sent us. It does "
                           "NOT answer: it shows the user a Confirm button.", {
            "request_id": {"type": "integer"}, "decision": {"type": "string", "enum": ["approved", "declined"]},
            "feedback": {"type": "string", "description": "optional feedback for them"}}, ["request_id", "decision"]),
        "start_goal": (_bind(ctx, start_goal), "Start a multi-step goal like 'line up collaboration on our top 5 overlaps': ranks our best "
                       "overlaps that have no pending or approved request, drafts a request note for each and saves them as a goal the user "
                       "reviews and sends from the goal panel. Nothing is sent.", {
            "goal": {"type": "string", "description": "the goal in the user's words"}, "count": {"type": "integer", "description": "how many overlaps, default 5"},
            "start_date": {"type": "string", "description": "YYYY-MM-DD"}, "end_date": {"type": "string", "description": "YYYY-MM-DD"},
            "tier": {"type": "string", "enum": ["crossing", "land", "site", "crew"]}}, ["goal"]),
        "goal_status": (_bind(ctx, goal_status), "Progress on a goal (latest one if no id): which drafts are still unsent, sent, approved, "
                        "declined or skipped, with their feedback.", {"task_id": {"type": "integer"}}, []),
    }
