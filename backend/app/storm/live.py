import csv
import io
import json
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from shapely.geometry import shape

from app.storm import incidents, news
from app.storm.helene import DAMAGE

HEADERS = {"User-Agent": "opencrew/0.1 (hackathon)", "Accept": "application/geo+json"}  # NWS requires a User-Agent
ALERTS = "https://api.weather.gov/alerts/active?area=GA,SC"
SPC_TODAY = "https://www.spc.noaa.gov/climo/reports/today_filtered_{kind}.csv"
LSR = "https://mesonet.agron.iastate.edu/geojson/lsr.geojson"
POINTS = "https://api.weather.gov/points/{lat:.4f},{lon:.4f}"
GUST_LIMIT_MPH = 35  # crane lifts and line work stop above this
WORK = {"construction": "crane lift", "clearing": "tree clearing", "energization": "line work"}
ET = ZoneInfo("America/New_York")
KMH_TO_MPH = 0.621371
LSR_TYPES = DAMAGE | {"FLOOD", "FLASH FLOOD", "COASTAL FLOOD"}


def get(url, **kw):
    r = httpx.get(url, headers=HEADERS, timeout=30, follow_redirects=True, **kw)
    r.raise_for_status()
    return r


def parse_alerts(data, zone_geometry=lambda url: None, max_zones=40):
    """NWS active alerts -> storm_event rows; zone-based alerts borrow their first zone's outline."""
    rows, zones = [], 0
    for f in data.get("features", []):
        p = f["properties"]
        geom = f.get("geometry")
        if not geom and p.get("affectedZones") and zones < max_zones:
            zones += 1
            geom = zone_geometry(p["affectedZones"][0])
        ts = datetime.fromisoformat(p.get("sent") or p.get("effective"))
        wkt = shape(geom).wkt if geom else None
        rows.append((ts, "nws_alert", wkt, {"mode": "live", "label": p.get("event"), "phenomena": (p.get("event") or "")[:2].upper(),
                                            "expire": p.get("expires") or p.get("ends"), "severity": p.get("severity"),
                                            "places": (p.get("areaDesc") or "")[:200], "headline": p.get("headline"), "id": p.get("id")}))
    return rows


def parse_spc(text, kind, now):
    """SPC today file: times are UTC HHMM within the 12Z-to-12Z convective day."""
    day0 = (now - timedelta(hours=12)).replace(hour=12, minute=0, second=0, microsecond=0)
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        if r.get("State") not in ("GA", "SC") or not r.get("Time", "").isdigit():
            continue
        hhmm = int(r["Time"])
        ts = day0 + timedelta(days=1 if hhmm < 1200 else 0, hours=hhmm // 100 - 12, minutes=hhmm % 100)
        rows.append((ts, "spc_report", f"POINT({r['Lon']} {r['Lat']})", {"mode": "live", "kind": kind, "place": r["Location"],
                                                                         "county": r["County"], "state": r["State"], "comments": r["Comments"][:300]}))
    return rows


def parse_lsr(data):
    rows = []
    for f in data.get("features", []):
        p = f["properties"]
        if p["typetext"] not in LSR_TYPES:
            continue  # rain totals and hail are not grid damage
        ts = datetime.fromisoformat(p["valid"].replace("Z", "+00:00"))
        rows.append((ts, "lsr", f"POINT({p['lon']} {p['lat']})", {"mode": "live", "type": p["typetext"], "place": p["city"], "county": p["county"],
                                                                 "state": p["state"], "reported_by": p["source"], "remark": (p["remark"] or "")[:300]}))
    return rows


def zone_outline(url, cache={}):
    if url not in cache:
        try:
            cache[url] = get(url).json().get("geometry")
        except httpx.HTTPError:
            cache[url] = None
    return cache[url]


def store(conn, rows, kind):
    conn.execute("DELETE FROM storm_event WHERE kind = %s AND payload->>'mode' = 'live'", (kind,))
    with conn.cursor() as cur:
        cur.executemany("""INSERT INTO storm_event (ts, kind, geom, payload, confidence, verified)
                           VALUES (%s, %s, ST_GeogFromText(%s), %s, 1.0, TRUE)""", [(t, k, w, json.dumps(p)) for t, k, w, p in rows])
    return len(rows)


def poll(conn):
    """One live refresh: official feeds, latest news, incidents, and phase wind risks. Failures skip a source, never the poll."""
    now, out = datetime.now(timezone.utc), {}
    try:
        out["alerts"] = store(conn, parse_alerts(get(ALERTS).json(), zone_outline), "nws_alert")
    except httpx.HTTPError as e:
        out["alerts_error"] = str(e)[:120]
    try:
        spc = [row for kind in ("wind", "torn") for row in parse_spc(get(SPC_TODAY.format(kind=kind)).text, kind, now)]
        out["spc_reports"] = store(conn, spc, "spc_report")
    except httpx.HTTPError as e:
        out["spc_error"] = str(e)[:120]
    try:
        lsr = get(LSR, params={"sts": f"{now - timedelta(hours=24):%Y-%m-%dT%H:%MZ}", "ets": f"{now:%Y-%m-%dT%H:%MZ}", "states": "GA,SC"}).json()
        out["lsr_reports"] = store(conn, parse_lsr(lsr), "lsr")
    except httpx.HTTPError as e:
        out["lsr_error"] = str(e)[:120]
    items = []
    try:
        for row in news.latest_rows():
            items += news.items_for(row, news.fetch_article(row["url"]).get("text"))
    except httpx.HTTPError as e:
        out["news_error"] = str(e)[:120]
    out["news_items"] = len(items)
    out["incidents"] = dict(incidents.rebuild(conn, "live", items))
    out["phase_risks"] = phase_risks(conn)
    return out


# ---------- near-term wind risk ----------

ACTIVE_SQL = """
SELECT j.id, j.name, j.phase, j.endpoints, ST_Y(ST_PointOnSurface(j.geom::geometry)) AS lat, ST_X(ST_PointOnSurface(j.geom::geometry)) AS lon,
       lower(j.work_window) AS start_at, upper(j.work_window) AS end_at
FROM job j WHERE j.horizon = 'near' AND j.phase = ANY(%(phases)s) AND j.work_window && tstzrange(%(now)s, %(now)s + interval '7 days')
"""


def daily_gusts(grid):
    """NWS gridpoint windGust (km/h, ISO intervals) -> max mph per local day."""
    out = {}
    wg = grid.get("properties", {}).get("windGust", {})
    factor = KMH_TO_MPH if "km_h" in wg.get("uom", "km_h") else 1.0
    for v in wg.get("values", []):
        if v.get("value") is None:
            continue
        day = datetime.fromisoformat(v["validTime"].split("/")[0]).astimezone(ET).date()
        out[day] = max(out.get(day, 0), round(v["value"] * factor))
    return out


def site_name(job):
    ends = job["endpoints"] or []
    return ends[0].title() if ends else job["name"][:30]


def alert_text(gust, day, site, work):
    return f"Gusts of {gust} mph forecast {day:%A} at the {site} site; the {work} should move."


def phase_risks(conn, limit_mph=GUST_LIMIT_MPH, fetch=None, store=True):
    fetch = fetch or (lambda lat, lon: get(get(POINTS.format(lat=lat, lon=lon)).json()["properties"]["forecastGridData"]).json())
    now = datetime.now(timezone.utc)
    jobs = conn.execute(ACTIVE_SQL, {"phases": list(WORK), "now": now}).fetchall()
    grids, rows = {}, []
    for j in jobs:
        key = (round(j["lat"], 2), round(j["lon"], 2))  # nearby sites share one forecast grid
        if key not in grids:
            try:
                grids[key] = daily_gusts(fetch(j["lat"], j["lon"]))
                time.sleep(0.2)
            except (httpx.HTTPError, KeyError, ValueError):
                grids[key] = {}
        for day, gust in sorted(grids[key].items()):
            if gust >= limit_mph and j["start_at"].date() <= day <= j["end_at"].date():
                site, work = site_name(j), WORK[j["phase"]]
                rows.append((j["id"], site, day, gust, work, alert_text(gust, day, site, work)))
    summary = {"phases_checked": len(jobs), "sites": len(grids), "alerts": len(rows)}
    if not store:
        return {**summary, "rows": rows}
    conn.execute("DELETE FROM phase_risk")
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO phase_risk (job_id, site, day, gust_mph, work, alert) VALUES (%s, %s, %s, %s, %s, %s)", rows)
    return summary
