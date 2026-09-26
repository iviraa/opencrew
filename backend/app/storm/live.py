import csv
import io
import json
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from shapely.geometry import shape

from app.storm import incidents, news, replay
from app.storm.helene import DAMAGE, LANDFALL, REPLAY

HEADERS = {"User-Agent": "opencrew/0.1 (hackathon)", "Accept": "application/geo+json"}  # NWS requires a User-Agent
ALERTS = "https://api.weather.gov/alerts/active"  # ?area= is the states our utilities work in, from the org table
DEFAULT_STATES = ("GA", "SC")
ALERT_CAP = 2000  # features kept per poll across pages
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


def utility_states(conn):
    """Every state a utility on crewly works in; the two demo states when the table is empty."""
    rows = conn.execute("SELECT DISTINCT state FROM org WHERE kind = 'utility' AND state IS NOT NULL ORDER BY state").fetchall()
    return tuple(r["state"] for r in rows) or DEFAULT_STATES


def fetch_alerts(states):
    """Active NWS alerts for these states, following the feed's pagination up to a cap."""
    feats, url, params = [], ALERTS, {"area": ",".join(states)}
    while url and len(feats) < ALERT_CAP:
        data = get(url, params=params).json()
        feats += data.get("features", [])
        url, params = data.get("pagination", {}).get("next"), None
    return {"features": feats[:ALERT_CAP]}


def parse_spc(text, kind, now, states=DEFAULT_STATES):
    """SPC today file: times are UTC HHMM within the 12Z-to-12Z convective day."""
    day0 = (now - timedelta(hours=12)).replace(hour=12, minute=0, second=0, microsecond=0)
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        if r.get("State") not in states or not r.get("Time", "").isdigit():
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


HISTORY_DAYS = 30  # live history kept for the time bar


def store(conn, rows, kind, since=None):
    """Append live rows, replacing only what this poll covers, so older history stays scrubbable."""
    ids = [p["id"] for *_, p in rows if p.get("id")]
    if ids:
        conn.execute("DELETE FROM storm_event WHERE kind = %s AND payload->>'mode' = 'live' AND payload->>'id' = ANY(%s)", (kind, ids))
    if since:
        conn.execute("DELETE FROM storm_event WHERE kind = %s AND payload->>'mode' = 'live' AND ts >= %s", (kind, since))
    conn.execute("DELETE FROM storm_event WHERE kind = %s AND payload->>'mode' = 'live' AND ts < now() - make_interval(days => %s)",
                 (kind, HISTORY_DAYS))
    with conn.cursor() as cur:
        cur.executemany("""INSERT INTO storm_event (ts, kind, geom, payload, confidence, verified)
                           VALUES (%s, %s, ST_GeogFromText(%s), %s, 1.0, TRUE)""", [(t, k, w, json.dumps(p)) for t, k, w, p in rows])
    return len(rows)


def poll(conn):
    """One live refresh: official feeds, latest news, incidents, and phase wind risks. Failures skip a source, never the poll."""
    now, out = datetime.now(timezone.utc), {}
    states = utility_states(conn)
    try:
        out["alerts"] = store(conn, parse_alerts(fetch_alerts(states), zone_outline), "nws_alert")
    except httpx.HTTPError as e:
        out["alerts_error"] = str(e)[:120]
    try:
        spc = [row for kind in ("wind", "torn") for row in parse_spc(get(SPC_TODAY.format(kind=kind)).text, kind, now, states)]
        out["spc_reports"] = store(conn, spc, "spc_report", since=now - timedelta(hours=24))
    except httpx.HTTPError as e:
        out["spc_error"] = str(e)[:120]
    try:
        lsr = get(LSR, params={"sts": f"{now - timedelta(hours=24):%Y-%m-%dT%H:%MZ}", "ets": f"{now:%Y-%m-%dT%H:%MZ}", "states": ",".join(states)}).json()
        out["lsr_reports"] = store(conn, parse_lsr(lsr), "lsr", since=now - timedelta(hours=24))
    except httpx.HTTPError as e:
        out["lsr_error"] = str(e)[:120]
    items = []
    try:
        for row in news.latest_rows():
            items += news.items_for(row, news.fetch_article(row["url"]).get("text"))
    except httpx.HTTPError as e:
        out["news_error"] = str(e)[:120]
    out["news_items"] = store_news(conn, items)
    out["incidents"] = dict(incidents.rebuild(conn, "live", news_history(conn)))  # rebuilt from the whole kept history
    out["phase_risks"] = phase_risks(conn)
    return out


def store_news(conn, items):
    """Keep each structured news item so incidents can be rebuilt for any past time."""
    by_url = {}
    for it in items:
        by_url.setdefault(it["sources"][0]["url"], []).append(it)
    for url, group in by_url.items():
        conn.execute("DELETE FROM storm_event WHERE kind = 'news_item' AND payload->>'url' = %s", (url,))
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO storm_event (ts, kind, geom, payload) VALUES (%s, 'news_item', ST_GeogFromText(%s), %s)",
                            [(it["ts"], f"POINT({it['lon']} {it['lat']})", json.dumps({"mode": "live", "url": url, "item": it}, default=str)) for it in group])
    return len(items)


def news_history(conn, days=HISTORY_DAYS):
    rows = conn.execute("""SELECT payload->'item' AS item FROM storm_event WHERE kind = 'news_item' AND payload->>'mode' = 'live'
                           AND ts >= now() - make_interval(days => %s)""", (days,)).fetchall()
    out = []
    for r in rows:
        it = r["item"]
        it["ts"] = datetime.fromisoformat(str(it["ts"]))
        out.append(it)
    return out


# ---------- live and scenario frames ----------

NEWS_NEAR_M = 10000  # news pins only near a project or utility substation
DAMAGE_KINDS = {"downed_line", "substation_damage", "tree_on_line", "wind_damage", "tornado", "flooding"}
WORK_WORDS = ("construction", "project", "upgrade", "rebuild", "new line", "substation", "transmission line", "right-of-way")

NEWS_SQL = """
WITH n AS (
  SELECT DISTINCT ON (s->>'url') i.id AS incident_id, i.ts, i.kind, i.verified, i.geom, s->>'title' AS title, s->>'name' AS source,
         s->>'url' AS url, coalesce(s->>'quote_evidence', '') AS quote, s->>'ts' AS published
  FROM incident i CROSS JOIN LATERAL jsonb_array_elements(i.sources) s
  WHERE i.mode = %(mode)s AND s->>'type' = 'news' AND i.ts <= %(t)s AND i.ts >= %(t0)s
  ORDER BY s->>'url', i.ts DESC
)
SELECT n.incident_id, n.ts, n.kind, n.verified, n.title, n.source, n.url, n.quote, n.published, near.name AS near_name, near.mi AS near_mi,
       ST_AsGeoJSON(n.geom, 5)::json AS geometry
FROM n CROSS JOIN LATERAL (
  SELECT x.name, round((ST_Distance(x.geom, n.geom) / 1609.344)::numeric, 1) AS mi FROM (
    SELECT name, geom FROM job WHERE horizon = 'long'
    UNION ALL SELECT coalesce(name, 'utility substation'), geom FROM asset) x
  WHERE ST_DWithin(x.geom, n.geom, %(near_m)s) ORDER BY ST_Distance(x.geom, n.geom) LIMIT 1) near
"""  # the lateral join drops news that is not near any site

ACTIVE_AT_SQL = """
SELECT j.id, j.name, j.phase, j.org_id, o.name AS org_name, o.color, j.parent_job_id, lower(j.work_window) AS start_at, upper(j.work_window) AS end_at,
       ST_AsGeoJSON(j.geom, 5)::json AS geometry, ST_AsGeoJSON(ST_PointOnSurface(j.geom::geometry), 5)::json AS label
FROM job j JOIN org o ON o.id = j.org_id WHERE j.horizon = 'near' AND j.work_window @> %(t)s::timestamptz
"""


def topic(kind, title):
    if kind == "outage":
        return "outage"
    if kind in DAMAGE_KINDS:
        return "damage"
    return "work" if any(w in (title or "").lower() for w in WORK_WORDS) else "other"


SEVERITY = ["damage", "outage", "work", "other"]


def news_pins(rows):
    """One pin per place: syndicated copies of a story collapse into one article with a copy count."""
    pins = {}
    for r in rows:
        lon, lat = r["geometry"]["coordinates"]
        pin = pins.setdefault((round(lon, 3), round(lat, 3)), {"geometry": r["geometry"], "articles": {}, "near_name": r["near_name"],
                                                                "near_mi": float(r["near_mi"]), "verified": False, "ts": r["ts"]})
        key = " ".join((r["title"] or "").lower().split())[:80]
        art = pin["articles"].setdefault(key, {"title": r["title"], "source": r["source"], "url": r["url"], "quote": (r["quote"] or "")[:240],
                                               "published": r["published"], "topic": topic(r["kind"], r["title"]), "copies": 0})
        art["copies"] += 1
        pin["verified"] = pin["verified"] or bool(r["verified"])
        pin["ts"] = max(pin["ts"], r["ts"])
    out = []
    for pin in pins.values():
        arts = sorted(pin.pop("articles").values(), key=lambda a: SEVERITY.index(a["topic"]))
        out.append({"type": "Feature", "geometry": pin.pop("geometry"),
                    "properties": {**pin, "ts": pin["ts"].isoformat(), "topic": arts[0]["topic"], "count": len(arts), "articles": arts}})
    return out


def _fc(features):
    return {"type": "FeatureCollection", "features": features}


def frame(conn, t=None, scenario="none"):
    """Everything the map shows at time t: live feeds by default, or a planted storm scenario."""
    now = datetime.now(timezone.utc)
    if scenario == "helene":
        mode, rng = "replay", REPLAY
        t = min(max(t or LANDFALL - timedelta(hours=12), REPLAY[0]), REPLAY[1])
    else:
        mode, rng = "live", (now - timedelta(days=HISTORY_DAYS), now)
        t = min(t or now, now)
    out = replay.frame(conn, t, mode)
    for f in out["incidents"]["features"]:  # older incidents fade on the map
        f["properties"]["age_h"] = round((t - datetime.fromisoformat(f["properties"]["ts"])).total_seconds() / 3600, 1)
    t0 = REPLAY[0] if mode == "replay" else t - timedelta(hours=72)
    news_rows = conn.execute(NEWS_SQL, {"mode": mode, "t": t, "t0": t0, "near_m": NEWS_NEAR_M}).fetchall()
    out_news = news_pins(news_rows)
    active, labels = [], []
    for r in conn.execute(ACTIVE_AT_SQL, {"t": t}).fetchall():
        label = r.pop("label")
        feat = replay.feature(r)
        active.append(feat)
        labels.append({"type": "Feature", "geometry": label, "properties": {"phase": r["phase"], "color": r["color"], "id": r["id"]}})
    risks = []
    if mode == "live" and now - t < timedelta(days=2):  # wind forecasts only describe the coming week
        risks = conn.execute("SELECT job_id, site, day, gust_mph, work, alert FROM phase_risk ORDER BY day, gust_mph DESC").fetchall()
    out.update({
        "scenario": scenario, "range": [rng[0].isoformat(), rng[1].isoformat()], "is_live": mode == "live" and now - t < timedelta(minutes=10),
        "storm_active": bool(out["cone"]["features"]), "news": _fc(out_news), "active_phases": _fc(active), "active_labels": _fc(labels),
        "wind_risks": risks,
    })
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
