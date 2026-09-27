"""History replay: each real year's county event-days, so a plan is judged against what actually happened, not an average."""
import calendar
import statistics
from collections import defaultdict
from datetime import date

from app.hazards import climate
from app.hazards.config import CLIMATE_YEARS, HAZARDS
from app.hazards.layers import FIPS_STATE, zone_counties
from app.stormlab import finding

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS hazard_events_year (
  county_fips TEXT NOT NULL, state TEXT, year INT NOT NULL, month INT NOT NULL, hazard TEXT NOT NULL, event_days INT NOT NULL,
  PRIMARY KEY (county_fips, year, month, hazard)
)"""
YEAR_SQL = "SELECT county_fips, month, hazard, event_days FROM hazard_events_year WHERE county_fips = ANY(%(fips)s) AND year = %(year)s AND hazard = ANY(%(hazards)s)"
JOBS_SQL = """
SELECT j.id, j.org_id, j.name, lower(j.work_window) AS start_at, upper(j.work_window) AS end_at,
       ST_X(ST_PointOnSurface(j.geom::geometry)) AS lon, ST_Y(ST_PointOnSurface(j.geom::geometry)) AS lat, ST_Buffer(j.geom, 2000)::geometry AS footprint
FROM job j WHERE j.id = ANY(%(ids)s)
"""


def build_events(conn, years=CLIMATE_YEARS):
    """Stream each year's Storm Events file once (gzipped, never unpacked) and store distinct event-days per county-month-hazard-year."""
    conn.execute(TABLE_SQL)
    zones = zone_counties()
    seen = []
    for y in years:
        rows = climate.read_year(y)
        if rows is None:
            continue
        seen.append(y)
        conn.execute("DELETE FROM hazard_events_year WHERE year = %s", (y,))
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO hazard_events_year (county_fips, state, year, month, hazard, event_days) VALUES (%s, %s, %s, %s, %s, %s)",
                            [(f, FIPS_STATE.get(f[:2]), y, m, h, len(v["days"])) for (f, m, h), v in climate.tally(rows, zones).items()])
    return seen


def ensure_events(conn):
    conn.execute(TABLE_SQL)
    if conn.execute("SELECT count(*) AS n FROM hazard_events_year").fetchone()["n"] == 0:
        build_events(conn)


def year_days(rows, shares, fips):
    """Affected days per hazard in one year for the covered months: least and most exposed county under the works."""
    per = defaultdict(lambda: {f: 0.0 for f in fips})
    for r in rows:
        if r["month"] in shares:
            per[r["hazard"]][r["county_fips"]] += r["event_days"] / calendar.monthrange(2025, r["month"])[1] * shares[r["month"]]
    return {h: {"low": round(min(v.values()), 1), "high": round(max(v.values()), 1)} for h, v in per.items()}


def jobs_for(conn, company, opportunity_ids=(), job_ids=(), plan_id=None):
    """Our jobs behind the targets: an overlap's two sides, plain job ids, or the pairs a saved plan holds."""
    ids = set(job_ids or [])
    opps = list(opportunity_ids or [])
    if plan_id:
        p = conn.execute("SELECT items FROM coordination_plan WHERE id = %s AND company_id = %s", (int(plan_id), company)).fetchone()
        opps += [int(i["id"]) for i in (p["items"] if p else []) if i.get("state") != "skipped"][:8]
    for op in conn.execute("""SELECT op.job_a, op.job_b FROM opportunity op JOIN job a ON a.id = op.job_a JOIN job b ON b.id = op.job_b
                              WHERE op.id = ANY(%s) AND %s IN (a.org_id, b.org_id)""", (opps, company)).fetchall() if opps else []:
        ids.update((op["job_a"], op["job_b"]))
    if not ids and (opps or job_ids):
        raise ValueError("none of those overlaps or projects are ours")
    rows = conn.execute(JOBS_SQL, {"ids": list(ids)}).fetchall() if ids else []
    ours = {r["id"] for r in rows if r["org_id"] == company} | {o for op in conn.execute(
        """SELECT op.job_a, op.job_b FROM opportunity op JOIN job a ON a.id = op.job_a JOIN job b ON b.id = op.job_b
           WHERE (op.job_a = ANY(%(ids)s) OR op.job_b = ANY(%(ids)s)) AND %(c)s IN (a.org_id, b.org_id)""", {"ids": list(ids), "c": company}).fetchall()
        for o in (op["job_a"], op["job_b"])}
    return [r for r in rows if r["id"] in ours]  # our projects and partners' inside our overlaps only


def quantile(vals, q):
    if not vals:
        return None
    s = sorted(vals)
    i = (len(s) - 1) * q
    lo, hi = int(i), min(int(i) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (i - lo), 1)


def history_replay(conn, company, opportunity_ids=(), job_ids=(), plan_id=None, years=None, hazards=None):
    """Run the target windows through each real year: distribution of affected days and cost, best and worst year."""
    from app.stormlab.events import apply_event
    years = [int(y) for y in (years or CLIMATE_YEARS)]
    rows = jobs_for(conn, company, opportunity_ids, job_ids, plan_id)
    ours = [r for r in rows if r["org_id"] == company]
    if not ours:
        raise ValueError("none of those targets has a project of ours to replay")
    per_year = {}
    for y in years:
        per_year[y] = apply_event(conn, company, {"kind": "year", "year": y, "hazards": hazards}, rows)["metrics"]
    mids = {y: (m["affected_days_low"] + m["affected_days_high"]) / 2 for y, m in per_year.items()}
    costs = {y: (m["weather_cost_low"] + m["weather_cost_high"]) / 2 for y, m in per_year.items()}
    worst, best = max(mids, key=mids.get), min(mids, key=mids.get)
    avg_days = round(statistics.mean(mids.values()), 1)
    avg_cost = round(statistics.mean(costs.values()), -2)
    base = finding.metrics(affected_days_low=round(min(m["affected_days_low"] for m in per_year.values()), 1),
                           affected_days_high=round(max(m["affected_days_high"] for m in per_year.values()), 1),
                           weather_cost_low=round(min(m["weather_cost_low"] for m in per_year.values()), -2),
                           weather_cost_high=round(max(m["weather_cost_high"] for m in per_year.values()), -2))
    base["affected_days_low"]["label"], base["affected_days_high"]["label"] = "Affected days, calmest year", "Affected days, worst year"
    base["weather_cost_low"]["label"], base["weather_cost_high"]["label"] = "Extra cost, calmest year", "Extra cost, worst year"
    scenario = finding.metrics(affected_days_low=per_year[worst]["affected_days_low"], affected_days_high=per_year[worst]["affected_days_high"],
                               weather_cost_low=per_year[worst]["weather_cost_low"], weather_cost_high=per_year[worst]["weather_cost_high"],
                               worst_year=worst, best_year=best)
    for k in ("affected_days_low", "affected_days_high", "weather_cost_low", "weather_cost_high"):
        scenario[k]["label"] = scenario[k]["label"] + f" ({worst})"
    names = ", ".join(r["name"] for r in ours[:3]) + (f" and {len(ours) - 3} more" if len(ours) > 3 else "")
    title = f"{len(years)}-year weather replay: {names}"
    evidence = [f"across {years[0]} to {years[-1]}, affected days ran {quantile(list(mids.values()), 0.1):g} (p10) to {quantile(list(mids.values()), 0.9):g} (p90), median {quantile(list(mids.values()), 0.5):g}, average {avg_days:g}",
                f"worst year {worst}: {per_year[worst]['affected_days_low']:g} to {per_year[worst]['affected_days_high']:g} days, {finding.usd(per_year[worst]['weather_cost_low'])} to {finding.usd(per_year[worst]['weather_cost_high'])}",
                f"calmest year {best}: {per_year[best]['affected_days_low']:g} to {per_year[best]['affected_days_high']:g} days, {finding.usd(per_year[best]['weather_cost_low'])} to {finding.usd(per_year[best]['weather_cost_high'])}",
                f"average extra cost {finding.usd(avg_cost)} per run of these windows"]
    chart = {"title": f"Weather-affected days by year, {names}", "kind": "bar", "x": [str(y) for y in years], "unit": "days",
             "series": [{"name": "low (calmest county)", "values": [per_year[y]["affected_days_low"] for y in years], "color": "#a5d8c8"},
                        {"name": "high (most exposed county)", "values": [per_year[y]["affected_days_high"] for y in years], "color": "#12a36b"}],
             "source": "NOAA Storm Events, counties under the works, scaled to each build window's months"}
    params = {"opportunity_ids": list(opportunity_ids or []), "job_ids": list(job_ids or []), "plan_id": plan_id, "years": years, "hazards": hazards}
    f = finding.make("history_replay", title, "How would these build windows have fared in each of the last ten years?", params, base, scenario,
                     notes=["Each year replaces the ten-year average with that year's real county event-days. "
                            "Windows are read as they stand now, so a shifted plan replays against the same years. Estimates for assessment, never work orders."],
                     evidence=evidence, knobs=[finding.knob("years", "select", years, "Years", options=CLIMATE_YEARS),
                                                finding.knob("hazards", "select", hazards or list(HAZARDS), "Hazards", options=list(HAZARDS))],
                     sources=["NOAA NCEI Storm Events Database (2016-2025)"],
                     chart=chart, per_year={str(y): m for y, m in per_year.items()}, distribution={"p10": quantile(list(mids.values()), 0.1),
                     "p50": quantile(list(mids.values()), 0.5), "p90": quantile(list(mids.values()), 0.9), "mean_days": avg_days, "mean_cost": avg_cost})
    return finding.save(conn, company, f)
