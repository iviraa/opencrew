"""What exposure costs: idle crews and equipment on affected days, storm-rate labor after big events, and what coordinating saves.

Every number traces to a key in config.ASSUMPTIONS (crew_costs.json) or a stop rule; ranges are low/high, never a single guess.
"""
import calendar
from contextvars import ContextVar
from datetime import date, datetime, timedelta, timezone

from app.config import ASSUMPTIONS, PHASES, STOP_RULES
from app.engine.cost import SHARE, factors, savings_for
from app.hazards import exposure
from app.hazards.config import HAZARDS

EQUIPMENT = {  # what sits idle on an affected day, by the phase the works are in
    "survey & permitting": [],
    "clearing": ["digger_derrick_standby_usd_day", "bucket_truck_standby_usd_day"],
    "construction": ["crane_standby_usd_day", "digger_derrick_standby_usd_day", "bucket_truck_standby_usd_day", "puller_tensioner_standby_usd_day"],
    "energization": ["bucket_truck_standby_usd_day"],
}
CREW_IDLE = {"survey & permitting": 0.2, "clearing": 1.0, "construction": 1.0, "energization": 1.0}  # share of the crew a weather day idles
EVENT_DAYS = {"tropical": 3, "winter": 2, "wildfire": 2, "flood": 1}  # how long one event keeps a site down; demob only pays for long ones
STORM = {"tropical", "winter", "tornado"}  # after these, restoration pulls crews at storm rates
LABOR_SHARE = 0.6  # wages inside crew_day_usd (54% at the low end, 67% at the high end per its note)
RULES = {  # which stop rules make a day of each hazard an affected day
    "wind": ["crane_gust_mph", "stringing_gust_mph", "aerial_lift_wind_mph"], "storms": ["lightning_miles", "adverse_weather_structures"],
    "tornado": ["adverse_weather_structures"], "winter": ["ice_aerial", "adverse_weather_structures"],
    "heat": ["heat_index_caution_f", "heat_index_stop_f"], "flood": [], "tropical": ["adverse_weather_structures"],
    "wildfire": ["red_flag_hot_work"], "earthquake": [], "hail": ["adverse_weather_structures"],
}
ENDS = ("low", "high")
MONTHS = list(calendar.month_abbr)


OVERRIDES = ContextVar("hazard_cost_overrides", default=None)  # a what-if can swap assumption values for one evaluation


def _a(key, end):
    o = (OVERRIDES.get() or {}).get(key) or {}
    return float(o[end]) if end in o else float(ASSUMPTIONS[key][end])


def _day(d):
    return d.date() if isinstance(d, datetime) else d


def phase_mix(window, start, end):
    """Share of the period spent in each phase; outside the build window the project's average mix is assumed."""
    ws, we = _day(window[0]), _day(window[1])
    total = max((we - ws).days, 1)
    lo, hi = max(start, ws), min(end, we)
    if hi < lo:
        return {p: s for p, s in PHASES}, False
    mix, at = {}, 0.0
    for phase, share in PHASES:
        ps, pe = ws + timedelta(days=round(total * at)), ws + timedelta(days=round(total * (at + share)))
        days = (min(pe, hi) - max(ps, lo)).days + (1 if min(pe, hi) >= max(ps, lo) else 0)
        if days > 0:
            mix[phase] = days
        at += share
    n = sum(mix.values()) or 1
    return {p: round(v / n, 3) for p, v in mix.items()}, True


def per_day(mix, end):
    """Standby cost of one affected day: the idle crew plus the equipment held for the phases under way."""
    crew = _a("crew_day_usd", end) * sum(CREW_IDLE[p] * f for p, f in mix.items())
    equipment = sum(f * sum(_a(k, end) for k in EQUIPMENT[p]) for p, f in mix.items())
    return {"crew": round(crew), "equipment": round(equipment), "standby": round(crew + equipment)}


def hazard_item(h, days, mix):
    """Cost of one hazard's affected days: standby or demobilize (whichever is cheaper per event), plus a storm-rate premium."""
    length = EVENT_DAYS.get(h, 1)
    out = {"hazard": h, "label": HAZARDS[h][0], "days": days, "event_days": length, "rules": [r for r in RULES[h] if r in STOP_RULES],
           "option": {}, "per_day": {}, "premium": {}, "total": {}}
    for end in ENDS:
        standby = per_day(mix, end)["standby"]
        demob = _a("demob_remob_usd", end)
        can_move = length >= 2  # a round trip costs a day itself, so only multi-day events are worth demobilizing for
        cheaper = min(standby * length, demob) / length if can_move else standby
        out["option"][end] = "demob" if can_move and demob < standby * length else "standby"
        premium = LABOR_SHARE * _a("crew_day_usd", end) * (_a("storm_rate_multiplier", end) - 1) if h in STORM else 0.0
        out["per_day"][end] = round(cheaper)
        out["premium"][end] = round(premium)
        out["total"][end] = round(days[end] * (cheaper + premium))
    return out


def days_of(exp):
    """Affected days per hazard as low/high (now7 forecasts count as a single number)."""
    out = {}
    for h in exp["hazards"]:
        d = h["affected_days"]
        out[h["hazard"]] = {"low": float(d["forecast"]), "high": float(d["forecast"])} if exp["period"] == "now7" else {"low": float(d["low"]), "high": float(d["high"])}
    return out


def site_cost(exp, window):
    start, end = date.fromisoformat(exp["start"]), date.fromisoformat(exp["end"])
    mix, inside = phase_mix(window, start, end)
    items = [hazard_item(h, d, mix) for h, d in days_of(exp).items() if d["high"] > 0]
    items.sort(key=lambda x: -x["total"]["high"])
    total = {end: round(sum(i["total"][end] for i in items), -2) for end in ENDS}
    return {"kind": "site", "id": exp["id"], "name": exp["names"][0], "period": exp["period"], "start": exp["start"], "end": exp["end"],
            "phase_mix": mix, "inside_window": inside, "per_day": {end: per_day(mix, end) for end in ENDS}, "items": items, "total": total,
            "assumptions": sorted({"crew_day_usd", "demob_remob_usd", "storm_rate_multiplier", *(k for p in mix for k in EQUIPMENT[p])}),
            "method": ("Expected extra cost = affected days x the cheaper of holding the crew and equipment on standby or demobilizing and coming back, "
                       "plus storm-rate labor after tropical, winter or tornado days. Idle rates are equipment only; contractor overhead is not included. "
                       + ("" if inside else "The period falls outside the build window, so the project's average phase mix is assumed. ")
                       + "Estimates for assessment, not work orders.")}


SITE_WINDOW_SQL = "SELECT id, org_id, lower(work_window) AS start_at, upper(work_window) AS end_at FROM job WHERE id = %(id)s"
ZONE_SQL = "SELECT id, job_a, job_b, tier, overlap_m, drive_min, time_overlap FROM opportunity WHERE id = %(id)s"


def for_site(conn, job_id, period, month=None, hazards=None, today=None):
    exp = exposure.assess(conn, "site", job_id, period, month, hazards, today)
    if not exp:
        return None
    w = conn.execute(SITE_WINDOW_SQL, {"id": job_id}).fetchone()
    return site_cost(exp, (w["start_at"], w["end_at"]))


def month_days(conn, job_id, hazards):
    """Typical affected days per hazard for each calendar month at a site, from its counties' ten-year history."""
    r = conn.execute(exposure.SITE_SQL, {"id": job_id}).fetchone()
    fips = exposure.county_fips_for(conn, r["footprint"])
    rows = conn.execute(exposure.COUNTIES_SQL, {"hazards": hazards or list(HAZARDS), "fips": fips}).fetchall() if fips else []
    return {m: exposure.history_days(rows, {m: calendar.monthrange(2025, m)[1]}) for m in range(1, 13)}


def shared_days(days_a, days_b, drive_min, end):
    """Affected days both sites share, so one standby crew and yard could cover both: the overlap of their days, cut by the commute."""
    drive = factors(None, drive_min)["drive"]
    return sum(min(days_a.get(h, {}).get(end, 0.0), days_b.get(h, {}).get(end, 0.0)) for h in set(days_a) | set(days_b)) * drive * SHARE[end]


def coordination(conn, op, cost_a, cost_b, days_a, days_b, exp_a_days, exp_b_days, drive_min, period_days):
    """Separate vs coordinated cost for the pair in the period, and the cheapest months to work together."""
    out = {"partner": None, "separate": {}, "coordinated": {}, "savings": {}, "items": [], "one_off": [], "best_months": []}
    small = min(cost_a, cost_b, key=lambda c: c["per_day"]["high"]["standby"])  # the crew released is the smaller one
    for end in ENDS:
        sep = cost_a["total"][end] + cost_b["total"][end]
        shared = shared_days(days_a, days_b, drive_min, end) * small["per_day"][end]["standby"]
        out["separate"][end] = round(sep, -2)
        out["coordinated"][end] = round(max(sep - shared, 0), -2)
        out["savings"][end] = round(min(shared, sep), -2)
    out["items"].append({"name": "one standby crew and yard on shared days", "low": out["savings"]["low"], "high": out["savings"]["high"],
                         "shared_days": {end: round(shared_days(days_a, days_b, drive_min, end), 1) for end in ENDS}})
    sav = savings_for(conn, op)
    for name, v in sav["items"].items():
        out["one_off"].append({"name": name, "low": v.get("low", 0), "high": v.get("high", 0)})  # per project, not per period
    # cheapest months: pair cost per 30 days with the project-average phase mix
    mix = {p: s for p, s in PHASES}
    months = []
    for m in range(1, 13):
        da, db = exp_a_days.get(m, {}), exp_b_days.get(m, {})
        cost = {}
        for end in ENDS:
            a = sum(hazard_item(h, {"low": float(d["low"]), "high": float(d["high"])}, mix)["total"][end] for h, d in da.items())
            b = sum(hazard_item(h, {"low": float(d["low"]), "high": float(d["high"])}, mix)["total"][end] for h, d in db.items())
            shared = shared_days({h: {end: d[end]} for h, d in da.items()}, {h: {end: d[end]} for h, d in db.items()}, drive_min, end)
            scale = 30 / calendar.monthrange(2025, m)[1]
            cost[end] = round(max(a + b - shared * small["per_day"][end]["standby"], 0) * scale, -2)
        days = {end: round(sum(d[end] for d in da.values()) + sum(d[end] for d in db.values()), 1) for end in ENDS}
        months.append({"month": m, "label": MONTHS[m], "cost_per_30d": cost, "days": days})
    months.sort(key=lambda x: (x["cost_per_30d"]["high"], x["cost_per_30d"]["low"]))
    scale = 30 / max(period_days, 1)
    for x in months[:3]:
        x["saves_vs_period"] = {end: round(max(out["coordinated"][end] * scale - x["cost_per_30d"][end], 0), -2) for end in ENDS}
    out["best_months"] = months[:3]
    out["all_months"] = sorted(months, key=lambda x: x["month"])
    return out


def for_zone(conn, opp_id, period, month=None, hazards=None, today=None):
    op = conn.execute(ZONE_SQL, {"id": int(opp_id)}).fetchone()
    if not op:
        return None
    exp = {}
    costs = {}
    for side in ("job_a", "job_b"):
        e = exposure.assess(conn, "site", op[side], period, month, hazards, today)
        w = conn.execute(SITE_WINDOW_SQL, {"id": op[side]}).fetchone()
        exp[side], costs[side] = e, site_cost(e, (w["start_at"], w["end_at"]))
    ca, cb = costs["job_a"], costs["job_b"]
    orgs = {side: conn.execute(SITE_WINDOW_SQL, {"id": op[side]}).fetchone()["org_id"] for side in ("job_a", "job_b")}
    coord = coordination(conn, op, ca, cb, days_of(exp["job_a"]), days_of(exp["job_b"]), month_days(conn, op["job_a"], hazards),
                         month_days(conn, op["job_b"], hazards), op["drive_min"], exp["job_a"]["days"])
    coord["partners"] = [orgs["job_a"], orgs["job_b"]]
    cost = {"kind": "zone", "id": int(opp_id), "period": period, "start": exp["job_a"]["start"], "end": exp["job_a"]["end"], "sites": [ca, cb],
            "total": {end: round(ca["total"][end] + cb["total"][end], -2) for end in ENDS},
            "assumptions": sorted(set(ca["assumptions"]) | set(cb["assumptions"])), "method": ca["method"]}
    return cost, coord
