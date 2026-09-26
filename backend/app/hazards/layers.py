"""Live and outlook hazard layers for the whole country: fetched, cached on disk, stored as hazard_layer rows."""
import io
import json
import re
import zipfile
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

import httpx
import shapefile
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.ops import unary_union

from app.hazards.config import (ALERT_EVENTS, ALERT_RANK, CACHE, CPC, CPC_PRODUCTS, HEADERS, LIVE_TTL_H, OUTLOOK_TTL_H, SOURCES, SPC_FIRE, USGS,
                                WFIGS, WFIGS_LAYERS)
from app.storm import outlook
from app.storm.outlook import ERO_LIVE, ERO_RANK, GTWO_LIVE, GTWO_RANK, SPC48_LIVE, SPC48_RANK, SPC_LIVE, SPC_RANK, SPC_WORDS, utc

STATE_FIPS = {"AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09", "DE": "10", "DC": "11", "FL": "12", "GA": "13",
              "HI": "15", "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21", "LA": "22", "ME": "23", "MD": "24", "MA": "25",
              "MI": "26", "MN": "27", "MS": "28", "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36",
              "NC": "37", "ND": "38", "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46", "TN": "47", "TX": "48",
              "UT": "49", "VT": "50", "VA": "51", "WA": "53", "WV": "54", "WI": "55", "WY": "56", "PR": "72"}
FIPS_STATE = {v: k for k, v in STATE_FIPS.items()}
US_BOX = (-179.5, 17.5, -64.0, 72.0)  # includes alaska, hawaii and puerto rico
SPC_FIRE_RANK = {"ELEV": 1, "CRIT": 2, "EXTM": 3, "ISODRYT": 1, "SCTDRYT": 2}
SPC_FIRE_WORDS = {"ELEV": "elevated fire weather", "CRIT": "critical fire weather", "EXTM": "extreme fire weather",
                  "ISODRYT": "isolated dry thunderstorms", "SCTDRYT": "scattered dry thunderstorms"}
MAX_ZONE_FETCH = 60  # zone outlines fetched from the NWS per refresh when the county correlation cannot draw an alert
SIMPLIFY = 0.01  # degrees, about 1 km: plenty for a national map


def get(url, **kw):
    r = httpx.get(url, headers=HEADERS, timeout=90, follow_redirects=True, **kw)
    r.raise_for_status()
    return r


def cached(name, fetch, ttl_h):
    """Bytes from disk when fresh enough, else fetched and saved. Returns (bytes, fetched_at)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / name
    if path.exists():
        age = datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        if age < timedelta(hours=ttl_h):
            return path.read_bytes(), datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    blob = fetch()
    path.write_bytes(blob)
    return blob, datetime.now(timezone.utc)


def simple(geom):
    g = geom.simplify(SIMPLIFY, preserve_topology=True)
    return geom if g.is_empty else g


def row(layer, hazard, product, label, rank, start, end, geom, props=None, source="", fetched=None):
    return {"layer": layer, "hazard": hazard, "product": product, "label": label, "rank": rank, "period_start": start, "period_end": end,
            "props": props or {}, "source": source, "fetched_at": fetched or datetime.now(timezone.utc), "wkt": simple(geom).wkt}


# ---------- counties and NWS zones, for drawing zone-based alerts ----------

@lru_cache
def county_shapes():
    """FIPS -> shapely polygon from the Census 1:20m county file."""
    from app.db import ROOT
    z = zipfile.ZipFile(ROOT / "data/layers/counties_20m.zip")
    base = next(n for n in z.namelist() if n.endswith(".shp"))[:-4]
    r = shapefile.Reader(shp=io.BytesIO(z.read(base + ".shp")), dbf=io.BytesIO(z.read(base + ".dbf")))
    return {rec["GEOID"]: shape(s.__geo_interface__) for rec, s in zip(r.records(), r.shapes())}


def parse_zone_counties(text):
    """NWS bp*.dbx: STATE|ZONE|CWA|NAME|STATE_ZONE|COUNTY|FIPS|... -> {'GAZ001': ['13123', ...]}."""
    out = {}
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) < 7 or not parts[6].isdigit():
            continue
        out.setdefault(f"{parts[0]}Z{parts[1]}", []).append(parts[6])
    return out


@lru_cache
def zone_counties():
    blob, _ = cached("zone_counties.dbx", lambda: get(SOURCES["nws_zones"]["url"]).content, 24 * 365)
    return parse_zone_counties(blob.decode("utf-8", "ignore"))


def ugc_counties(codes):
    """County FIPS for NWS UGC codes: SSC### is a county, SSZ### a forecast zone."""
    fips = []
    for c in codes or []:
        st, kind, num = c[:2], c[2], c[3:]
        if kind == "C" and st in STATE_FIPS:
            fips.append(STATE_FIPS[st] + num)
        elif kind == "Z":
            fips += zone_counties().get(c, [])
    return fips


def counties_geom(fips):
    shapes = [county_shapes()[f] for f in fips if f in county_shapes()]
    return unary_union(shapes) if shapes else None


def zone_geom(url, budget):
    """Outline of one NWS zone from the API, cached on disk; None once the per-refresh budget is spent."""
    name = "zone_" + url.rsplit("/", 1)[-1] + ".json"
    path = CACHE / name
    if not path.exists():
        if budget[0] <= 0:
            return None
        budget[0] -= 1
        try:
            path.write_bytes(get(url).content)
        except httpx.HTTPError:
            return None
    g = json.loads(path.read_bytes()).get("geometry")
    return shape(g) if g else None


# ---------- live layers ----------

def parse_alerts(data, zone_budget=None, fetched=None):
    """NWS active alerts -> rows for the events that touch construction work; zone alerts are drawn from their counties."""
    rows, budget = [], zone_budget if zone_budget is not None else [MAX_ZONE_FETCH]
    for f in data.get("features", []):
        p = f.get("properties") or {}
        hazard = ALERT_EVENTS.get(p.get("event"))
        if not hazard:
            continue
        geom = shape(f["geometry"]) if f.get("geometry") else counties_geom(ugc_counties((p.get("geocode") or {}).get("UGC")))
        if geom is None and p.get("affectedZones"):
            parts = [g for g in (zone_geom(u, budget) for u in p["affectedZones"][:8]) if g]
            geom = unary_union(parts) if parts else None
        if geom is None or geom.is_empty:
            continue
        kind = next((k for k in ALERT_RANK if p["event"].endswith(k)), "Advisory")
        start = datetime.fromisoformat(p.get("onset") or p.get("effective") or p["sent"])
        end = datetime.fromisoformat(p.get("ends") or p.get("expires"))
        rows.append(row("alerts", hazard, "nws_alert", p["event"], ALERT_RANK[kind], start, end, geom,
                        {"headline": p.get("headline"), "places": (p.get("areaDesc") or "")[:240], "severity": p.get("severity"), "id": p.get("id")},
                        "nws_alerts", fetched))
    return rows


def fetch_alerts():
    blob, at = cached("nws_alerts.json", lambda: get(SOURCES["nws_alerts"]["url"]).content, LIVE_TTL_H)
    return parse_alerts(json.loads(blob), fetched=at)


def parse_spc_national(data, day, product, fetched=None):
    """SPC categorical (days 1-3), probabilistic (days 4-8) or fire weather outlooks, whole country, no clipping."""
    rows = []
    for f in data.get("features", []):
        p, g = f.get("properties") or {}, f.get("geometry")
        label = str(p.get("LABEL", "")).upper()
        if not g or label in ("", "NO AREAS", "TSTM"):
            continue
        if product == "spc":
            if label not in SPC_RANK:
                continue
            rank, text, hazard = SPC_RANK[label], f"SPC {SPC_WORDS[label]}", "storms"
        elif product == "spc48":
            try:
                pct = round(float(label) * 100)
            except ValueError:
                continue
            if pct not in SPC48_RANK:
                continue
            label, rank, text, hazard = f"{pct}%", SPC48_RANK[pct], f"SPC {pct}% chance of severe storms", "storms"
        else:
            if label not in SPC_FIRE_RANK:
                continue
            rank, text, hazard = SPC_FIRE_RANK[label], f"SPC {SPC_FIRE_WORDS[label]}", "wildfire"
        rows.append(row("outlooks", hazard, product, text, rank, utc(p["VALID"]), utc(p["EXPIRE"]), shape(g),
                        {"day": day, "level": label, "issued": utc(p["ISSUE"]).isoformat() if p.get("ISSUE") else None}, "spc", fetched))
    return rows


def parse_ero_national(data, fetched=None):
    groups = {}
    for f in data.get("features", []):
        p, g = f.get("properties") or {}, f.get("geometry")
        word = str(p.get("OUTLOOK", "")).split(" ")[0]
        if word in ERO_RANK and g:
            groups.setdefault((word, p.get("PRODUCT"), p.get("START_TIME"), p.get("END_TIME")), []).append(shape(g))
    rows = []
    for (word, product, start, end), geoms in groups.items():
        day = int(re.search(r"Day (\d)", product or "Day 1").group(1))
        parse = lambda s: datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        rows.append(row("outlooks", "flood", "wpc_ero", f"WPC {word.lower()} risk of flash flooding", ERO_RANK[word], parse(start), parse(end),
                        unary_union(geoms), {"day": day, "level": word}, "wpc_ero", fetched))
    return rows


def parse_gtwo_national(blob, fetched=None):
    """NHC 7-day tropical outlook areas (all basins), from the shapefile zip."""
    rows = []
    for rec, geom in outlook.read_shp(blob, "areas"):
        lvl = str(rec.get("RISK7DAY") or rec.get("RISK2DAY") or "").title()
        if lvl not in GTWO_RANK:
            continue
        stamp = str(rec.get("ISSUANCE") or "")[:12]
        issued = utc(stamp) if stamp.isdigit() else datetime.now(timezone.utc)
        rows.append(row("outlooks", "tropical", "nhc_gtwo", f"NHC {lvl.lower()} chance of a tropical cyclone in 7 days", GTWO_RANK[lvl],
                        issued, issued + timedelta(days=7), geom, {"level": lvl}, "nhc", fetched))
    return rows


def fetch_outlooks():
    rows = []
    for d in (1, 2, 3):
        blob, at = cached(f"spc_day{d}.geojson", lambda d=d: get(SPC_LIVE.format(d=d)).content, LIVE_TTL_H)
        rows += parse_spc_national(json.loads(blob), d, "spc", at)
    for d in range(4, 9):
        blob, at = cached(f"spc_day{d}.geojson", lambda d=d: get(SPC48_LIVE.format(d=d)).content, LIVE_TTL_H)
        rows += parse_spc_national(json.loads(blob), d, "spc48", at)
    for d in (1, 2):
        for kind in ("windrh", "dryt"):
            blob, at = cached(f"spc_fire_day{d}_{kind}.geojson", lambda d=d, k=kind: get(SPC_FIRE.format(d=d, kind=k)).content, LIVE_TTL_H)
            rows += parse_spc_national(json.loads(blob), d, "spc_fire", at)
    for d in range(1, 6):
        blob, at = cached(f"wpc_day{d}.geojson", lambda d=d: get(ERO_LIVE.format(d=d)).content, LIVE_TTL_H)
        rows += parse_ero_national(json.loads(blob), at)
    blob, at = cached("nhc_gtwo.zip", lambda: get(GTWO_LIVE).content, LIVE_TTL_H)
    try:
        rows += parse_gtwo_national(blob, at)
    except (zipfile.BadZipFile, KeyError, ValueError):
        pass  # no active outlook shapefile outside the season
    return rows


def pick(props, *names):
    return next((props[k] for k in props if any(n.lower() in k.lower() for n in names) and props[k] not in (None, "")), None)


def parse_fires(data, kind, fetched=None):
    """WFIGS current perimeters (polygons) or incident locations (points) -> wildfire rows."""
    rows = []
    for f in data.get("features", []):
        p, g = f.get("properties") or {}, f.get("geometry")
        if not g:
            continue
        acres = pick(p, "GISAcres", "IncidentSize", "DailyAcres")
        name = pick(p, "IncidentName") or "Wildfire"
        found = pick(p, "FireDiscoveryDateTime")
        start = datetime.fromtimestamp(found / 1000, timezone.utc) if isinstance(found, (int, float)) else datetime.now(timezone.utc)
        try:
            acres = float(acres) if acres is not None else None
        except (TypeError, ValueError):
            acres = None
        rank = 3 if (acres or 0) >= 10000 else 2 if (acres or 0) >= 1000 else 1
        rows.append(row("fires", "wildfire", f"wfigs_{kind}", f"{name} fire" + (f", {acres:,.0f} acres" if acres else ""), rank,
                        start, datetime.now(timezone.utc) + timedelta(days=7), shape(g),
                        {"acres": acres, "contained_pct": pick(p, "PercentContained"), "state": pick(p, "POOState")}, "wfigs", fetched))
    return rows


def fetch_fires():
    rows = []
    for kind, layer in WFIGS_LAYERS.items():
        params = {"where": "1=1", "outFields": "*", "f": "geojson", "outSR": "4326", "resultRecordCount": "2000"}
        if kind == "perimeters":
            params["maxAllowableOffset"] = str(SIMPLIFY)
        blob, at = cached(f"wfigs_{kind}.geojson", lambda l=layer, q=params: get(WFIGS.format(layer=l), params=q).content, LIVE_TTL_H)
        rows += parse_fires(json.loads(blob), kind, at)
    return rows


def parse_quakes(data, fetched=None):
    rows = []
    for f in data.get("features", []):
        p, g = f.get("properties") or {}, f.get("geometry")
        if not g:
            continue
        lon, lat = g["coordinates"][:2]
        if not (US_BOX[0] <= lon <= US_BOX[2] and US_BOX[1] <= lat <= US_BOX[3]):
            continue
        mag = float(p.get("mag") or 0)
        at = datetime.fromtimestamp(p["time"] / 1000, timezone.utc)
        rows.append(row("quakes", "earthquake", "usgs", f"M{mag:.1f} {p.get('place') or 'earthquake'}", 3 if mag >= 5 else 2 if mag >= 4 else 1,
                        at, at + timedelta(days=7), shape(g), {"mag": mag, "place": p.get("place"), "url": p.get("url")}, "usgs", fetched))
    return rows


def fetch_quakes():
    blob, at = cached("usgs_week.geojson", lambda: get(USGS).content, LIVE_TTL_H)
    return parse_quakes(json.loads(blob), at)


# ---------- weeks to season: CPC outlooks ----------

def season_hazard(var, cat, month):
    """What a temperature or precipitation lean means for the work in that month."""
    if var == "temp" and cat == "Above" and month in (5, 6, 7, 8, 9):
        return "heat"
    if var == "temp" and cat == "Below" and month in (11, 12, 1, 2, 3):
        return "winter"
    if var == "prcp" and cat == "Above":
        return "flood"
    if var == "prcp" and cat == "Below" and month in (5, 6, 7, 8, 9, 10):
        return "wildfire"
    return None


def parse_cpc(blob, var, product, fetched=None):
    """CPC outlook shapefile zip -> rows; 6-10/8-14/wk34 carry dates, monthly and seasonal carry 'Oct 2026' style labels."""
    rows = []
    z = zipfile.ZipFile(io.BytesIO(blob))
    for shp in [n for n in z.namelist() if n.endswith(".shp") and (product != "seasonal" or re.search(r"lead[12]_", n))]:  # seasonal: next two leads only
        base = shp[:-4]
        r = shapefile.Reader(shp=io.BytesIO(z.read(base + ".shp")), dbf=io.BytesIO(z.read(base + ".dbf")))
        for rec, s in zip(r.records(), r.shapes()):
            d = rec.as_dict()
            cat = str(d.get("Cat") or "").title()
            if cat not in ("Above", "Below"):
                continue
            if d.get("Start_Date"):
                start, end = d["Start_Date"], d["End_Date"]
            else:  # 'Oct 2026' or 'OND 2026'
                label = str(d.get("Valid_Seas") or "")
                try:
                    start = datetime.strptime(label, "%b %Y").date()
                    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
                except ValueError:
                    m = re.match(r"([A-Z]{3}) (\d{4})", label)
                    if not m:
                        continue
                    first = "JFMAMJJASOND".index(m.group(1)[0]) + 1
                    start = date(int(m.group(2)), first, 1)
                    end = (date(int(m.group(2)) + (first + 2) // 12, (first + 2) % 12 + 1, 1) - timedelta(days=1)) if first + 2 <= 12 else date(int(m.group(2)) + 1, first + 2 - 12, 1)
            start, end = [x if isinstance(x, date) else date.fromisoformat(str(x)[:10]) for x in (start, end)]
            hazard = season_hazard(var, cat, start.month)
            if not hazard:
                continue
            prob = float(d.get("Prob") or 0)
            geom = shape(s.__geo_interface__)
            if geom.is_empty:
                continue
            rows.append(row("outlooks", hazard, f"cpc_{product}", f"CPC {product}: {prob:.0f}% chance of {cat.lower()}-normal {'temperature' if var == 'temp' else 'precipitation'}",
                            3 if prob >= 60 else 2 if prob >= 45 else 1, datetime.combine(start, datetime.min.time(), timezone.utc),
                            datetime.combine(end, datetime.max.time().replace(microsecond=0), timezone.utc), geom,
                            {"variable": var, "category": cat, "probability": prob, "issued": str(d.get("Fcst_Date") or "")}, "cpc", fetched))
    return rows


def fetch_cpc():
    rows = []
    for prefix, product in CPC_PRODUCTS.items():
        for var in ("temp", "prcp"):
            name = f"{prefix}{var}"
            try:
                blob, at = cached(f"cpc_{name}.zip", lambda n=name: get(CPC.format(name=n)).content, OUTLOOK_TTL_H)
                rows += parse_cpc(blob, var, product, at)
            except (httpx.HTTPError, zipfile.BadZipFile, KeyError, ValueError):
                continue  # one product missing never blocks the others
    return rows


# ---------- storage ----------

def store(conn, rows, products):
    """Replace every row of the given products with the fresh set."""
    conn.execute("DELETE FROM hazard_layer WHERE product = ANY(%s)", (list(products),))
    with conn.cursor() as cur:
        cur.executemany("""INSERT INTO hazard_layer (layer, hazard, product, label, rank, period_start, period_end, props, source, fetched_at, geom)
                           VALUES (%(layer)s, %(hazard)s, %(product)s, %(label)s, %(rank)s, %(period_start)s, %(period_end)s, %(props)s, %(source)s,
                                   %(fetched_at)s, ST_GeogFromText(%(wkt)s))""",
                        [{**r, "props": json.dumps(r["props"], default=str)} for r in rows])
    for p in products:
        conn.execute("""INSERT INTO hazard_fetch (product, fetched_at, rows) VALUES (%s, now(), %s)
                        ON CONFLICT (product) DO UPDATE SET fetched_at = now(), rows = EXCLUDED.rows""", (p, sum(1 for r in rows if r["product"] == p)))
    return len(rows)


GROUPS = {  # refresh group -> (fetcher, products it owns, ttl hours)
    "alerts": (fetch_alerts, ["nws_alert"], LIVE_TTL_H),
    "outlooks": (fetch_outlooks, ["spc", "spc48", "spc_fire", "wpc_ero", "nhc_gtwo"], LIVE_TTL_H),
    "fires": (fetch_fires, ["wfigs_perimeters", "wfigs_incidents"], LIVE_TTL_H),
    "quakes": (fetch_quakes, ["usgs"], LIVE_TTL_H),
    "cpc": (fetch_cpc, ["cpc_" + p for p in CPC_PRODUCTS.values()], OUTLOOK_TTL_H),
}


def stale(conn, group):
    ttl = GROUPS[group][2]
    r = conn.execute("SELECT min(fetched_at) AS at FROM hazard_fetch WHERE product = ANY(%s)", (GROUPS[group][1],)).fetchone()
    return r["at"] is None or datetime.now(timezone.utc) - r["at"] > timedelta(hours=ttl)


def refresh(conn, groups=None, force=False):
    """Fetch and store every stale group; a failing source is reported, never fatal."""
    out = {}
    for g in groups or GROUPS:
        if not force and not stale(conn, g):
            out[g] = "fresh"
            continue
        fetch, products, _ = GROUPS[g]
        try:
            out[g] = store(conn, fetch(), products)
        except (httpx.HTTPError, ValueError, KeyError, zipfile.BadZipFile, OSError) as e:
            out[g] = f"error: {str(e)[:120]}"
    conn.execute("DELETE FROM hazard_layer WHERE period_end < now() - interval '14 days'")
    return out


def polygon_only(geom):
    return geom if isinstance(geom, (Polygon, MultiPolygon)) else geom.buffer(0.02)  # points and lines get a small footprint
