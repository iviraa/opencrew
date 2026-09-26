"""What touches a site or an overlap zone in a period: live alerts and outlooks, and ten years of history for the covered months."""
import calendar
from datetime import date, datetime, timedelta, timezone

from app.hazards.config import HAZARDS

PERIODS = ("now7", "weeks", "season", "month", "window")
PRODUCTS = {  # what each period looks at; history covers the rest
    "now7": ["nws_alert", "spc", "spc48", "spc_fire", "wpc_ero", "nhc_gtwo", "wfigs_perimeters", "wfigs_incidents", "usgs"],
    "weeks": ["spc48", "cpc_6-10 day", "cpc_8-14 day", "cpc_weeks 3-4"],
    "season": ["cpc_monthly", "cpc_seasonal"],
    "month": [], "window": [],
}
COUNTED = {"nws_alert", "spc", "spc48", "spc_fire", "wpc_ero", "nhc_gtwo", "wfigs_perimeters", "wfigs_incidents", "usgs"}  # events, not leans
WEEKS_DAYS, SEASON_DAYS = (7, 28), (28, 120)  # what each outlook period covers, in days from today

SITE_SQL = """
SELECT j.id, j.name, j.org_id, lower(j.work_window) AS start_at, upper(j.work_window) AS end_at, ST_AsGeoJSON(j.geom::geometry, 5)::json AS geometry,
       ST_Buffer(j.geom, 2000)::geometry AS footprint  -- 2 km around the works: yards and access roads
FROM job j WHERE j.id = %(id)s
"""

ZONE_SQL = """
SELECT op.id, op.job_a, op.job_b, ja.name AS a_name, jb.name AS b_name, ja.org_id AS a_org, jb.org_id AS b_org,
       lower(ja.work_window) AS a_start, upper(ja.work_window) AS a_end, lower(jb.work_window) AS b_start, upper(jb.work_window) AS b_end,
       ST_Buffer(ST_Union(ja.geom::geometry, jb.geom::geometry)::geography, 2000)::geometry AS footprint
FROM opportunity op JOIN job ja ON ja.id = op.job_a JOIN job jb ON jb.id = op.job_b WHERE op.id = %(id)s
"""

LIVE_SQL = """
SELECT l.id, l.layer, l.hazard, l.product, l.label, l.rank, l.period_start, l.period_end, l.props
FROM hazard_layer l
WHERE l.hazard = ANY(%(hazards)s) AND l.product = ANY(%(products)s) AND l.period_end >= %(start)s AND l.period_start <= %(end)s
  AND ST_Intersects(l.geom::geometry, %(footprint)s::geometry)
ORDER BY l.rank DESC, l.period_start
"""

COUNTIES_SQL = """
SELECT c.county_fips, c.month, c.hazard, c.event_days, c.years, c.damage_usd
FROM hazard_climate c
WHERE c.hazard = ANY(%(hazards)s) AND c.county_fips = ANY(%(fips)s)
"""

FIPS_SQL = "SELECT geoid FROM tract WHERE ST_Intersects(geom::geometry, %(footprint)s::geometry)"  # tracts only cover GA and SC


def period_range(period, month=None, window=None, today=None):
    """Start and end dates a period covers; 'window' is the site's own build window."""
    today = today or date.today()
    if period == "now7":
        return today, today + timedelta(days=7)
    if period == "weeks":
        return today + timedelta(days=WEEKS_DAYS[0]), today + timedelta(days=WEEKS_DAYS[1])
    if period == "season":
        return today + timedelta(days=SEASON_DAYS[0]), today + timedelta(days=SEASON_DAYS[1])
    if period == "month":
        m = month or today.month
        y = today.year if m >= today.month else today.year + 1
        return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
    if period == "window" and window:
        return window[0].date() if hasattr(window[0], "date") else window[0], window[1].date() if hasattr(window[1], "date") else window[1]
    return today, today + timedelta(days=30)


def month_shares(start, end):
    """How many days of each calendar month a date range covers."""
    out, d = {}, start
    while d <= end:
        last = date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])
        stop = min(last, end)
        out[d.month] = out.get(d.month, 0) + (stop - d).days + 1
        d = stop + timedelta(days=1)
    return out


def history_days(rows, shares):
    """Expected affected days per hazard for the covered months, low and high, from county event-days per year."""
    per = {}
    for r in rows:
        if r["month"] not in shares:
            continue
        rate = r["event_days"] / max(r["years"], 1) / calendar.monthrange(2025, r["month"])[1]  # event-days per calendar day
        per.setdefault(r["hazard"], {}).setdefault(r["county_fips"], 0.0)
        per[r["hazard"]][r["county_fips"]] += rate * shares[r["month"]]
    out = {}
    for h, by_county in per.items():
        vals = sorted(by_county.values())
        out[h] = {"low": round(vals[0], 1), "high": round(vals[-1], 1), "counties": len(vals)}
    return out


def live_days(rows, start, end):
    """Days in the period with at least one alert, outlook area, fire or quake over the works, per hazard (sets of dates)."""
    out = {}
    for r in rows:
        if r["product"] not in COUNTED:
            continue  # a monthly lean is not an event day
        s, e = max(r["period_start"].date(), start), min(r["period_end"].date(), end)
        days = {s + timedelta(days=i) for i in range((e - s).days + 1)} if e >= s else set()
        out.setdefault(r["hazard"], set()).update(days)
    return out


def county_fips_for(conn, footprint_wkb):
    """Counties under a footprint, from the national county file (loaded once into a temp table per connection)."""
    from app.hazards.layers import county_shapes
    from shapely import wkb
    fp = footprint_wkb if hasattr(footprint_wkb, "geom_type") else wkb.loads(footprint_wkb, hex=True) if isinstance(footprint_wkb, str) else wkb.loads(bytes(footprint_wkb))
    box = fp.bounds
    return [f for f, g in county_shapes().items() if g.bounds[2] >= box[0] and g.bounds[0] <= box[2] and g.bounds[3] >= box[1] and g.bounds[1] <= box[3]
            and g.intersects(fp)]


def assess(conn, kind, ident, period="now7", month=None, hazards=None, today=None):
    """Exposure of a site or zone in a period: {hazards: [{hazard, label, affected_days, live: [...], history}], ...}."""
    hazards = hazards or list(HAZARDS)
    today = today or date.today()
    if kind == "site":
        r = conn.execute(SITE_SQL, {"id": ident}).fetchone()
        if not r:
            return None
        window, names, partners = (r["start_at"], r["end_at"]), [r["name"]], []
    else:
        r = conn.execute(ZONE_SQL, {"id": int(ident)}).fetchone()
        if not r:
            return None
        window = (min(r["a_start"], r["b_start"]), max(r["a_end"], r["b_end"]))
        names, partners = [r["a_name"], r["b_name"]], sorted({r["a_org"], r["b_org"]})
    start, end = period_range(period, month, window, today)
    live = conn.execute(LIVE_SQL, {"hazards": hazards, "products": PRODUCTS[period], "start": datetime.combine(start, datetime.min.time(), timezone.utc),
                                    "end": datetime.combine(end, datetime.max.time(), timezone.utc), "footprint": r["footprint"]}).fetchall()
    fips = county_fips_for(conn, r["footprint"])
    hist_rows = conn.execute(COUNTIES_SQL, {"hazards": hazards, "fips": fips}).fetchall() if fips else []
    shares = month_shares(start, end)
    hist = history_days(hist_rows, shares)
    day_sets = live_days(live, start, end)
    now_days = {h: len(d) for h, d in day_sets.items()}
    out = []
    for h in hazards:
        items = [x for x in live if x["hazard"] == h]
        if not items and h not in hist:
            continue
        out.append({"hazard": h, "label": HAZARDS[h][0], "why": HAZARDS[h][1],
                    "affected_days": {"forecast": now_days.get(h, 0), **hist.get(h, {"low": 0, "high": 0})},
                    "leans": [x["label"] for x in items if x["product"] not in COUNTED][:3],
                    "live": [{"id": x["id"], "layer": x["layer"], "product": x["product"], "label": x["label"], "rank": x["rank"],
                              "from": x["period_start"].isoformat(), "to": x["period_end"].isoformat()} for x in items[:6]]})
    out.sort(key=lambda x: (-max(x["affected_days"]["forecast"], x["affected_days"]["high"]), x["hazard"]))
    total = {"forecast": len(set().union(*day_sets.values())) if day_sets else 0,
             "low": round(sum(v["low"] for v in hist.values()), 1), "high": round(sum(v["high"] for v in hist.values()), 1)}
    return {"kind": kind, "id": ident, "names": names, "partners": partners, "period": period, "start": start.isoformat(), "end": end.isoformat(),
            "days": (end - start).days + 1, "counties": len(fips), "hazards": out, "affected_days": total,
            "method": ("Forecast days count calendar days with an active NWS alert, an SPC, WPC or NHC outlook area, a wildfire or a quake over the works; "
                       "CPC leans (above or below normal) are listed, not counted. "
                       "History days scale ten years of NOAA Storm Events event-days per county to the months the period covers; "
                       "low and high are the least and most exposed county under the works. Estimates for assessment, not work orders.")}
