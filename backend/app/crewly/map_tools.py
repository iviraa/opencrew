"""Crewly abilities that drive the map and explain the numbers: views, project filters, timelines, forecasts, routes, methods."""
import json
import math
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from app.companies import companies, name, short
from app.config import ASSUMPTIONS, STOP_RULES
from app.crewly.tools import REGIONS
from app.hazards.config import HAZARDS
from app.hazards.exposure import PERIODS

TABS = ("overlaps", "hazards", "news")
TIERS = ("crossing", "land", "site", "crew")
KMH_TO_MPH, MM_TO_IN = 0.621371, 1 / 25.4
NWS_HEADERS = {"User-Agent": "opencrew/0.1 (hackathon)", "Accept": "application/geo+json"}
POINTS = "https://api.weather.gov/points/{lat:.4f},{lon:.4f}"
FORECAST_TTL_H = 3
FORECAST_SQL = "CREATE TABLE IF NOT EXISTS forecast_cache (key TEXT PRIMARY KEY, fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(), payload JSONB NOT NULL)"
FIELDS = ("windGust", "windSpeed", "probabilityOfThunder", "quantitativePrecipitation", "iceAccumulation", "snowfallAmount", "heatIndex", "temperature")


def _bind(ctx, fn):
    return lambda conn, **kw: fn(ctx, conn, **kw)


def _int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ---------- filters shared by map_view, filter_projects and timeline ----------

def find_company(q):
    from app.crewly.app_tools import find_company as _find
    return _find(q)


def project_filter_sql(f, alias="j"):
    """WHERE clauses for a project filter dict; values are bound, never pasted."""
    f = f or {}
    clauses, params = [], {}
    if f.get("kv") is not None:
        kv = [_int(x) for x in (f["kv"] if isinstance(f["kv"], list) else [f["kv"]])]
        kv = [x for x in kv if x]
        if kv:
            clauses.append(f"{alias}.voltage_kv = ANY(%(kv)s)"); params["kv"] = kv
    if f.get("type"):
        clauses.append(f"{alias}.job_type = %(type)s"); params["type"] = str(f["type"])
    if f.get("status"):
        clauses.append(f"{alias}.status ILIKE %(status)s"); params["status"] = f"%{f['status']}%"
    if f.get("state"):
        clauses.append(f"{alias}.state = %(state)s"); params["state"] = str(f["state"]).upper()[:2]
    if f.get("county"):
        clauses.append(f"EXISTS (SELECT 1 FROM unnest(coalesce({alias}.counties, '{{}}')) c WHERE c ILIKE %(county)s)"); params["county"] = f"%{f['county']}%"
    if f.get("name"):
        clauses.append(f"{alias}.name ILIKE %(name)s"); params["name"] = f"%{f['name']}%"
    years = f.get("years") or []
    lo, hi = (_int(years[0]) if years else None), (_int(years[1]) if len(years) > 1 else (_int(years[0]) if years else None))
    if lo and hi:
        lo, hi = min(lo, hi), max(lo, hi)
        clauses.append(f"{alias}.work_window && tstzrange(%(ylo)s::timestamptz, %(yhi)s::timestamptz)"); params["ylo"], params["yhi"] = f"{lo}-01-01", f"{hi}-12-31"
    return clauses, params


def overlap_ids_for(conn, company, f):
    """Our overlap ids whose own project matches the filter (and the partner, when one is named)."""
    from app.crewly.app_tools import mine_sql
    clauses, params = project_filter_sql(f, "mine")
    who = find_company(f["partner"]) if f.get("partner") else None
    if f.get("partner") and not who:
        raise ValueError(f"no utility called {f['partner']!r}")
    if f.get("tier") in TIERS:
        clauses.append("op.tier = %(tier)s"); params["tier"] = f["tier"]
    if who:
        clauses.append("%(who)s IN (ja.org_id, jb.org_id)"); params["who"] = who
    sql = (f"SELECT op.id FROM ({mine_sql(company)}) o JOIN opportunity op ON op.id = o.id JOIN job ja ON ja.id = op.job_a JOIN job jb ON jb.id = op.job_b "
           f"JOIN job mine ON mine.id = CASE WHEN ja.org_id = %(co)s THEN ja.id ELSE jb.id END" + (" WHERE " + " AND ".join(clauses) if clauses else "")
           + " ORDER BY op.score DESC")
    return [r["id"] for r in conn.execute(sql, {**params, "co": company}).fetchall()], who


def map_view(ctx, conn, tab="overlaps", period=None, month=None, hazards=None, filters=None, fit=None):
    tab = {"weather": "hazards"}.get(tab, tab)
    if tab not in TABS:
        return {"error": f"tab must be one of {', '.join(TABS)}"}, []
    action, said = {"type": "map_view", "tab": tab}, [f"switched to {tab}"]
    if tab == "hazards":
        if period and period not in PERIODS:
            return {"error": f"period must be one of {', '.join(PERIODS)}"}, []
        if period:
            action["period"] = period; said.append(f"period {period}")
        m = _int(month)
        if m and 1 <= m <= 12:
            action["month"] = m; action.setdefault("period", "month"); said.append(f"month {m}")
        hz = [h for h in (hazards or []) if h in HAZARDS]
        if hazards and not hz:
            return {"error": f"hazards must be some of {', '.join(HAZARDS)}"}, []
        if hz:
            action["hazards"] = hz; said.append("hazards " + ", ".join(hz))
    if filters:
        try:
            ids, who = overlap_ids_for(conn, ctx["company"], filters)
        except ValueError as e:
            return {"error": str(e)}, []
        action["ids"], action["filters"] = ids, {k: v for k, v in filters.items() if v not in (None, "", [])}
        if who:
            action["partner"] = who
        said.append(f"{len(ids)} overlaps match the filter")
    if fit:
        if isinstance(fit, list) and len(fit) == 4 and all(isinstance(x, (int, float)) for x in fit):
            action["fit"] = {"bbox": fit}
        elif isinstance(fit, str) and (fit in ("ours", "overlaps") or re.fullmatch(r"overlap:#?\d+", fit)):
            action["fit"] = {"to": fit.replace("#", "")}
        else:
            return {"error": "fit must be 'ours', 'overlaps', 'overlap:18' or a bbox [west, south, east, north]"}, []
        said.append("map fitted")
    return {"did": "; ".join(said), "view": action}, [action]


PROJECT_SQL = """
SELECT j.id, j.name, j.org_id, j.job_type, j.voltage_kv, j.status, j.state, j.counties, j.in_service, j.cost_usd, j.length_mi,
       lower(j.work_window) AS start_at, upper(j.work_window) AS end_at, ST_AsGeoJSON(ST_Centroid(j.geom::geometry), 5)::json AS center
FROM job j WHERE j.horizon = 'long' AND j.org_id = %(co)s
"""


def _project_rows(conn, org, f, limit):
    clauses, params = project_filter_sql(f)
    sql = PROJECT_SQL + ("".join(" AND " + c for c in clauses)) + " ORDER BY lower(j.work_window) LIMIT %(lim)s"
    return conn.execute(sql, {**params, "co": org, "lim": max(1, min(_int(limit, 200), 500))}).fetchall()


def _row(r):
    return {"id": r["id"], "name": r["name"], "kv": r["voltage_kv"], "type": r["job_type"], "status": r["status"], "state": r["state"],
            "county": (r["counties"] or [None])[0], "start": str(r["start_at"])[:10], "end": str(r["end_at"])[:10], "in_service": str(r["in_service"] or "")[:10],
            "cost_usd": r["cost_usd"] and round(float(r["cost_usd"])), "miles": r["length_mi"], "center": (r["center"] or {}).get("coordinates")}


def filter_projects(ctx, conn, filters=None, limit=200):
    rows = [_row(r) for r in _project_rows(conn, ctx["company"], filters or {}, limit)]
    f = {k: v for k, v in (filters or {}).items() if v not in (None, "", [])}
    title = "Our projects" + (": " + ", ".join(f"{k} {v}" for k, v in f.items()) if f else "")
    return ({"count": len(rows), "filters": f, "projects": [{k: v for k, v in r.items() if k != "center"} for r in rows[:15]],
             "note": f"{len(rows)} shown on the map and in the card" if len(rows) > 15 else None},
            [{"type": "projects", "projects": {"title": title, "filters": f, "rows": rows}}])


def timeline(ctx, conn, years=None, filters=None, partner=None):
    lo = _int((years or [None])[0], datetime.now().year)
    hi = _int((years or [None, None])[1] if len(years or []) > 1 else None, lo + 2)
    lo, hi = min(lo, hi), max(lo, hi)
    f = {**(filters or {}), "years": [lo, hi]}
    orgs = [ctx["company"]]
    if partner:
        who = find_company(partner)
        if not who:
            return {"error": f"no utility called {partner!r}", "utilities": sorted(c["name"] for c in companies().values())}, []
        orgs.append(who)
    rows = []
    for org in orgs:
        for r in _project_rows(conn, org, f, 200):
            rows.append({**_row(r), "org": org, "org_short": short(org), "mine": org == ctx["company"]})
    rows.sort(key=lambda r: (not r["mine"], r["start"]))
    tl = {"title": f"Projects on the calendar, {lo} to {hi}" + (f", ours and {name(orgs[1])}'s" if len(orgs) > 1 else ""), "years": [lo, hi],
          "rows": [{k: v for k, v in r.items() if k != "center"} for r in rows]}
    return ({"count": len(rows), "years": [lo, hi], "by_company": {short(o): sum(r["org"] == o for r in rows) for o in orgs},
             "first": [{"name": r["name"], "start": r["start"], "end": r["end"]} for r in rows[:8]]}, [{"type": "timeline", "timeline": tl}])


# ---------- places ----------

def haversine_km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[1], a[0], b[1], b[0]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def resolve_point(conn, company, ref):
    """A (lon, lat, label) for a project id, an overlap (#18, '#18 ours', '#18 theirs'), a region name or 'lon,lat'."""
    s = str(ref or "").strip()
    m = re.fullmatch(r"#?(\d+)(?:\s*(ours|theirs|mine|partner))?", s, re.I)
    if m:
        op = conn.execute("""SELECT op.id, op.job_a, op.job_b, op.meet_lon, op.meet_lat, ja.org_id AS a_org, ja.name AS a_name, jb.name AS b_name,
                                    ST_AsGeoJSON(ST_Centroid(ja.geom::geometry), 5)::json AS ca, ST_AsGeoJSON(ST_Centroid(jb.geom::geometry), 5)::json AS cb,
                                    ST_AsGeoJSON(ST_Centroid(op.link::geometry), 5)::json AS cl
                             FROM opportunity op JOIN job ja ON ja.id = op.job_a JOIN job jb ON jb.id = op.job_b WHERE op.id = %s AND op.horizon = 'long'
                               AND %s IN (ja.org_id, jb.org_id)""", (int(m.group(1)), company)).fetchone()
        if not op:
            raise ValueError(f"#{m.group(1)} is not one of our overlaps")
        side = (m.group(2) or "").lower()
        ours_is_a = op["a_org"] == company
        if side in ("ours", "mine"):
            c = op["ca"] if ours_is_a else op["cb"]
            return c["coordinates"][0], c["coordinates"][1], op["a_name"] if ours_is_a else op["b_name"]
        if side in ("theirs", "partner"):
            c = op["cb"] if ours_is_a else op["ca"]
            return c["coordinates"][0], c["coordinates"][1], op["b_name"] if ours_is_a else op["a_name"]
        if op["meet_lon"] is not None:
            return float(op["meet_lon"]), float(op["meet_lat"]), f"meet point of overlap #{op['id']}"
        return op["cl"]["coordinates"][0], op["cl"]["coordinates"][1], f"midpoint of overlap #{op['id']}"
    if s.lower() in REGIONS:
        x0, y0, x1, y1 = REGIONS[s.lower()]
        return (x0 + x1) / 2, (y0 + y1) / 2, s.title()
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)", s)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        lon, lat = (a, b) if abs(a) > 90 or abs(b) <= 90 and a < 0 else (b, a)  # "lon,lat" or "lat,lon", whichever is plausible
        return lon, lat, f"{lat:.3f}, {lon:.3f}"
    j = conn.execute("SELECT id, name, org_id, ST_AsGeoJSON(ST_Centroid(geom::geometry), 5)::json AS c FROM job WHERE id = %s", (s,)).fetchone()
    if j:
        return j["c"]["coordinates"][0], j["c"]["coordinates"][1], j["name"]
    j = conn.execute("SELECT id, name, ST_AsGeoJSON(ST_Centroid(geom::geometry), 5)::json AS c FROM job WHERE horizon = 'long' AND org_id = %s AND name ILIKE %s "
                     "ORDER BY length(name) LIMIT 1", (company, f"%{s}%")).fetchone()
    if j:
        return j["c"]["coordinates"][0], j["c"]["coordinates"][1], j["name"]
    raise ValueError(f"I can't place {s!r}: give a project id, an overlap like #18 (ours/theirs), a region ({', '.join(REGIONS)}) or lon,lat")


# ---------- forecast ----------

def fetch_grid(lon, lat):
    """NWS point metadata and its 7-day gridpoint data."""
    p = httpx.get(POINTS.format(lat=lat, lon=lon), headers=NWS_HEADERS, timeout=30, follow_redirects=True)
    p.raise_for_status()
    props = p.json()["properties"]
    g = httpx.get(props["forecastGridData"], headers=NWS_HEADERS, timeout=30, follow_redirects=True)
    g.raise_for_status()
    gp = g.json().get("properties", {})
    return {"tz": props.get("timeZone") or "America/New_York", "place": (props.get("relativeLocation") or {}).get("properties", {}),
            **{k: gp.get(k) for k in FIELDS}}


def parse_days(grid, days=7, today=None):
    """Per local day: worst gust and wind (mph), thunder chance, rain, ice and snow (in), heat index and temperatures (F)."""
    tz = ZoneInfo(grid.get("tz") or "America/New_York")
    out = {}

    def scan(field, fn):
        f = grid.get(field) or {}
        uom = f.get("uom", "")
        for v in f.get("values", []):
            if v.get("value") is None:
                continue
            day = datetime.fromisoformat(v["validTime"].split("/")[0]).astimezone(tz).date()
            fn(out.setdefault(day, {}), float(v["value"]), uom)

    mph = lambda val, uom: val * KMH_TO_MPH if "km_h" in uom else val  # noqa: E731
    f_deg = lambda val, uom: val * 9 / 5 + 32 if "degC" in uom else val  # noqa: E731
    inch = lambda val, uom: val * MM_TO_IN if "mm" in uom else val  # noqa: E731
    scan("windGust", lambda d, v, u: d.__setitem__("gust_mph", max(d.get("gust_mph", 0), round(mph(v, u)))))
    scan("windSpeed", lambda d, v, u: d.__setitem__("wind_mph", max(d.get("wind_mph", 0), round(mph(v, u)))))
    scan("probabilityOfThunder", lambda d, v, u: d.__setitem__("thunder_pct", max(d.get("thunder_pct", 0), round(v))))
    scan("quantitativePrecipitation", lambda d, v, u: d.__setitem__("rain_in", round(d.get("rain_in", 0) + inch(v, u), 2)))
    scan("iceAccumulation", lambda d, v, u: d.__setitem__("ice_in", round(d.get("ice_in", 0) + inch(v, u), 2)))
    scan("snowfallAmount", lambda d, v, u: d.__setitem__("snow_in", round(d.get("snow_in", 0) + inch(v, u), 1)))
    scan("heatIndex", lambda d, v, u: d.__setitem__("heat_index_f", max(d.get("heat_index_f", -99), round(f_deg(v, u)))))
    scan("temperature", lambda d, v, u: (d.__setitem__("high_f", max(d.get("high_f", -99), round(f_deg(v, u)))), d.__setitem__("low_f", min(d.get("low_f", 199), round(f_deg(v, u))))))
    start = today or datetime.now(tz).date()
    rows = []
    for i in range(days):
        day = start + timedelta(days=i)
        d = out.get(day, {})
        notes = []
        crane, aerial = STOP_RULES.get("crane_gust_mph", {}), STOP_RULES.get("aerial_lift_wind_mph", {})
        if d.get("gust_mph", 0) >= float(crane.get("threshold", 30) if isinstance(crane.get("threshold"), (int, float)) else 30):
            notes.append(f"gusts to {d['gust_mph']} mph, above the crane wind limit")
        elif d.get("gust_mph", 0) >= float(aerial.get("threshold", 28) if isinstance(aerial.get("threshold"), (int, float)) else 28):
            notes.append(f"gusts to {d['gust_mph']} mph, near the aerial-lift limit")
        if d.get("thunder_pct", 0) >= 40:
            notes.append(f"{d['thunder_pct']}% chance of thunder")
        if d.get("ice_in", 0) > 0:
            notes.append(f"{d['ice_in']} in of ice")
        if d.get("snow_in", 0) >= 1:
            notes.append(f"{d['snow_in']} in of snow")
        heat = STOP_RULES.get("heat_index_caution_f", {}).get("threshold", 91)
        if d.get("heat_index_f", -99) >= float(heat if isinstance(heat, (int, float)) else 91):
            notes.append(f"heat index {d['heat_index_f']} F")
        if d.get("rain_in", 0) >= 1:
            notes.append(f"{d['rain_in']} in of rain")
        rows.append({"date": day.isoformat(), "dow": day.strftime("%a"), **{k: d.get(k) for k in ("gust_mph", "wind_mph", "thunder_pct", "rain_in", "ice_in", "snow_in", "heat_index_f", "high_f", "low_f")},
                     "notes": notes, "quiet": not notes and bool(d)})
    return rows


def site_forecast(ctx, conn, site, fetch=None):
    try:
        lon, lat, label = resolve_point(conn, ctx["company"], site)
    except ValueError as e:
        return {"error": str(e)}, []
    key = f"{round(lat / 0.05) * 0.05:.2f},{round(lon / 0.05) * 0.05:.2f}"  # nearby sites share one grid cell
    conn.execute(FORECAST_SQL)
    hit = conn.execute("SELECT payload, fetched_at FROM forecast_cache WHERE key = %s", (key,)).fetchone()
    if hit and datetime.now(timezone.utc) - hit["fetched_at"] < timedelta(hours=FORECAST_TTL_H):
        grid, fetched = hit["payload"], hit["fetched_at"].isoformat()
    else:
        try:
            grid = (fetch or fetch_grid)(lon, lat)
        except (httpx.HTTPError, KeyError, ValueError) as e:
            return {"error": f"the weather service did not answer for {label} ({type(e).__name__})"}, []
        conn.execute("INSERT INTO forecast_cache (key, payload) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET payload = EXCLUDED.payload, fetched_at = now()",
                     (key, json.dumps(grid)))
        fetched = datetime.now(timezone.utc).isoformat()
    days = parse_days(grid)
    fc = {"site": label, "point": [round(lon, 4), round(lat, 4)], "near": " ".join(str(v) for v in ((grid.get("place") or {}).get("city"), (grid.get("place") or {}).get("state")) if v),
          "days": days, "fetched_at": fetched, "source": "NOAA National Weather Service gridpoint forecast", "sources": [{"title": "NWS API forecast grid", "url": "https://api.weather.gov"}]}
    busy = [d for d in days if d["notes"]]
    brief = {"site": label, "days": [{"date": d["date"], "dow": d["dow"], "gust_mph": d["gust_mph"], "thunder_pct": d["thunder_pct"], "heat_index_f": d["heat_index_f"], "notes": d["notes"]} for d in days],
             "summary": f"{len(busy)} of {len(days)} days carry a work-affecting note" if busy else "a quiet week: nothing near the wind, lightning, ice or heat thresholds"}
    return brief, [{"type": "forecast", "forecast": fc}]


# ---------- routes ----------

def route_between(ctx, conn, a, b, drive=None):
    from app.geo.drive import OSRM, Drive
    try:
        p1, p2 = resolve_point(conn, ctx["company"], a), resolve_point(conn, ctx["company"], b)
    except ValueError as e:
        return {"error": str(e)}, []
    road = drive or Drive()
    got = road.between((p1[0], p1[1]), (p2[0], p2[1]))
    key = "geom:" + ";".join(f"{p[0]:.4f},{p[1]:.4f}" for p in (p1, p2))
    if key not in road.cache:
        data = road._get(f"{OSRM}/route/v1/driving/{p1[0]:.5f},{p1[1]:.5f};{p2[0]:.5f},{p2[1]:.5f}", {"overview": "simplified", "geometries": "geojson"})
        if data and data.get("routes"):
            road.cache[key] = data["routes"][0]["geometry"]
    geom = road.cache.get(key) or {"type": "LineString", "coordinates": [[p1[0], p1[1]], [p2[0], p2[1]]]}
    road.save()
    straight = round(haversine_km(p1, p2), 1)
    out = {"from": p1[2], "to": p2[2], "straight_km": straight, "straight_mi": round(straight / 1.609344, 1),
           "road_km": got and got["km"], "road_mi": got and round(got["km"] / 1.609344, 1), "drive_min": got and got["min"],
           "note": None if got else "the routing service did not answer; straight-line distance only", "source": "OSRM public router"}
    return out, [{"type": "route", "route": {**out, "geometry": geom, "a": [p1[0], p1[1]], "b": [p2[0], p2[1]]}}]


# ---------- explanations ----------

def _assumption(key):
    a = ASSUMPTIONS.get(key)
    if not a:
        return None
    return {"key": key, "label": a.get("label", key), "low": a.get("low"), "high": a.get("high"), "unit": a.get("unit"), "verified": bool(a.get("verified")),
            "source": a.get("source"), "url": a.get("url"), "page": a.get("page"), "note": (a.get("note") or "")[:220]}


def explain_numbers(ctx, conn, what, opportunity_id):
    from app.queries import OPP_SQL
    opp = _int(str(opportunity_id).lstrip("#"))
    op = conn.execute(OPP_SQL + " WHERE op.id = %s", (opp,)).fetchone() if opp else None
    if not op or ctx["company"] not in (op["a_org"], op["b_org"]):
        return {"error": f"#{opportunity_id} is not one of our overlaps"}, []
    what = (what or "savings").lower()
    ex = {"title": "", "formula": "", "inputs": [], "steps": [], "sources": [], "what": what, "opportunity_id": opp}
    if what == "savings":
        from app.engine.cost import savings_for
        s = savings_for(conn, op)
        ex["title"] = f"Where the savings on #{opp} come from"
        ex["formula"] = ("Each line is one cost the pair would otherwise pay twice: quantity x the cited unit price, scaled by how much of the build "
                         "windows coincide (same_time) and how close the sites are by road (drive). Low and high use the low and high unit prices.")
        ex["steps"] = [f"{ln['name']}: {ln['qty']}; basis {ln['basis']}; {_usd(ln['low'])} to {_usd(ln['high'])}" for ln in s.get("lines", [])]
        f = s.get("factors") or {}
        ex["inputs"] = [{"label": "Same-time factor", "value": f.get("same_time"), "unit": "share of the shorter window"},
                        {"label": "Drive factor", "value": f.get("drive"), "unit": "1 within 45 min by road, lower beyond"},
                        {"label": "Project scale", "value": f.get("project_scale"), "unit": "vs MISO's typical project"}]
        keys = ("mobilization_usd", "yard_usd", "outage_usd", "per_diem_usd_day", "escalation_pct_yr", "lineworker_hourly_usd", "labor_burden_factor", "crew_day_usd")
        ex["assumptions"] = [a for a in (_assumption(k) for k in keys) if a]
        ex["result"] = {"low": s["low"], "high": s["high"], "unit": "USD"}
    elif what == "weather_cost":
        from app.hazards import cost
        got = cost.for_zone(conn, opp, "month")
        if not got:
            return {"error": "no weather cost for this overlap"}, []
        c, coord = got
        ex["title"] = f"How the weather cost on #{opp} is built"
        ex["formula"] = c["method"]
        ex["steps"] = [f"{site['name'][:40]}: {i['label']} {i['days']['low']} to {i['days']['high']} days x {_usd(i['per_day']['low'])} to {_usd(i['per_day']['high'])} per day"
                       f"{' + storm-rate premium' if i['premium']['high'] else ''} = {_usd(i['total']['low'])} to {_usd(i['total']['high'])}" for site in c["sites"] for i in site["items"]]
        ex["assumptions"] = [a for a in (_assumption(k) for k in c["assumptions"]) if a]
        ex["inputs"] = [{"label": "Affected days", "value": "from ten years of NOAA Storm Events per county under the works", "unit": ""},
                        {"label": "Shared standby days", "value": coord["items"][0]["shared_days"] if coord.get("items") else None, "unit": "days both sites are affected"}]
        ex["result"] = {"low": c["total"]["low"], "high": c["total"]["high"], "unit": "USD"}
        ex["sources"] = [{"title": "NOAA NCEI Storm Events Database", "url": "https://www.ncei.noaa.gov/stormevents/"}]
    elif what == "feasibility":
        from app.feasibility.assess import assess
        a = assess(conn, opp, ctx["company"])
        if not a:
            return {"error": "no assessment for this overlap"}, []
        ex["title"] = f"How #{opp} scored {a['verdict']} ({a['score']:.2f})"
        ex["formula"] = ("Seven factors each get a score from 0 to 1 with evidence; the overall score is their weighted mean. Any factor that is unlikely "
                         "caps the verdict at possible, two unlikely factors make it unlikely.")
        ex["steps"] = [f"{f['label']}: {f['verdict']} ({f['score']})" + (f"; {f['evidence'][0]}" if f.get("evidence") else "") for f in a["factors"]]
        ex["sources"] = [{"title": s, "url": None} for f in a["factors"] for s in f.get("sources", [])][:12]
        ex["result"] = {"value": a["score"], "verdict": a["verdict"]}
    elif what == "exposure":
        from app.hazards.exposure import assess as ex_assess
        e = ex_assess(conn, "zone", str(opp), "month")
        if not e:
            return {"error": "no exposure for this overlap"}, []
        ex["title"] = f"How the hazard exposure on #{opp} is counted"
        ex["formula"] = e["method"]
        ex["steps"] = [f"{h['label']}: {h['affected_days'].get('low')} to {h['affected_days'].get('high')} days; {h['why']}" for h in e["hazards"]]
        ex["sources"] = [{"title": "NOAA NCEI Storm Events Database", "url": "https://www.ncei.noaa.gov/stormevents/"}, {"title": "FEMA National Risk Index", "url": "https://hazards.fema.gov/nri/"}]
        ex["result"] = {"low": e["affected_days"]["low"], "high": e["affected_days"]["high"], "unit": "days"}
    else:
        return {"error": "what must be savings, weather_cost, feasibility or exposure"}, []
    for a in ex.get("assumptions", []):
        if a.get("url") and not any(s.get("url") == a["url"] for s in ex["sources"]):
            ex["sources"].append({"title": a["source"], "url": a["url"]})
    brief = {k: v for k, v in ex.items() if k not in ("inputs", "assumptions")}
    brief["steps"] = brief["steps"][:8]
    return brief, [{"type": "explain", "explain": ex}]


def _usd(n):
    n = float(n or 0)
    return f"${n / 1e6:.1f}M" if n >= 1e6 else f"${round(n / 1e3)}k" if n >= 1e3 else f"${round(n)}"


METHODS = {
    "overlaps": ("How overlaps are found", "Every pair of projects from different utilities within 25 miles is a candidate. The closest distance between the works sets "
                 "the tier (crossing, same land under 1 mile, same site under 5 miles, crew range under 25 miles); the road drive time between the sites comes from "
                 "OSRM and pairs over 45 minutes apart lose crew and yard sharing. Score = tier weight x share of the shorter build window that coincides x (1 + hurricane "
                 "risk + social vulnerability at the midpoint), halved when the drive is too long.",
                 [{"title": "FEMA National Risk Index", "url": "https://hazards.fema.gov/nri/"}, {"title": "OSRM routing", "url": "https://project-osrm.org"}]),
    "savings": ("How savings are estimated", "Each overlap lists the costs a pair would otherwise pay twice (hauling and setting up once, one yard, one outage window, "
                "fewer crew days and per diems, months of escalation avoided), priced with cited unit costs from MISO's cost guides, BLS wages and GSA per diems, "
                "then scaled by how much of the windows coincide and how close the sites are by road. Low and high come from the low and high unit prices.",
                [{"title": "MISO Transmission Cost Estimation Guide", "url": ASSUMPTIONS.get("mobilization_usd", {}).get("url")}, {"title": "BLS Occupational Employment and Wages", "url": ASSUMPTIONS.get("lineworker_hourly_usd", {}).get("url")}]),
    "hazard_days": ("How weather-affected days are counted", "Ten years of NOAA Storm Events are aggregated per county and month into event-days per hazard (wind, storms, "
                    "tornado, winter, heat, flood, tropical, wildfire, hail). For a site the counties under a 2 km buffer around the works set a low (least exposed) and "
                    "high (most exposed) count, scaled to the months a period covers. For the next 7 days, active NWS alerts and SPC, WPC and NHC outlooks over the works "
                    "count as forecast days; CPC leans are listed but never counted.", [{"title": "NOAA NCEI Storm Events Database", "url": "https://www.ncei.noaa.gov/stormevents/"}]),
    "weather_cost": ("How weather cost is priced", "Affected days x the cheaper of holding the crew and equipment on standby (crew day rate plus the standby rates of the "
                     "equipment the current phase uses) or demobilizing and returning, plus storm-rate labor after tropical, winter or tornado days. Coordinating "
                     "lets one standby crew and yard cover both sites on the days both are affected.", [{"title": "FEMA Schedule of Equipment Rates", "url": ASSUMPTIONS.get("crane_standby_usd_day", {}).get("url")}]),
    "feasibility": ("How feasibility is judged", "Seven factors: location (tier, drive, floodplain, state lines), timing (window overlap, phase alignment, slack, "
                    "history of slips, shift options), cost (savings vs each budget), forecast and season, news, the counterparty's record and our notes, and "
                    "future considerations (later work at the same stations, cross-state approvals). Each has a verdict and evidence; an unlikely factor caps the "
                    "overall at possible. It is an assessment of the pair, never an instruction.", []),
    "storm_scenario": ("How a storm scenario is evaluated", "A synthetic tropical event: Saffir-Simpson winds for the category, typical 34, 50 and 64 kt wind radii, a "
                       "straight track decaying inland. Sites active on the date inside each band get affected days (passage plus a recovery allowance by band) priced "
                       "with the weather cost model; partner sites within 45 minutes outside the field are counted as capacity available nearby.",
                       [{"title": "NHC Saffir-Simpson Hurricane Wind Scale", "url": "https://www.nhc.noaa.gov/aboutsshws.php"}]),
    "replay": ("How a history replay works", "Instead of ten-year averages, each year's real county event-days by month are applied to the same build windows, giving a "
               "per-year spread (best and worst year, p10, p50, p90) of affected days and cost.", [{"title": "NOAA NCEI Storm Events Database", "url": "https://www.ncei.noaa.gov/stormevents/"}]),
    "sensitivity": ("How sensitivity is ranked", "Each assumption is moved 25% below and above its value on its own (plus drive time or a 3-month shift) and the "
                    "swing in the chosen metric is ranked, tornado-style.", []),
    "plan_ranking": ("How the plan ranks pairs", "Candidates are our overlaps with savings and no approved request. Each gets a feasibility score, a target window (the "
                     "cheapest run of months inside both build windows by weather history) and an action (send, follow up, wait). Ranked by feasibility x savings, capped "
                     "per horizon, sequenced by target start, with conflicts flagged when two pairs need the same project in the same months.", []),
}


def explain_method(ctx, conn, topic):
    t = (topic or "").lower().replace(" ", "_")
    aliases = {"overlap": "overlaps", "cost": "savings", "saving": "savings", "weather": "hazard_days", "hazards": "hazard_days", "exposure": "hazard_days",
               "storm": "storm_scenario", "hurricane": "storm_scenario", "history": "replay", "plan": "plan_ranking", "planning": "plan_ranking", "feasible": "feasibility"}
    t = aliases.get(t, t)
    if t not in METHODS:
        return {"error": f"topic must be one of {', '.join(METHODS)}"}, []
    title, text, sources = METHODS[t]
    ex = {"title": title, "formula": text, "steps": [], "inputs": [], "sources": [s for s in sources if s.get("url")], "what": t}
    return {"title": title, "method": text, "sources": ex["sources"]}, [{"type": "explain", "explain": ex}]


# ---------- registry ----------

def map_tools(ctx):
    filt = {"type": "object", "properties": {
        "partner": {"type": "string"}, "tier": {"type": "string", "enum": list(TIERS)}, "kv": {"type": "integer"}, "type": {"type": "string"},
        "status": {"type": "string"}, "county": {"type": "string"}, "state": {"type": "string"}, "name": {"type": "string"},
        "years": {"type": "array", "items": {"type": "integer"}}}}
    return {
        "map_view": (_bind(ctx, map_view), "Drive the map: switch tab (overlaps, hazards, news), set the hazards period and month and which hazard layers show, "
                     "narrow the overlaps list and map with filters (partner, tier, kv, type, status, county, state, years), and fit the map to ours, "
                     "overlaps, one overlap or a bbox.", {
            "tab": {"type": "string", "enum": list(TABS)}, "period": {"type": "string", "enum": list(PERIODS)}, "month": {"type": "integer"},
            "hazards": {"type": "array", "items": {"type": "string", "enum": list(HAZARDS)}}, "filters": filt,
            "fit": {"type": "string", "description": "ours, overlaps, or overlap:18"}}, ["tab"]),
        "filter_projects": (_bind(ctx, filter_projects), "Find and highlight our own projects by kv, type, status, county, state, name or build years; they light "
                            "up on the map and list in a card.", {"filters": filt, "limit": {"type": "integer"}}, []),
        "timeline": (_bind(ctx, timeline), "Our projects (and optionally a partner utility's) on a month timeline for a year range.", {
            "years": {"type": "array", "items": {"type": "integer"}}, "filters": filt, "partner": {"type": "string"}}, []),
        "site_forecast": (_bind(ctx, site_forecast), "The NWS 7-day forecast at a site (project id), an overlap's meet point (#18) or one side (#18 ours), or a "
                          "region: daily gusts, thunder chance, rain, ice, snow and heat index, with notes where a value crosses a work-affecting threshold. "
                          "Assessment only.", {"site": {"type": "string"}}, ["site"]),
        "route_between": (_bind(ctx, route_between), "Road distance and drive time between two places (project ids, #18 ours / #18 theirs, regions or lon,lat), "
                          "drawn on the map.", {"a": {"type": "string"}, "b": {"type": "string"}}, ["a", "b"]),
        "explain_numbers": (_bind(ctx, explain_numbers), "Where a figure for one overlap comes from: the formula in words, each line with its basis, the "
                            "assumptions used with their sources.", {"what": {"type": "string", "enum": ["savings", "weather_cost", "feasibility", "exposure"]},
                                                                      "opportunity_id": {"type": "integer"}}, ["what", "opportunity_id"]),
        "explain_method": (_bind(ctx, explain_method), "How a model works, in a few sentences with sources: " + ", ".join(METHODS) + ".", {
            "topic": {"type": "string", "enum": list(METHODS)}}, ["topic"]),
    }


PROMPT = """
- Map words ("show the map", "switch to hazards", "August floods", "only 230 kV", "just Duke", "zoom to #18", "fit to our projects") mean map_view;
  "highlight / find our projects that ..." means filter_projects; "timeline / calendar of our projects" means timeline.
- "Forecast at ...", "weather this week at ..." means site_forecast; report it as an assessment (gusts, thunder chance, heat index) and never as
  an instruction about who works. "How far / drive time from A to B" means route_between.
- "Where does this number come from", "how is X calculated", "explain the savings on #18" means explain_numbers; "how does crewly judge / rank /
  count ..." means explain_method. Quote the tool's formula and sources; add no figures of your own."""
