"""Datasets Crewly can chart or export: computed here from the planner tables, never by the model."""
import calendar
import csv
import io
from collections import Counter, defaultdict
from datetime import date

from app.companies import companies, name, partner, short
from app.hazards.config import HAZARDS
from app.queries import JOB_SQL

MONTHS = [calendar.month_abbr[m] for m in range(1, 13)]
KINDS = ("bar", "line", "stacked")
COLORS = {"low": "#a5d8c8", "high": "#12a36b", "ours": "#5b2bb5", "partner": "#ff9f1c"}
HAZARD_COLORS = {"wind": "#3a86ff", "storms": "#8e5cf7", "tornado": "#e84393", "winter": "#2ec4b6", "heat": "#f4a261", "flood": "#12a36b",
                 "tropical": "#c9184a", "wildfire": "#fb8500", "earthquake": "#9b5de5", "hail": "#00a6fb"}


def mine_sql(company):
    from app.crewly.app_tools import mine_sql as _mine
    return _mine(company)


def _int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def years_of(options, span=2):
    y = options.get("years") or []
    today = date.today().year
    lo = _int(y[0] if len(y) > 0 else None, today)
    hi = _int(y[1] if len(y) > 1 else None, lo + span)
    return (lo, hi) if hi >= lo else (hi, lo)


def month_labels(lo, hi):
    return [f"{MONTHS[m - 1]} {y}" for y in range(lo, hi + 1) for m in range(1, 13)]


def _partner_id(options):
    from app.crewly.app_tools import find_company
    p = options.get("partner")
    return find_company(p) if p else None


def _opp(conn, options):
    opp = str(options.get("id") or "").lstrip("#")
    if not opp.isdigit():
        raise ValueError("this dataset needs an overlap id like #18")
    return int(opp)


# ---------- datasets: each returns (chart, rows) ----------

def overlaps_by_month(conn, company, options):
    """How many of our overlaps have both projects building in each month."""
    lo, hi = years_of(options)
    who = _partner_id(options)
    rows = conn.execute(mine_sql(company) + " AND (%(p)s::text IS NULL OR %(p)s IN (ja.org_id, jb.org_id))", {"p": who}).fetchall()
    counts = Counter()
    for r in rows:
        s, e = max(r["a_start"], r["b_start"]), min(r["a_end"], r["b_end"])
        end = e.date() if hasattr(e, "date") else e
        d = date(s.year, s.month, 1)
        while d <= end:
            if lo <= d.year <= hi:
                counts[(d.year, d.month)] += 1
            d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    labels = month_labels(lo, hi)
    values = [counts[(y, m)] for y in range(lo, hi + 1) for m in range(1, 13)]
    title = f"Overlaps building together by month, {lo} to {hi}" + (f", with {name(who)}" if who else "")
    chart = {"title": title, "x": labels, "series": [{"name": "overlaps", "values": values, "color": COLORS["ours"]}], "unit": "overlaps",
             "source": "planner filings; both projects' build windows"}
    return chart, [{"month": lab, "overlaps": v} for lab, v in zip(labels, values)]


def hazard_days_by_month(conn, company, options):
    """Typical weather-affected days per month at a site or across an overlap's two sites, from ten years of county history."""
    from app.hazards import cost, exposure
    ident = str(options.get("id") or "").lstrip("#")
    if not ident:
        raise ValueError("this dataset needs a site id like gpc-123 or an overlap id like #18")
    hazards = [h for h in (options.get("hazards") or []) if h in HAZARDS] or list(HAZARDS)
    if ident.isdigit():
        op = conn.execute(exposure.ZONE_SQL, {"id": int(ident)}).fetchone()
        if not op:
            raise ValueError(f"no overlap #{ident}")
        sites, title = [op["job_a"], op["job_b"]], f"Weather-affected days by month, overlap #{ident}"
    else:
        r = conn.execute(exposure.SITE_SQL, {"id": ident}).fetchone()
        if not r:
            raise ValueError(f"no site {ident}")
        sites, title = [ident], f"Weather-affected days by month, {r['name']}"
    per_site = [cost.month_days(conn, s, hazards) for s in sites]
    series = []
    for h in hazards:
        vals = [round(max(d[m].get(h, {}).get("high", 0.0) for d in per_site), 1) for m in range(1, 13)]  # the more exposed site sets the month
        if any(vals):
            series.append({"name": HAZARDS[h][0], "values": vals, "color": HAZARD_COLORS.get(h)})
    chart = {"title": title, "x": MONTHS, "series": series, "unit": "days", "source": "NOAA Storm Events 2016-2025, counties under the works"}
    rows = [{"month": MONTHS[m - 1], **{s["name"]: s["values"][m - 1] for s in series}} for m in range(1, 13)]
    return chart, rows


def savings_by_partner(conn, company, options):
    top = max(1, min(_int(options.get("top"), 8), 20))
    rows = conn.execute(mine_sql(company)).fetchall()
    low, high, n = Counter(), Counter(), Counter()
    for r in rows:
        p = partner(r, company)
        low[p] += r["savings_low"] or 0
        high[p] += r["savings_high"] or 0
        n[p] += 1
    order = [p for p, _ in high.most_common(top)]
    chart = {"title": f"Estimated savings by neighboring utility (top {len(order)})", "x": [short(p) for p in order],
             "series": [{"name": "low", "values": [round(low[p]) for p in order], "color": COLORS["low"]},
                        {"name": "high", "values": [round(high[p]) for p in order], "color": COLORS["high"]}],
             "unit": "USD", "source": "savings model per overlap, summed by partner"}
    return chart, [{"partner": name(p), "overlaps": n[p], "savings_low": round(low[p]), "savings_high": round(high[p])} for p in order]


def projects_by_year(conn, company, options):
    lo, hi = years_of(options, span=4)
    who = _partner_id(options)
    orgs = [company] + ([who] if who and who != company else [])
    rows = conn.execute("SELECT org_id, extract(year FROM in_service)::int AS y, count(*) AS n FROM job WHERE horizon = 'long' AND org_id = ANY(%s) "
                        "AND in_service IS NOT NULL GROUP BY 1, 2", (orgs,)).fetchall()
    by = defaultdict(Counter)
    for r in rows:
        by[r["org_id"]][r["y"]] = r["n"]
    years = list(range(lo, hi + 1))
    series = [{"name": short(o), "values": [by[o][y] for y in years], "color": COLORS["ours"] if o == company else COLORS["partner"]} for o in orgs]
    chart = {"title": f"Projects by in-service year, {lo} to {hi}", "x": [str(y) for y in years], "series": series, "unit": "projects",
             "source": "planner filings"}
    return chart, [{"year": y, **{s["name"]: s["values"][i] for s in series}} for i, y in enumerate(years)]


def cost_by_category(conn, company, options):
    from app.engine.cost import savings_for
    from app.queries import OPP_SQL
    opp = _opp(conn, options)
    op = conn.execute(OPP_SQL + " WHERE op.id = %s", (opp,)).fetchone()
    if not op or company not in (op["a_org"], op["b_org"]):
        raise ValueError(f"#{opp} is not one of our overlaps")
    s = savings_for(conn, op)
    items = list(s["items"].items())
    chart = {"title": f"Savings by cost type, overlap #{opp}", "x": [k for k, _ in items],
             "series": [{"name": "low", "values": [round(v["low"]) for _, v in items], "color": COLORS["low"]},
                        {"name": "high", "values": [round(v["high"]) for _, v in items], "color": COLORS["high"]}],
             "unit": "USD", "source": "savings model with cited unit costs"}
    return chart, [{"cost_type": k, "low": round(v["low"]), "high": round(v["high"])} for k, v in items]


def news_by_impact(conn, company, options):
    from app.news import feed
    days = max(1, min(_int(options.get("days"), 90), 365))
    who = _partner_id(options) or company
    items = feed.for_org(conn, who, days)
    counts = Counter(i["impact"] for i in items)
    order = [k for k, _ in counts.most_common()]
    chart = {"title": f"News about {name(who)} by impact, last {days} days", "x": order,
             "series": [{"name": "stories", "values": [counts[k] for k in order], "color": COLORS["ours"]}], "unit": "stories",
             "source": "news pipeline (Google News, GDELT), rule-classified"}
    return chart, [{"impact": k, "stories": counts[k]} for k in order]


def plan_totals(conn, company, options):
    from app.planner import build, store
    horizon = options.get("horizon") if options.get("horizon") in build.HORIZONS else "quarter"
    row = store.latest(conn, company, horizon)
    if not row:
        raise ValueError("no plan yet; ask Crewly to build one first")
    items = [i for i in row["items"] if i["state"] != "skipped"]
    chart = {"title": f"Plan for the {horizon}: expected savings by pair (v{row['version']})", "x": [f"#{i['id']} {i['partner_short']}" for i in items],
             "series": [{"name": "low", "values": [round(i["savings"]["low"]) for i in items], "color": COLORS["low"]},
                        {"name": "high", "values": [round(i["savings"]["high"]) for i in items], "color": COLORS["high"]}],
             "unit": "USD", "source": "coordination plan"}
    rows = [{"overlap": i["id"], "ours": i["ours"], "partner": i["partner_name"], "verdict": i["verdict"], "months": f"{i['target_start'][:7]} to {i['target_end'][:7]}",
             "savings_low": round(i["savings"]["low"]), "savings_high": round(i["savings"]["high"]), "action": i["action"], "state": i["state"]} for i in items]
    return chart, rows


DATASETS = {
    "overlaps_by_month": (overlaps_by_month, "our overlaps with both projects building, per month; options years [from, to], partner"),
    "hazard_days_by_month": (hazard_days_by_month, "typical weather-affected days per month for a site or overlap; options id, hazards"),
    "savings_by_partner": (savings_by_partner, "estimated savings summed by neighboring utility; options top"),
    "projects_by_year": (projects_by_year, "our projects by in-service year, optionally a partner's too; options years, partner"),
    "cost_by_category": (cost_by_category, "one overlap's savings by cost type; options id"),
    "news_by_impact": (news_by_impact, "our news stories by impact; options days, partner"),
    "plan_totals": (plan_totals, "the latest plan's pairs and savings; options horizon"),
}


def make(conn, company, dataset, options=None):
    """A chart spec plus its rows for one dataset."""
    if dataset not in DATASETS:
        raise ValueError(f"unknown dataset {dataset!r}; one of {', '.join(DATASETS)}")
    options = options or {}
    kind = options.get("kind") if options.get("kind") in KINDS else ("stacked" if dataset == "hazard_days_by_month" else "bar")
    chart, rows = DATASETS[dataset][0](conn, company, options)
    chart = {**chart, "kind": kind, "dataset": dataset, "options": {k: v for k, v in options.items() if v not in (None, "", [])}}
    return chart, rows


def to_csv(rows):
    if not rows:
        return ""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


# ---------- raw tables for get_data ----------

def overlaps_table(conn, company, f):
    lo, hi = years_of(f, span=10) if f.get("years") else (None, None)
    who = _partner_id(f)
    sql = mine_sql(company) + " AND (%(p)s::text IS NULL OR %(p)s IN (ja.org_id, jb.org_id)) AND (%(t)s::text IS NULL OR op.tier = %(t)s)"
    if lo:
        sql += " AND ja.work_window && tstzrange(%(s)s::timestamptz, %(e)s::timestamptz) AND jb.work_window && tstzrange(%(s)s::timestamptz, %(e)s::timestamptz)"
    rows = conn.execute(sql + " ORDER BY op.score DESC LIMIT 500", {"p": who, "t": f.get("tier"), "s": f"{lo}-01-01" if lo else None, "e": f"{hi}-12-31" if hi else None}).fetchall()
    verdicts = {}
    if f.get("verdict"):
        verdicts = {r["opportunity_id"]: r["verdict"] for r in conn.execute("SELECT opportunity_id, verdict FROM feasibility_assessment WHERE company_id = %s", (company,)).fetchall()}
    out = []
    for r in rows:
        mine = r["a_org"] == company
        v = verdicts.get(r["id"])
        if f.get("verdict") and v != f["verdict"]:
            continue
        out.append({"overlap": r["id"], "ours": r["a_name"] if mine else r["b_name"], "partner": name(partner(r, company)), "theirs": r["b_name"] if mine else r["a_name"],
                    "tier": r["tier"], "miles_apart": round(r["distance_m"] / 1609.344, 1), "drive_min": r["drive_min"], "window_overlap_pct": round(r["time_overlap"] * 100),
                    "savings_low": round(r["savings_low"] or 0), "savings_high": round(r["savings_high"] or 0), "score": round(r["score"], 2), **({"verdict": v} if verdicts else {})})
    return out[: max(1, min(_int(f.get("top"), 500), 500))]


def projects_table(conn, company, f):
    lo, hi = years_of(f, span=10) if f.get("years") else (None, None)
    rows = conn.execute(JOB_SQL + " WHERE j.horizon = 'long' AND j.org_id = %(o)s AND (%(st)s::text IS NULL OR j.state = %(st)s) AND (%(s)s::text IS NULL OR j.status = %(s)s)"
                        " AND (%(lo)s::int IS NULL OR extract(year FROM j.in_service) BETWEEN %(lo)s AND %(hi)s) ORDER BY j.in_service LIMIT 500",
                        {"o": company, "st": f.get("state"), "s": f.get("status"), "lo": lo, "hi": hi}).fetchall()
    return [{"project": r["id"], "name": r["name"], "type": r["job_type"], "kv": r["voltage_kv"], "start": str(r["start_at"])[:10], "end": str(r["end_at"])[:10],
             "in_service": str(r["in_service"]), "status": r.get("status"), "cost_usd": r["cost_usd"] and round(r["cost_usd"]), "state": r.get("state")} for r in rows]


def hazard_table(conn, company, f):
    from app.hazards.exposure import PERIODS, assess
    ident = str(f.get("id") or "").lstrip("#")
    kind = "zone" if ident.isdigit() else "site"
    period = f.get("period") if f.get("period") in PERIODS else "month"
    out = assess(conn, kind, ident, period, _int(f.get("month"), None)) if ident else None
    if not out:
        raise ValueError("this dataset needs a site id or overlap id")
    return [{"hazard": h["label"], "affected_days_low": h["affected_days"].get("low"), "affected_days_high": h["affected_days"].get("high"),
             "forecast_days": h["affected_days"].get("forecast"), "active_now": len(h.get("live") or []), "why": h["why"]} for h in out["hazards"]]


def news_table(conn, company, f):
    from app.news import feed
    who = _partner_id(f) or company
    return [{"date": (i["published"] or "")[:10], "title": i["title"], "impact": i["impact"], "affects_work": i["affects_work"], "source": i["source"],
             "linked_overlaps": ",".join(map(str, i["opportunity_ids"][:5])), "url": i["url"]} for i in feed.for_org(conn, who, max(1, min(_int(f.get("days"), 90), 365)), f.get("impact"))[:500]]


TABLES = {"overlaps": overlaps_table, "projects": projects_table, "hazard_exposure": hazard_table, "news": news_table}


def table(conn, company, dataset, filters=None, ctx=None):
    """Rows and columns for a raw table or any chart dataset."""
    filters = filters or {}
    if dataset == "requests":
        from app.crewly.app_tools import collab_requests
        out, _ = collab_requests(ctx, conn, filters.get("direction") or "any", filters.get("status"), 20)
        rows = out["requests"]
    elif dataset in TABLES:
        rows = TABLES[dataset](conn, company, filters)
    elif dataset in DATASETS:
        _, rows = DATASETS[dataset][0](conn, company, filters)
    else:
        raise ValueError(f"unknown dataset {dataset!r}; one of {', '.join([*TABLES, 'requests', *DATASETS])}")
    rows = rows[:500]
    cols = list(rows[0].keys()) if rows else []
    return {"dataset": dataset, "filters": {k: v for k, v in filters.items() if v not in (None, "", [])}, "columns": cols, "rows": rows, "count": len(rows)}
