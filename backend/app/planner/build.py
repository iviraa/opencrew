"""Build a plan from what the tools already know: overlaps, feasibility, hazard cost by month, news, open requests.

Nothing here computes cost: month costs come from app.hazards.cost, savings from the opportunity row. Crewly proposes; a person decides.
"""
import calendar
from datetime import date, datetime, timedelta

from dateutil.relativedelta import relativedelta

from app.companies import name, partner, short
from app.config import PHASES
from app.hazards import cost as hcost
from app.hazards.config import HAZARDS

HORIZONS = {"quarter": (3, 8), "year": (12, 20), "window": (None, None)}  # months ahead, most items
TARGET_MONTHS = 3  # how long one coordinated push lasts
CONSIDER = 40  # most promising overlaps priced per build
FOLLOW_UP_DAYS = 7
MIN_ITEMS = 3  # fewer than this and the period widens
UNCERTAIN = ("concept", "propos", "tbd", "study")  # planner statuses too early to ask a neighbor about
RISKY_NEWS = {"delay", "opposition", "regulatory", "supply_chain", "security", "damage", "outage"}
VERDICT_SCORE = {"strong": 0.85, "possible": 0.55, "unknown": 0.4, "unlikely": 0.15}
MONTHS = list(calendar.month_abbr)
ENDS = ("low", "high")

JOB_SQL = """SELECT id, org_id, name, status, need, cost_usd, in_service, window_basis, lower(work_window)::date AS start_at, upper(work_window)::date AS end_at
             FROM job WHERE id = %s"""


def _d(v):
    return v.date() if isinstance(v, datetime) else v


def first(d):
    return date(d.year, d.month, 1)


def last(d):
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def months_between(a, b):
    """First-of-month dates from a's month to b's month."""
    out, m = [], first(a)
    while m <= b:
        out.append(m)
        m += relativedelta(months=1)
    return out


def period_for(horizon, today):
    months = HORIZONS.get(horizon, HORIZONS["quarter"])[0]
    return (today, today + relativedelta(months=months)) if months else None


def requests_for(company):
    """Open requests either way, read with the backend key (a nightly build has no user token)."""
    from app.crewly.proactive import _rest
    try:
        return _rest("collab_request", params={"select": "id,opportunity_id,status,from_company,to_company,created_at",
                                               "or": f"(from_company.eq.{company},to_company.eq.{company})", "status": "in.(pending,approved)"})
    except Exception:  # no supabase reachable: plan without request states
        return []


def candidates(conn, company):
    from app.crewly.app_tools import mine_sql
    return conn.execute(mine_sql(company) + " AND op.savings_high > 0 ORDER BY op.score DESC, op.distance_m").fetchall()


def feasibility_for(conn, opp_id, company):
    """The feasibility fork's verdict when it exists, else None."""
    try:
        from app.feasibility.assess import assess
        f = assess(conn, opp_id, company, quick=True)  # quick: skips the hazard models, enough for ranking
        if not f:
            return None
        return {"verdict": f.get("verdict", "unknown"), "score": float(f.get("score", VERDICT_SCORE["unknown"])), "source": "assessment",
                "narrative": f.get("narrative")}
    except Exception:
        return None


def news_for(conn, opp_id):
    try:
        from app.news.feed import for_overlap
        items = for_overlap(conn, opp_id, days=90) or []
    except Exception:
        return []
    risky = [i for i in items if i.get("impact") in RISKY_NEWS]
    risky.sort(key=lambda i: -float(i.get("confidence") or 0))
    return [{"title": i.get("title"), "impact": i.get("impact"), "url": i.get("url"), "published": i.get("published"), "summary": i.get("summary")}
            for i in risky[:3]]


def uncertain(job):
    s = f"{job.get('status') or ''} {job.get('need') or ''}".lower()
    return any(w in s for w in UNCERTAIN) or job.get("in_service") is None


class Pricer:
    """Month-by-month weather cost for a pair, from the hazards cost module; sites are priced once per build."""

    def __init__(self, conn):
        self.conn, self.days = conn, {}
        self.mix = {p: s for p, s in PHASES}

    def site_days(self, job_id):
        if job_id not in self.days:
            self.days[job_id] = hcost.month_days(self.conn, job_id, list(HAZARDS))
        return self.days[job_id]

    def pair(self, op):
        da, db = self.site_days(op["job_a"]), self.site_days(op["job_b"])
        small = min(hcost.per_day(self.mix, end)["standby"] for end in ENDS)  # the crew released on shared days
        out = {}
        for m in range(1, 13):
            cost, days = {}, {}
            for end in ENDS:
                a = sum(hcost.hazard_item(h, {"low": float(d["low"]), "high": float(d["high"])}, self.mix)["total"][end] for h, d in da.get(m, {}).items())
                b = sum(hcost.hazard_item(h, {"low": float(d["low"]), "high": float(d["high"])}, self.mix)["total"][end] for h, d in db.get(m, {}).items())
                shared = hcost.shared_days({h: {end: d[end]} for h, d in da.get(m, {}).items()}, {h: {end: d[end]} for h, d in db.get(m, {}).items()},
                                           op["drive_min"], end)
                cost[end] = round(max(a + b - shared * small, 0), -2)
                days[end] = round(sum(d[end] for d in da.get(m, {}).values()) + sum(d[end] for d in db.get(m, {}).values()), 1)
            out[m] = {"cost": cost, "days": days}
        return out


def choose_window(months_cost, allowed):
    """The cheapest run of TARGET_MONTHS inside the allowed months, against the naive choice of the first months."""
    if not allowed:
        return None
    n = min(TARGET_MONTHS, len(allowed))
    runs = [allowed[i:i + n] for i in range(len(allowed) - n + 1)]
    total = lambda run: {end: sum(months_cost[m.month]["cost"][end] for m in run) for end in ENDS}  # noqa: E731
    best = min(runs, key=lambda r: (total(r)["high"], total(r)["low"], r[0]))
    naive = runs[0]
    tc, nc = total(best), total(naive)
    return {"target_start": best[0], "target_end": last(best[-1]), "naive_start": naive[0], "naive_end": last(naive[-1]),
            "target_cost": tc, "naive_cost": nc, "avoided": {end: max(nc[end] - tc[end], 0) for end in ENDS},
            "days": {end: round(sum(months_cost[m.month]["days"][end] for m in best), 1) for end in ENDS}}


def action_for(pending, ja, jb, today):
    if pending:
        age = (today - _d(datetime.fromisoformat(pending["created_at"].replace("Z", "+00:00")))).days
        return ("follow up", f"our request has waited {age} days") if age >= FOLLOW_UP_DAYS else ("wait", f"request sent {age} days ago")
    for j in (ja, jb):
        if uncertain(j):
            return "wait", f"{j['name']} is still {j.get('status') or 'undated'} in its planner's list"
    return "send request", "no request yet and both projects are firm"


def solver_evidence(conn, job_a, job_b):
    """Coordinated windows from a stored joint plan, only when one already covers both projects (never solved here)."""
    try:
        row = conn.execute("SELECT schedule FROM joint_plan WHERE status IN ('OPTIMAL', 'FEASIBLE') ORDER BY id DESC LIMIT 1").fetchone()
    except Exception:
        return None
    if not row or not row["schedule"]:
        return None
    rows = {r["job_id"]: r for r in row["schedule"] if r.get("job_id") in (job_a, job_b)}
    if len(rows) < 2:
        return None
    return {j: {"start": r["phases"][0]["start"] if r.get("phases") else None, "crew": r.get("crew"), "why": r.get("why")} for j, r in rows.items()}


def item_for(conn, pricer, op, company, reqs, period, today):
    ja, jb = conn.execute(JOB_SQL, (op["job_a"],)).fetchone(), conn.execute(JOB_SQL, (op["job_b"],)).fetchone()
    common = (max(ja["start_at"], jb["start_at"]), min(ja["end_at"], jb["end_at"]))
    if common[0] > common[1]:
        return None, "no common window"
    lo, hi = (max(common[0], period[0]), min(common[1], period[1])) if period else (max(common[0], today), common[1])
    passed = common[1] < today  # the filing's windows are behind us: flag it rather than plan the past
    if lo > hi and not (passed and period is None):
        return None, "outside the horizon"
    allowed = [m for m in months_between(lo, hi) if last(m) >= lo] if not passed else months_between(common[0], common[1])[-TARGET_MONTHS:]
    months = pricer.pair(op)
    win = choose_window(months, allowed)
    if not win:
        return None, "no months to plan"
    feas = feasibility_for(conn, op["id"], company)
    if not feas:
        verdict = "possible" if op["score"] >= 0.4 else "unknown"
        feas = {"verdict": verdict, "score": round(min(max(op["score"], 0.05), 1.0), 3), "source": "overlap score", "narrative": None}
    pending = next((r for r in reqs.get(op["id"], []) if r["status"] == "pending"), None)
    action, why = action_for(pending, ja, jb, today)
    if passed:
        action, why = "wait", f"both build windows ended by {common[1]:%b %Y} in the filings; confirm the dates before asking"
    ours, theirs = (ja, jb) if ja["org_id"] == company else (jb, ja)
    other = partner(op, company)
    news = news_for(conn, op["id"])
    risks = [f"{n['impact'].replace('_', ' ')}: {n['title']}" for n in news]
    if op["time_overlap"] < 0.3:
        risks.append(f"build windows only overlap {round(op['time_overlap'] * 100)}%")
    if op["drive_min"] is not None and op["drive_min"] > 45:
        risks.append(f"{round(op['drive_min'])} min drive, so crews and yards are hard to share")
    if win["days"]["high"] >= 3:
        risks.append(f"up to {win['days']['high']} weather-affected days in the target months")
    if passed:
        risks.insert(0, f"filed build windows ended {common[1]:%b %Y}; the planner lists may be stale")
    return {
        "id": str(op["id"]), "opportunity_id": op["id"], "partner": other, "partner_name": name(other), "partner_short": short(other),
        "ours": ours["name"], "theirs": theirs["name"], "our_job": ours["id"], "their_job": theirs["id"], "tier": op["tier"],
        "verdict": feas["verdict"], "feasibility": feas["score"], "feasibility_source": feas["source"], "narrative": feas.get("narrative"),
        "savings": {"low": float(op["savings_low"]), "high": float(op["savings_high"])},
        "project_cost": {"ours": float(ours["cost_usd"]) if ours["cost_usd"] else None, "theirs": float(theirs["cost_usd"]) if theirs["cost_usd"] else None},
        "window": {"ours": [str(ours["start_at"]), str(ours["end_at"])], "theirs": [str(theirs["start_at"]), str(theirs["end_at"])],
                   "common": [str(common[0]), str(common[1])], "overlap_pct": round(op["time_overlap"] * 100)},
        "target_start": str(win["target_start"]), "target_end": str(win["target_end"]),
        "weather": {"target": win["target_cost"], "naive": win["naive_cost"], "avoided": win["avoided"], "days": win["days"],
                    "naive_window": [str(win["naive_start"]), str(win["naive_end"])]},
        "hazard_strip": {str(m): months[m]["days"]["high"] for m in range(1, 13)},
        "month_costs": {str(m): months[m]["cost"] for m in range(1, 13)},
        "action": action, "action_reason": why, "request_id": pending["id"] if pending else None, "news": news, "risks": risks,
        "solver": solver_evidence(conn, op["job_a"], op["job_b"]), "conflicts": [], "state": "proposed", "note": "", "goal_id": None,
        "target_edited": False, "passed": passed, "rank": round(feas["score"] * float(op["savings_high"]) * (0.5 if passed else 1)),
    }, None


def mark_conflicts(items):
    """Two selected pairs that need the same project of ours in the same months."""
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if a["our_job"] != b["our_job"]:
                continue
            if a["target_start"] <= b["target_end"] and b["target_start"] <= a["target_end"]:
                a["conflicts"].append(b["id"])
                b["conflicts"].append(a["id"])
    return items


def totals_for(items, considered, skipped, period, note):
    live = [i for i in items if i["state"] != "skipped"]
    counts = {v: sum(1 for i in items if i["verdict"] == v) for v in ("strong", "possible", "unknown", "unlikely")}
    return {"savings": {end: round(sum(i["savings"][end] for i in live)) for end in ENDS},
            "weather_avoided": {end: round(sum(i["weather"]["avoided"][end] for i in live)) for end in ENDS},
            "verdicts": counts, "selected": len(items), "considered": considered, "skipped": skipped,
            "period": [str(period[0]), str(period[1])] if period else None, "conflicts": sum(1 for i in items if i["conflicts"]),
            "passed": sum(1 for i in items if i.get("passed")),
            "actions": {a: sum(1 for i in live if i["action"] == a) for a in ("send request", "follow up", "wait")}, "note": note}


def build(conn, company, horizon="quarter", today=None):
    """Select, time and sequence the overlaps worth pursuing in a horizon."""
    today = today or date.today()
    horizon = horizon if horizon in HORIZONS else "quarter"
    rows = candidates(conn, company)
    reqs = {}
    for r in requests_for(company):
        reqs.setdefault(r["opportunity_id"], []).append(r)
    rows = [r for r in rows if not any(x["status"] == "approved" for x in reqs.get(r["id"], []))]
    pricer = Pricer(conn)
    tried = [horizon] + [h for h in ("year", "window") if h != horizon and list(HORIZONS).index(h) > list(HORIZONS).index(horizon)]
    note, items, skipped, considered, period = "", [], {}, 0, None
    for h in tried:
        period = period_for(h, today)
        items, skipped, considered = [], {}, 0
        for op in rows[:CONSIDER]:
            considered += 1
            it, why = item_for(conn, pricer, op, company, reqs, period, today)
            if it is None:
                skipped[why] = skipped.get(why, 0) + 1
                continue
            if it["verdict"] == "unlikely" and h == "window":
                skipped["unlikely"] = skipped.get("unlikely", 0) + 1
                continue
            items.append(it)
        if len(items) >= MIN_ITEMS or h == tried[-1]:
            if h != horizon:
                note = f"Fewer than {MIN_ITEMS} pairs fit the next {HORIZONS[horizon][0]} months, so the plan looks at the {'next year' if h == 'year' else 'whole build windows'}."
            break
    items.sort(key=lambda i: (bool(i.get("passed")), -i["rank"]))
    limit = HORIZONS[horizon][1]
    items = items[:limit] if limit else items
    items.sort(key=lambda i: (i["target_start"], -i["rank"]))
    mark_conflicts(items)
    return {"horizon": horizon, "period": period, "items": items, "totals": totals_for(items, considered, skipped, period, note)}


def explain_item(it):
    """Why this pair, why these months: the numbers behind the item, nothing computed here."""
    w = it["weather"]
    return {"item_id": it["id"], "overlap_id": it["opportunity_id"], "projects": f"{it['ours']} with {it['theirs']} ({it['partner_name']})",
            "chosen_because": {"feasibility": it["verdict"], "feasibility_score": it["feasibility"], "feasibility_source": it["feasibility_source"],
                               "savings_usd": it["savings"], "rank": it["rank"], "windows_overlap_pct": it["window"]["overlap_pct"]},
            "months_because": {"target": [it["target_start"], it["target_end"]], "weather_cost_usd": w["target"],
                               "instead_of": w["naive_window"], "its_weather_cost_usd": w["naive"], "avoided_usd": w["avoided"],
                               "affected_days": w["days"], "common_window": it["window"]["common"]},
            "action": it["action"], "action_reason": it["action_reason"], "risks": it["risks"], "news": it["news"],
            "conflicts": it["conflicts"], "solver": it["solver"], "narrative": it.get("narrative"),
            "method": "Pairs ranked by feasibility x savings; months are the cheapest run inside both build windows by ten-year weather history. "
                      "Estimates for assessment; a person approves each item."}
