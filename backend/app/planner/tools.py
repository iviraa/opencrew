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
            "next_step": "the user accepts or skips items on the plan card in the chat, then executes the accepted ones as requests"}


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


def _bind(ctx, fn):
    return lambda conn, **kw: fn(ctx, conn, **kw)


def planner_tools(ctx):
    h = {"type": "string", "enum": list(build.HORIZONS), "description": "quarter (next 3 months), year, or window (whole build windows)"}
    return {
        "build_plan": (_bind(ctx, build_plan), "Build or rebuild our coordination plan for a horizon: which overlaps to pursue, the cheapest "
                       "months to work each pair by weather history, expected savings, risks and conflicts. Opens the Plan tab. Nothing is sent.",
                       {"horizon": h}, []),
        "plan_status": (_bind(ctx, plan_status), "The current plan for a horizon: pairs, months, savings, which items the user accepted or skipped.",
                        {"horizon": h}, []),
        "explain_plan_item": (_bind(ctx, explain_plan_item), "Why a plan item was chosen and why those months: feasibility, savings, weather "
                              "cost vs the naive window, risks, news.", {"item_id": {"type": "string", "description": "the overlap id"}, "horizon": h},
                              ["item_id"]),
    }
