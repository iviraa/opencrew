"""Timing: do the build windows and phases line up, how firm are the dates, and what a shift of a few months would do."""
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from app.config import PHASES
from app.engine.cost import CHAIN_DAYS
from app.engine.scoring import time_overlap
from app.feasibility.common import day, factor, months_between, today_or, ym

SHIFTS = (-6, -3, -1, 1, 3, 6)  # months our window could move
FIRM = ("construction", "approved", "ntc", "underway", "engineering")  # status words that mean the dates are committed
SOFT = ("conceptual", "proposed", "future", "concept", "study")


def phase_at(start, end, when):
    """Which phase a project is in on a date, from the fixed phase shares over its window."""
    start, end, when = day(start), day(end), day(when)
    total = max((end - start).days, 1)
    at = (when - start).days / total
    acc = 0.0
    for name, share in PHASES:
        acc += share
        if at < acc:
            return name
    return PHASES[-1][0]


def firmness(status):
    s = (status or "").lower()
    if any(w in s for w in FIRM):
        return "firm"
    if any(w in s for w in SOFT):
        return "soft"
    return "unknown"


def slips(history, current_end):
    """How many recorded plan versions ended earlier than the current one: each is a slip."""
    end = day(current_end)
    return sum(1 for v in history or [] if v.get("end") and day(v["end"]) < end)


def shift_options(ours, theirs, month_cost=None):
    """Overlap share and weather cost if our window moved by a few months; month_cost is the pair's cost per 30 days by month, when known."""
    out = []
    a0, a1, b0, b1 = ours["start"], ours["end"], theirs["start"], theirs["end"]
    base = time_overlap(a0, a1, b0, b1)
    base_wx = _shared_cost(a0, a1, b0, b1, month_cost)
    for m in SHIFTS:
        s0, s1 = a0 + relativedelta(months=m), a1 + relativedelta(months=m)
        ov = time_overlap(s0, s1, b0, b1)
        wx = _shared_cost(s0, s1, b0, b1, month_cost)
        out.append({"months": m, "overlap": round(ov, 2), "overlap_delta": round(ov - base, 2),
                    "weather_cost_delta": None if wx is None or base_wx is None else {end: round(wx[end] - base_wx[end], -2) for end in ("low", "high")}})
    return out


def _shared_cost(a0, a1, b0, b1, month_cost):
    """Weather cost over the months both windows are open, from the pair's per-month cost; None without that data."""
    if not month_cost:
        return None
    s, e = day(max(a0, b0)), day(min(a1, b1))
    if e <= s:
        return {"low": 0.0, "high": 0.0}
    total, d = {"low": 0.0, "high": 0.0}, s.replace(day=1)
    while d <= e:
        c = month_cost.get(d.month)
        if c:
            for end in ("low", "high"):
                total[end] += c[end]
        d += relativedelta(months=1)
    return total


def assess(ctx):
    op, ours, theirs = ctx["op"], ctx["ours"], ctx["theirs"]
    today = today_or(ctx)
    ov = float(op.get("time_overlap") or 0)
    gap = op.get("time_gap_days")
    evidence = [f"build windows: ours {ym(ours['start'])} to {ym(ours['end'])}, theirs {ym(theirs['start'])} to {ym(theirs['end'])}"]
    conditions, sources = [], ["planner build windows and in-service dates", "plan history (job_version)"]
    if ov >= 0.5:
        score = 0.9
        evidence.append(f"{ov:.0%} of the shorter window is shared")
    elif ov > 0:
        score = 0.6
        evidence.append(f"only {ov:.0%} of the shorter window is shared")
        conditions.append("more shared months would let crews and yards serve both works")
    elif gap is not None and gap <= CHAIN_DAYS:
        score = 0.45
        evidence.append(f"the windows do not overlap; {gap} days apart, so one crew could move from one job to the next")
        conditions.append("hand the crew and yard over back to back instead of sharing them")
    else:
        score = 0.2
        evidence.append("the windows do not overlap" + (f" ({gap} days apart)" if gap is not None else ""))
        conditions.append("only land, permits or shared structures can be coordinated unless a schedule moves")
    shared_start, shared_end = max(ours["start"], theirs["start"]), min(ours["end"], theirs["end"])
    if shared_end > shared_start:
        mid = shared_start + (shared_end - shared_start) / 2
        pa, pb = phase_at(ours["start"], ours["end"], mid), phase_at(theirs["start"], theirs["end"], mid)
        if pa == pb:
            evidence.append(f"both in {pa} around {ym(mid)}")
        else:
            evidence.append(f"around {ym(mid)} ours is in {pa} while theirs is in {pb}")
            score -= 0.1
    for who, j in (("ours", ours), ("theirs", theirs)):
        f = firmness(j.get("status"))
        if f == "soft":
            score -= 0.15
            evidence.append(f"{who} is still {j['status'].lower()}: dates may move")
            conditions.append(f"wait for {j['name']} to be approved before booking shared resources")
        elif f == "firm":
            evidence.append(f"{who} is {j['status'].lower()}")
        n = slips(j.get("history"), j["end"])
        if n:
            score -= 0.1
            evidence.append(f"{who} has slipped {n} time{'s' if n != 1 else ''} in earlier plans")
    left = months_between(today, ours["end"])
    if left < 0:
        evidence.append(f"our window ended {ym(ours['end'])}")
        score = min(score, 0.3)
    elif left < 6:
        evidence.append(f"our in-service date is {left:.0f} months away: little room to re-plan")
        score -= 0.1
    options = shift_options(ours, theirs, ctx.get("month_cost"))
    best = max(options, key=lambda o: o["overlap"])
    if best["overlap"] > ov + 0.15:
        conditions.append(f"moving our window {best['months']:+d} months would share {best['overlap']:.0%} of the shorter window")
    plan = ctx.get("plan") or {}
    if plan.get("covers_pair"):
        evidence.append("the joint schedule solver has a plan covering both projects")
        sources.append("CP-SAT joint plan")
    return factor("timing", "Timing", score, evidence, conditions, sources, options=options, phases=list(dict(PHASES)))
