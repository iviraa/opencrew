import json
import re
from datetime import timedelta

from app.geo.geolocate import km

MERGE_KM, MERGE_HOURS = 2.0, 6  # same kind this close in space and time is one event
NEAR_KM, NEAR_HOURS = 10.0, 12  # official report this close corroborates a news incident
PRECISION = {"exact": 1.0, "road": 0.95, "town": 0.85, "county": 0.7, "state": 0.4}
POWER_KINDS = {"downed_line", "substation_damage", "outage", "tree_on_line"}
ESTABLISHED = {  # local and national outlets we treat as established news
    "wrdw.com", "wjbf.com", "augustachronicle.com", "wfxg.com", "wsav.com", "wtoc.com", "savannahnow.com", "wjcl.com", "postandcourier.com",
    "thestate.com", "wltx.com", "wistv.com", "islandpacket.com", "aikenstandard.com", "ajc.com", "11alive.com", "wsbtv.com", "fox5atlanta.com",
    "gpb.org", "scdailygazette.com", "apnews.com", "reuters.com", "cnn.com", "nbcnews.com", "abcnews.go.com", "cbsnews.com", "weather.com",
    "washingtonpost.com", "nytimes.com", "npr.org", "foxweather.com", "usatoday.com", "wcnc.com", "wyff4.com", "wspa.com", "live5news.com",
}

SUBSTATION = re.compile(r"\bsubstations?\b", re.I)
TREE_ON_LINE = re.compile(r"\btrees?\b[^.]{0,40}\b(?:on|onto|into|across|fell on|fallen on|tangled in)\b[^.]{0,30}\blines?\b", re.I)
DOWNED = re.compile(r"(?:power|utility|electric(?:al)?)\s(?:lines?|poles?)\b[^.]{0,25}\b(?:down|downed|damaged|snapped|broken)\b|"
                    r"\bdowned\s(?:power\s|utility\s)?(?:lines?|poles?)\b|\blines?\s(?:are\s|were\s)?down\b", re.I)
OUTAGE = re.compile(r"without power|power outages?|lost power|\boutages?\b|customers?\s(?:are\s|were\s)?(?:out|without)", re.I)
FLOOD = re.compile(r"\bflood", re.I)
CUSTOMERS = re.compile(r"(\d{1,3}(?:,\d{3})+|\d{2,7})\s+(?:customers|homes and businesses|households|accounts)", re.I)
UTILITIES = [("Georgia Power", r"georgia power"), ("Dominion Energy", r"dominion|sce&g"), ("Santee Cooper", r"santee cooper"),
             ("Duke Energy", r"duke energy"), ("electric cooperative", r"\bemc\b|electric (?:membership|cooperative)")]


def classify(text, report_type=""):
    text = text or ""
    if SUBSTATION.search(text):
        return "substation_damage"
    if TREE_ON_LINE.search(text):
        return "tree_on_line"
    if DOWNED.search(text):
        return "downed_line"
    if OUTAGE.search(text):
        return "outage"
    if FLOOD.search(text) or "FLOOD" in report_type.upper():
        return "flooding"
    return "tornado" if "TORN" in report_type.upper() else "wind_damage"


def customers(text):
    nums = [int(m.replace(",", "")) for m in CUSTOMERS.findall(text or "")]
    return max(nums) if nums else None


def utility(text):
    return next((name for name, rx in UTILITIES if re.search(rx, text or "", re.I)), None)


def domain(url):
    host = re.sub(r"^https?://", "", url or "").split("/")[0].lower()
    return host[4:] if host.startswith("www.") else host


def trust(source):
    if source["type"] == "official":
        return 0.9
    if source["type"] == "context":
        return 0.0
    base = 0.6 if source.get("name") in ESTABLISHED else 0.4
    return base * (0.8 if source.get("method") == "rules" else 1.0)  # keyword fallback without an llm counts for less


def merge(items):
    """Greedy merge: same kind within MERGE_KM and MERGE_HOURS of an incident's first report joins it."""
    out = []
    for it in sorted(items, key=lambda x: x["ts"]):
        for inc in out:
            if inc["kind"] == it["kind"] and abs(it["ts"] - inc["ts"]) <= timedelta(hours=MERGE_HOURS) \
                    and km((inc["lat"], inc["lon"]), (it["lat"], it["lon"])) <= MERGE_KM:
                absorb(inc, it)
                break
        else:
            out.append({**it, "points": [(it["lon"], it["lat"])], "sources": list(it["sources"])})
    return out


def official(inc):
    return any(s["type"] == "official" for s in inc["sources"])


def absorb(inc, it):
    inc["points"].append((it["lon"], it["lat"]))
    if official(it) and not official(inc):  # news never overrides official data
        inc.update({k: it[k] for k in ("lon", "lat", "where_text", "precision")})
    inc["sources"] += it["sources"]
    inc["customers_affected"] = max(filter(None, [inc.get("customers_affected"), it.get("customers_affected")]), default=None)
    inc["utility_mentioned"] = inc.get("utility_mentioned") or it.get("utility_mentioned")


def score(inc, official_nearby=False):
    names = {s["name"] for s in inc["sources"] if s["type"] != "context"}
    corroboration = min(0.3, 0.15 * (len(names) - 1)) + (0.1 if official_nearby and not official(inc) else 0)
    base = max(trust(s) for s in inc["sources"])
    conf = round(min(1.0, (base + corroboration) * PRECISION.get(inc["precision"], 0.7)), 2)
    verified = official(inc) or len(names) >= 2  # official source or two independent sources
    return conf, verified


def official_items(conn, mode="replay"):
    rows = conn.execute("""SELECT ts, kind, ST_X(geom::geometry) AS lon, ST_Y(geom::geometry) AS lat, payload FROM storm_event
                           WHERE kind IN ('lsr', 'spc_report') AND coalesce(payload->>'mode', 'replay') = %s""", (mode,)).fetchall()
    out = []
    for r in rows:
        p = r["payload"]
        text = p.get("remark") or p.get("comments") or ""
        lsr = r["kind"] == "lsr"
        spc_day = (r["ts"] - timedelta(hours=12)).strftime("%y%m%d")
        out.append({
            "ts": r["ts"], "kind": classify(text, p.get("type") or p.get("kind") or ""), "lon": r["lon"], "lat": r["lat"],
            "where_text": f"{p.get('place')}, {p.get('state')}", "precision": "road",
            "utility_mentioned": utility(text), "customers_affected": customers(text),
            "sources": [{"type": "official", "name": "NWS local storm report" if lsr else "SPC storm report",
                         "url": "https://mesonet.agron.iastate.edu/lsr/" if lsr else f"https://www.spc.noaa.gov/climo/reports/{spc_day}_rpts.html",
                         "title": f"{p.get('type') or p.get('kind')} report near {p.get('place')}, {p.get('county')} County, {p.get('state')}",
                         "quote_evidence": text, "reported_by": p.get("reported_by"), "ts": r["ts"].isoformat()}],
        })
    return out


NEAREST_SQL = """
UPDATE incident i SET nearest = (
  SELECT jsonb_object_agg(org_id, jsonb_build_object('asset', name, 'km', round((d / 1000)::numeric, 1)))
  FROM (SELECT DISTINCT ON (a.org_id) a.org_id, a.name, ST_Distance(a.geom, i.geom) AS d FROM asset a
        WHERE ST_DWithin(a.geom, i.geom, 25000) ORDER BY a.org_id, d) x)
WHERE i.mode = %(mode)s
"""

CONTEXT_SQL = """
UPDATE incident i SET confidence = least(1, i.confidence + 0.05),
  sources = i.sources || jsonb_build_array(jsonb_build_object('type', 'context', 'name', 'NWS warning', 'title', w.label))
FROM (SELECT DISTINCT ON (i2.id) i2.id, coalesce(w2.payload->>'label', w2.payload->>'phenomena') AS label
      FROM incident i2 JOIN storm_event w2 ON w2.kind = 'nws_alert' AND w2.ts <= i2.ts
        AND (w2.payload->>'expire')::timestamptz >= i2.ts AND ST_Intersects(w2.geom, i2.geom)
      WHERE i2.mode = %(mode)s ORDER BY i2.id) w
WHERE i.id = w.id AND i.mode = %(mode)s
"""  # an active warning over the spot is context, not verification


def rebuild(conn, mode="replay", news_items=()):
    items = official_items(conn, mode) + list(news_items)
    incidents = merge(items)
    offs = [it for it in items if it["sources"][0]["type"] == "official"]
    conn.execute("DELETE FROM incident WHERE mode = %s", (mode,))
    rows = []
    for inc in incidents:
        near = not official(inc) and any(abs(o["ts"] - inc["ts"]) <= timedelta(hours=NEAR_HOURS)
                                         and km((o["lat"], o["lon"]), (inc["lat"], inc["lon"])) <= NEAR_KM for o in offs)
        conf, verified = score(inc, near)
        pts = ", ".join(f"{x} {y}" for x, y in inc["points"])
        rows.append((inc["ts"], mode, inc["kind"], f"POINT({inc['lon']} {inc['lat']})", f"MULTIPOINT({pts})", inc["where_text"], inc["precision"],
                     inc.get("utility_mentioned"), inc.get("customers_affected"), conf, verified, not verified,
                     json.dumps(inc["sources"], default=str)))
    with conn.cursor() as cur:
        cur.executemany("""INSERT INTO incident (ts, mode, kind, geom, footprint, where_text, precision, utility_mentioned, customers_affected,
                                                 confidence, verified, needs_confirmation, sources)
                           VALUES (%s, %s, %s, ST_GeogFromText(%s), ST_GeogFromText(%s), %s, %s, %s, %s, %s, %s, %s, %s)""", rows)
    conn.execute(NEAREST_SQL, {"mode": mode})
    conn.execute(CONTEXT_SQL, {"mode": mode})
    return conn.execute("""SELECT count(*) AS incidents, count(*) FILTER (WHERE verified) AS verified,
                                  count(*) FILTER (WHERE kind = ANY(%s)) AS power FROM incident WHERE mode = %s""",
                        (list(POWER_KINDS), mode)).fetchone()
