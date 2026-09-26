"""Cost: what the existing savings model and the weather-cost model already say about this pair, read as evidence."""
from app.config import MAX_DRIVE_MIN
from app.feasibility.common import factor, money, span

MEANINGFUL = 50_000  # savings above this are worth a request on their own


def assess(ctx):
    op, ours, theirs = ctx["op"], ctx["ours"], ctx["theirs"]
    lo, hi = float(op.get("savings_low") or 0), float(op.get("savings_high") or 0)
    sav = ctx.get("savings") or {}
    evidence, conditions = [], []
    sources = ["savings model (engine.cost) from published unit costs", "weather cost model (hazards.cost)"]
    if hi <= 0:
        evidence.append("no shared savings in the current windows")
        if float(op.get("time_overlap") or 0) == 0:
            conditions.append("savings only accrue on days both works are open: align the windows first")
        if op.get("drive_min") is not None and op["drive_min"] > MAX_DRIVE_MIN:
            conditions.append(f"beyond {MAX_DRIVE_MIN} min by road no crew or yard can serve both sites")
        return factor("cost", "Cost", 0.2, evidence, conditions, sources)
    evidence.append(f"coordinating saves {span(lo, hi)}")
    cats = sav.get("categories") or []
    if cats:
        evidence.append("mostly " + ", ".join(f"{c['label'].lower()} {span(c['low'], c['high'])}" for c in cats[:3]))
    budgets = [(j["name"], float(j["cost_usd"])) for j in (ours, theirs) if j.get("cost_usd")]
    share = (sav.get("share_of_budget") or {}).get("high")
    if budgets:
        small = min(budgets, key=lambda b: b[1])
        evidence.append("project budgets: " + " and ".join(f"{money(c)} ({n})" for n, c in budgets))
        if share is not None:
            evidence.append(f"the high estimate is {share:.1%} of the smaller project ({small[0]})")
    coord = ctx.get("coordination") or {}
    if coord.get("best_months"):
        months = ", ".join(m["label"] for m in coord["best_months"])
        wx = coord.get("savings") or {}
        evidence.append(f"cheapest months to work the pair: {months}")
        if wx.get("high"):
            evidence.append(f"shared standby in a typical month saves {span(wx.get('low', 0), wx['high'])} more")
    score = 0.85 if hi >= MEANINGFUL or (share or 0) >= 0.01 else 0.6
    if float(op.get("time_overlap") or 0) == 0:
        conditions.append("the recurring savings need shared months; only one-off items apply as the windows stand")
        score -= 0.1
    return factor("cost", "Cost", score, evidence, conditions, sources)
