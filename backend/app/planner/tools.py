"""Crewly's plan tools: build, report and explain; the person accepts or skips items on the plan card in the chat."""
from app.planner import build, store


def _usd(n):
    n = float(n or 0)
    return f"${n / 1e6:.1f}M" if n >= 1e6 else f"${round(n / 1e3)}k" if n >= 1e3 else f"${round(n)}"


def summary(row):
    t, items = row["totals"], row["items"]
    return {"plan_id": row["id"], "horizon": row["horizon"], "version": row["version"], "period": t.get("period"), "pairs": len(items),
            "expected_savings_usd": f"{_usd(t['savings']['low'])} to {_usd(t['savings']['high'])}",
            "weather_cost_avoided_usd": f"{_usd(t['weather_avoided']['low'])} to {_usd(t['weather_avoided']['high'])}",
            "by_verdict": t.get("verdicts"), "actions": t.get("actions"), "conflicts": t.get("conflicts"), "note": t.get("note") or None,
            "items": [{"item_id": i["id"], "overlap_id": i["opportunity_id"], "ours": i["ours"], "with": f"{i['theirs']} ({i['partner_name']})",
                       "verdict": i["verdict"], "months": f"{i['target_start'][:7]} to {i['target_end'][:7]}", "savings_usd": f"{_usd(i['savings']['low'])} to {_usd(i['savings']['high'])}",
                       "action": i["action"], "state": i["state"], "risks": i["risks"][:2]} for i in items],
            "weather_cost_usd": f"{_usd(t['weather_cost']['low'])} to {_usd(t['weather_cost']['high'])}" if t.get("weather_cost") else None,
            "changes_since_built": _changes(row),
            "next_step": "the user accepts or skips items on the plan card in the chat, then executes the accepted ones as requests"}


def _changes(row):
    """Before the edits against now, so questions about what the edits did are answered from the plan, not from memory."""
    from app.planner import edits
    d = edits.describe(row)
    if not d or not d["edits"]:
        return None
    fmt = lambda r: f"{_usd(r['low'])} to {_usd(r['high'])}"  # noqa: E731
    return {"edits": [e["summary"] for e in d["log"]], "savings_usd": {"before": fmt(d["savings"]["built"]), "now": fmt(d["savings"]["now"])},
            "weather_cost_usd": {"before": fmt(d["weather_cost"]["built"]), "now": fmt(d["weather_cost"]["now"])}}


def build_plan(ctx, conn, horizon="quarter"):
    plan = build.build(conn, ctx["company"], horizon)
    row = store.save(conn, ctx["company"], plan["horizon"], plan["items"], plan["totals"])
    return summary(row), [{"type": "plan", "horizon": plan["horizon"], "id": row["id"]}]


def plan_status(ctx, conn, horizon="quarter"):
    row = store.latest(conn, ctx["company"], horizon if horizon in build.HORIZONS else "quarter")
    if not row:
        return {"error": "no plan yet; call build_plan"}, []
    return summary(row), [{"type": "plan", "horizon": row["horizon"], "id": row["id"]}]


def explain_plan_item(ctx, conn, item_id, horizon="quarter"):
    row = store.latest(conn, ctx["company"], horizon if horizon in build.HORIZONS else "quarter")
    it = next((i for i in (row["items"] if row else []) if i["id"] == str(item_id).lstrip("#")), None)
    if not it:
        return {"error": f"no plan item {item_id}; item ids are the overlap ids"}, []
    return build.explain_item(it), [{"type": "plan", "horizon": row["horizon"], "id": row["id"], "item": it["id"]}]


def edit_plan(ctx, conn, changes, horizon=None):
    """Move, skip, accept or undo pairs in the plan the person last saw (or a horizon's), then report what the edits did to the cost."""
    from app.planner import edits
    row = store.latest(conn, ctx["company"], horizon) if horizon in build.HORIZONS else store.newest(conn, ctx["company"])
    if not row:
        return {"error": "no plan yet; build one first"}, []
    if not changes:
        return {"error": "say what to change: move (with start/end months or shift_months), skip, accept or undo"}, []
    try:
        row, done = edits.apply(conn, row, changes if isinstance(changes, list) else [changes])
    except ValueError as e:
        return {"error": str(e), "plan_items": [i["id"] for i in row["items"]]}, []
    d = edits.describe(row)
    fmt = lambda r: f"{_usd(r['low'])} to {_usd(r['high'])}"  # noqa: E731
    out = {"plan_id": row["id"], "horizon": row["horizon"], "changes": [c["summary"] for c in done],
           "now": {"savings_usd": fmt(row["totals"]["savings"]), "weather_cost_usd": fmt(d["weather_cost"]["now"]) if d else None},
           "before_your_edits": {"savings_usd": fmt(d["savings"]["built"]), "weather_cost_usd": fmt(d["weather_cost"]["built"])} if d else None,
           "edits_so_far": d["edits"] if d else 0,
           "next_step": "the plan card shows the changes; make_report kind plan writes the cost report with a changes section; 'undo' reverts the last edit"}
    return out, [{"type": "plan", "horizon": row["horizon"], "id": row["id"]}]


def _bind(ctx, fn):
    return lambda conn, **kw: fn(ctx, conn, **kw)


def planner_tools(ctx):
    h = {"type": "string", "enum": list(build.HORIZONS), "description": "quarter (next 3 months), year, or window (whole build windows)"}
    return {
        "build_plan": (_bind(ctx, build_plan), "Build or rebuild our coordination plan for a horizon: which overlaps to pursue, the cheapest "
                       "months to work each pair by weather history, expected savings, risks and conflicts. Shows the plan card in the chat. Nothing is sent.",
                       {"horizon": h}, []),
        "plan_status": (_bind(ctx, plan_status), "The current plan for a horizon: pairs, months, savings, which items the user accepted or skipped.",
                        {"horizon": h}, []),
        "edit_plan": (_bind(ctx, edit_plan), "Change the saved plan and re-cost it: move a pair's months (start and end as YYYY-MM, or shift_months "
                      "like 3 or -2), skip, accept or reopen pairs (by item_id = overlap id, item_ids, or partner = a utility's name), or undo the last edit. "
                      "Each move is re-priced from ten years of weather history; totals update and every edit is logged with its effect on savings and "
                      "weather cost. Changes apply in order. Nothing is sent to anyone.", {
            "changes": {"type": "array", "items": {"type": "object", "properties": {
                "action": {"type": "string", "enum": ["move", "skip", "accept", "propose", "undo"]}, "item_id": {"type": "string"},
                "item_ids": {"type": "array", "items": {"type": "string"}}, "partner": {"type": "string"},
                "start": {"type": "string", "description": "YYYY-MM"}, "end": {"type": "string", "description": "YYYY-MM"},
                "shift_months": {"type": "integer"}}, "required": ["action"]}},
            "horizon": h}, ["changes"]),
        "explain_plan_item": (_bind(ctx, explain_plan_item), "Why a plan item was chosen and why those months: feasibility, savings, weather "
                              "cost vs the naive window, risks, news.", {"item_id": {"type": "string", "description": "the overlap id"}, "horizon": h},
                              ["item_id"]),
    }
