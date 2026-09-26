import io
import json
import re
import zipfile
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import shapefile
from shapely.geometry import box, shape
from shapely.ops import unary_union

from app.db import ROOT

RAW = ROOT / "data/raw/outlooks"
HEADERS = {"User-Agent": "opencrew/0.1 (hackathon)"}
ET = ZoneInfo("America/New_York")
REGION = box(-89.0, 24.0, -74.0, 37.5)  # the southeast: enough to see what is heading for ga and sc
HOME = (-85.7, 30.3, -78.5, 35.3)  # ga + sc, where heads-up items must land
PAUSE_HOUR = 12  # crane and line work should be down by local noon on a severe weather day
PEAK_HOUR = 14  # severe storms and flash floods peak in the afternoon
WORK_PHASES = {"construction", "clearing", "energization"}  # phases with cranes, saws or live-line work

SPC_RANK = {"MRGL": 1, "SLGT": 2, "ENH": 3, "MDT": 4, "HIGH": 5}
SPC_WORDS = {"MRGL": "marginal risk", "SLGT": "slight risk", "ENH": "enhanced risk", "MDT": "moderate risk", "HIGH": "high risk"}
SPC48_RANK = {15: 2, 30: 3}
ERO_RANK = {"Marginal": 1, "Slight": 2, "Moderate": 4, "High": 5}
GTWO_RANK = {"Low": 1, "Medium": 2, "High": 3}
WSP_BANDS = [10, 30, 50, 70, 90]  # percent, like the nhc field

SPC_LIVE = "https://www.spc.noaa.gov/products/outlook/day{d}otlk_cat.lyr.geojson"
SPC48_LIVE = "https://www.spc.noaa.gov/products/exper/day4-8/day{d}prob.lyr.geojson"
SPC_ARCHIVE = "https://www.spc.noaa.gov/products/outlook/archive/{y}/day{d}otlk_{date}_{hhmm}_cat.lyr.geojson"
SPC48_ARCHIVE = "https://www.spc.noaa.gov/products/exper/day4-8/archive/{y}/day{d}prob_{date}.lyr.geojson"
ERO_LIVE = "https://www.wpc.ncep.noaa.gov/exper/eromap/geojson/Day{d}_Latest.geojson"
GTWO_LIVE = "https://www.nhc.noaa.gov/xgtwo/gtwo_shapefiles.zip"
GTWO_LIST = "https://www.nhc.noaa.gov/gis/archive_gtwo.php?year={y}"
GTWO_ARCHIVE = "https://www.nhc.noaa.gov/gis/gtwo/archive/{stamp}_gtwo.zip"
WSP_LIST = "https://www.nhc.noaa.gov/gis/archive_wsp.php?year={y}"
WSP_ARCHIVE = "https://www.nhc.noaa.gov/gis/forecast/archive/{stamp}_wsp_120hrhalfDeg.zip"
STORMS = "https://www.nhc.noaa.gov/CurrentStorms.json"

HELENE_DAYS = [datetime(2024, 9, d, tzinfo=timezone.utc) for d in range(21, 29)]  # outlooks issued before and during helene

CITIES = [("Atlanta", 33.75, -84.39), ("Augusta", 33.47, -81.97), ("Savannah", 32.08, -81.09), ("Macon", 32.84, -83.63),
          ("Columbus", 32.46, -84.99), ("Albany", 31.58, -84.16), ("Valdosta", 30.83, -83.28), ("Brunswick", 31.15, -81.49),
          ("Athens", 33.96, -83.38), ("Columbia", 34.00, -81.03), ("Charleston", 32.78, -79.93), ("Greenville", 34.85, -82.40),
          ("Florence", 34.20, -79.76), ("Aiken", 33.56, -81.72), ("Beaufort", 32.43, -80.67), ("Myrtle Beach", 33.69, -78.89),
          ("Statesboro", 32.45, -81.78), ("Dublin", 32.54, -82.90), ("Rome", 34.26, -85.16), ("Orangeburg", 33.49, -80.86)]


# ---------- parsers (pure) ----------

def utc(stamp):
    """SPC and NHC stamps: YYYYMMDDHH or YYYYMMDDHHMM in UTC."""
    s = str(stamp)
    return datetime.strptime(s[:12].ljust(12, "0"), "%Y%m%d%H%M").replace(tzinfo=timezone.utc)


def clip(geom, region=REGION):
    if geom is None or geom.is_empty:
        return None
    g = geom.intersection(region)
    return None if g.is_empty else g


def row(mode, product, day, issued, valid_from, valid_to, level, rank, label, geom, url=None, props=None):
    return {"mode": mode, "product": product, "day": day, "issued": issued, "valid_from": valid_from, "valid_to": valid_to,
            "level": level, "rank": rank, "label": label, "props": props or {}, "source_url": url, "wkt": geom.wkt}


def parse_spc(data, day, mode="live", url=None, issued=None):
    """SPC categorical outlook (days 1-3). General thunder is skipped: only severe risk levels are kept."""
    rows = []
    for f in data.get("features", []):
        p, g = f.get("properties") or {}, f.get("geometry")
        label = str(p.get("LABEL", "")).upper()
        if label not in SPC_RANK or not g:
            continue
        geom = clip(shape(g))
        if geom is None:
            continue
        rows.append(row(mode, "spc", day, utc(p["ISSUE"]) if p.get("ISSUE") else issued, utc(p["VALID"]), utc(p["EXPIRE"]), label,
                        SPC_RANK[label], f"SPC {SPC_WORDS[label]}", geom, url))
    return rows


def parse_spc48(data, day, mode="live", url=None, issued=None):
    """SPC day 4-8 outlook: 15% and 30% chances of severe storms."""
    rows = []
    for f in data.get("features", []):
        p, g = f.get("properties") or {}, f.get("geometry")
        try:
            pct = round(float(p.get("LABEL")) * 100)
        except (TypeError, ValueError):
            continue
        if pct not in SPC48_RANK or not g:
            continue
        geom = clip(shape(g))
        if geom is None:
            continue
        rows.append(row(mode, "spc48", day, utc(p["ISSUE"]) if p.get("ISSUE") else issued, utc(p["VALID"]), utc(p["EXPIRE"]), f"{pct}%",
                        SPC48_RANK[pct], f"SPC {pct}% chance of severe storms", geom, url))
    return rows


def parse_ero(data, mode="live", url=None):
    """WPC excessive rainfall outlook: one row per risk level, pieces merged."""
    groups = {}
    for f in data.get("features", []):
        p, g = f.get("properties") or {}, f.get("geometry")
        word = str(p.get("OUTLOOK", "")).split(" ")[0]
        if word not in ERO_RANK or not g:
            continue
        groups.setdefault((word, p.get("OUTLOOK"), p.get("PRODUCT"), p.get("ISSUE_TIME"), p.get("START_TIME"), p.get("END_TIME")), []).append(shape(g))
    rows = []
    for (word, outlook, product, issue, start, end), geoms in groups.items():
        geom = clip(unary_union(geoms))
        if geom is None:
            continue
        day = int(re.search(r"Day (\d)", product or "Day 1").group(1))
        pct = re.search(r"(\d+%)", outlook or "")
        parse = lambda s: datetime.fromisoformat(s).replace(tzinfo=timezone.utc)  # wpc times are utc
        rows.append(row(mode, "wpc_ero", day, parse(issue), parse(start), parse(end), word, ERO_RANK[word],
                        f"WPC {word.lower()} risk of flash flooding" + (f" (at least {pct.group(1)})" if pct else ""), geom, url))
    return rows


def parse_gtwo(areas, stamp, mode="live", url=None):
    """NHC 7-day tropical weather outlook areas (Atlantic only). `areas` is [(record dict, shapely geom)]."""
    rows = []
    for rec, geom in areas:
        if rec.get("BASIN") != "Atlantic" or geom is None or geom.is_empty:
            continue
        risk = str(rec.get("RISK7DAY", "Low")).title()
        prob = str(rec.get("PROB7DAY", "")).strip()
        rows.append(row(mode, "nhc_gtwo", None, stamp, stamp, stamp + timedelta(days=7), prob, GTWO_RANK.get(risk, 1),
                        f"{prob} chance of tropical development within 7 days", geom, url,
                        {"prob2day": rec.get("PROB2DAY"), "prob7day": prob, "risk7day": risk, "area": rec.get("AREA")}))
    return rows


def smooth(geom, r=0.2):
    """Round off the staircase edges of merged grid cells."""
    return geom.buffer(r).buffer(-2 * r).buffer(r)


def parse_wsp(cells, stamp, mode="live", url=None):
    """NHC tropical-storm-force wind probabilities: half-degree grid points grown into cells, merged into nested bands."""
    rows = []
    for i, band in enumerate(WSP_BANDS):
        inside = [g.buffer(0.25, cap_style="square") if g.geom_type == "Point" else g for p, g in cells if p >= band]
        geom = clip(smooth(unary_union(inside))) if inside else None
        if geom is None:
            continue
        rows.append(row(mode, "nhc_wsp", None, stamp, stamp, stamp + timedelta(hours=120), f"{band}%", i + 1,
                        f"{band}% or higher chance of tropical-storm-force winds within 5 days", geom.simplify(0.02), url))
    return rows


def read_shp(blob, contains):
    z = zipfile.ZipFile(io.BytesIO(blob))
    base = next((n[:-4] for n in z.namelist() if contains in n and n.endswith(".shp")), None)
    if not base:
        return base, []
    r = shapefile.Reader(shp=io.BytesIO(z.read(base + ".shp")), dbf=io.BytesIO(z.read(base + ".dbf")))
    return base, [(rec.as_dict(), shape(s.__geo_interface__)) for rec, s in zip(r.records(), r.shapes())]


def gtwo_rows(blob, mode, url):
    base, areas = read_shp(blob, "gtwo_areas_")
    if not base:
        return []
    return parse_gtwo(areas, utc(base.split("_")[-1]), mode, url)


def wsp_rows(blob, mode, url):
    base, cells = read_shp(blob, "wsp34knt")
    if not base:
        return []
    return parse_wsp([(float(rec["PWIND120"]), g) for rec, g in cells], utc(base.split("_")[0]), mode, url)


# ---------- fetching and storing ----------

def download(url, name, refresh=False):
    path = RAW / name
    if refresh or not path.exists():
        r = httpx.get(url, headers=HEADERS, timeout=60, follow_redirects=True)
        if r.status_code != 200:
            return None
        RAW.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
    return path.read_bytes()


def store(conn, rows):
    for key in {(r["mode"], r["product"], r["issued"], r["day"]) for r in rows}:  # a re-fetch replaces the same issuance
        conn.execute("DELETE FROM outlook WHERE mode = %s AND product = %s AND issued = %s AND day IS NOT DISTINCT FROM %s", key)
    with conn.cursor() as cur:
        cur.executemany("""INSERT INTO outlook (mode, product, day, issued, valid_from, valid_to, level, rank, label, props, source_url, geom)
                           VALUES (%(mode)s, %(product)s, %(day)s, %(issued)s, %(valid_from)s, %(valid_to)s, %(level)s, %(rank)s, %(label)s,
                                   %(props)s, %(source_url)s, ST_GeogFromText(%(wkt)s))""",
                        [{**r, "props": json.dumps(r["props"])} for r in rows])
    return len(rows)


def fetch_live(conn):
    """Today's official outlooks. A source that fails is skipped, never the whole refresh."""
    now, out, rows = datetime.now(timezone.utc), {}, []
    sources = [(f"spc_day{d}", SPC_LIVE.format(d=d), lambda b, d=d, u=SPC_LIVE.format(d=d): parse_spc(json.loads(b), d, "live", u, now)) for d in (1, 2, 3)]
    sources += [(f"spc_day{d}", SPC48_LIVE.format(d=d), lambda b, d=d, u=SPC48_LIVE.format(d=d): parse_spc48(json.loads(b), d, "live", u, now)) for d in range(4, 9)]
    sources += [(f"wpc_day{d}", ERO_LIVE.format(d=d), lambda b, u=ERO_LIVE.format(d=d): parse_ero(json.loads(b), "live", u)) for d in range(1, 6)]
    sources += [("nhc_gtwo", GTWO_LIVE, lambda b: gtwo_rows(b, "live", GTWO_LIVE))]
    try:
        storms = httpx.get(STORMS, headers=HEADERS, timeout=30).json().get("activeStorms", [])
        for url in {s["windSpeedProbabilitiesGIS"]["zipFile0p5deg"] for s in storms if s["id"].startswith("al") and s.get("windSpeedProbabilitiesGIS")}:
            sources.append(("nhc_wsp", url, lambda b, u=url: wsp_rows(b, "live", u)))
        out["active_storms"] = [f"{s['classification']} {s['name']}" for s in storms if s["id"].startswith("al")]
    except (httpx.HTTPError, ValueError, KeyError) as e:
        out["storms_error"] = str(e)[:120]
    for name, url, parse in sources:
        try:
            blob = download(url, f"live_{name}_{url.rsplit('/', 1)[-1]}", refresh=True)
            got = parse(blob) if blob else []
            rows += got
            out[name] = out.get(name, 0) + len(got)
        except (httpx.HTTPError, ValueError, KeyError, zipfile.BadZipFile) as e:
            out[f"{name}_error"] = str(e)[:120]
    store(conn, rows)
    conn.execute("DELETE FROM outlook WHERE mode = 'live' AND valid_to < now() - interval '30 days'")  # same history window as the live map
    return out


def archive_stamps(url, pattern):
    html = httpx.get(url, headers=HEADERS, timeout=60).text
    return sorted(set(re.findall(pattern, html)))


def fetch_helene(conn):
    """Outlooks that were issued before and during Helene, from the official archives."""
    rows, out = [], {"wpc_ero": "unavailable: WPC does not publish an archive of outlook shapes"}
    for day0 in HELENE_DAYS:
        date, y = day0.strftime("%Y%m%d"), day0.year
        for d, times in ((1, ["1200", "1300"]), (2, ["0600", "0700", "1730"]), (3, ["0730", "0830"])):
            for hhmm in times:  # first issuance that exists that morning
                url = SPC_ARCHIVE.format(y=y, d=d, date=date, hhmm=hhmm)
                blob = download(url, f"helene_spc_day{d}_{date}_{hhmm}.geojson")
                if blob:
                    rows += parse_spc(json.loads(blob), d, "replay", url, day0 + timedelta(hours=int(hhmm[:2])))
                    break
        for d in range(4, 9):
            url = SPC48_ARCHIVE.format(y=y, d=d, date=date)
            blob = download(url, f"helene_spc_day{d}_{date}.geojson")
            if blob:
                rows += parse_spc48(json.loads(blob), d, "replay", url, day0 + timedelta(hours=9))
    out["spc"] = sum(r["product"] in ("spc", "spc48") for r in rows)
    lo, hi = "202409200000", "202409280000"
    gtwo = [s for s in archive_stamps(GTWO_LIST.format(y=2024), r"gtwo/archive/(\d{12})_gtwo\.zip") if lo <= s < hi]
    picked = {}
    for s in gtwo:
        picked.setdefault((s[:8], int(s[8:10]) // 6), s)  # one outlook per 6 hours
    for s in sorted(picked.values()):
        url = GTWO_ARCHIVE.format(stamp=s)
        blob = download(url, f"helene_gtwo_{s}.zip")
        if blob:
            rows += gtwo_rows(blob, "replay", url)
    out["nhc_gtwo"] = sum(r["product"] == "nhc_gtwo" for r in rows)
    wsp = [s for s in archive_stamps(WSP_LIST.format(y=2024), r"forecast/archive/(\d{10})_wsp_120hrhalfDeg\.zip") if lo[:10] <= s < hi[:10]]
    for s in wsp:
        url = WSP_ARCHIVE.format(stamp=s)
        blob = download(url, f"helene_wsp_{s}.zip")
        if blob:
            rows += wsp_rows(blob, "replay", url)
    out["nhc_wsp"] = sum(r["product"] == "nhc_wsp" for r in rows)
    store(conn, rows)
    return out


# ---------- what the map shows at a time ----------

FRAME_SQL = """
WITH c AS (
  SELECT o.*, dense_rank() OVER (PARTITION BY o.product ORDER BY o.issued DESC) AS r
  FROM outlook o
  WHERE o.mode = %(mode)s AND o.issued <= %(known)s AND o.valid_from <= %(view)s AND o.valid_to > %(view)s
)
SELECT id, product, day, issued, valid_from, valid_to, level, rank, label, props,
       ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom::geometry, 0.01), 4)::json AS geometry
FROM c WHERE r = 1 ORDER BY product, rank
"""


def rows_at(conn, view, known, mode):
    """Latest outlooks known by `known` that are valid at `view` (view may be in the future)."""
    return conn.execute(FRAME_SQL, {"mode": mode, "known": known, "view": view}).fetchall()


def frame(conn, view, known, mode):
    feats = []
    for r in rows_at(conn, view, known, mode):
        geom = r.pop("geometry")
        props = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()}
        feats.append({"type": "Feature", "geometry": geom, "properties": props})
    return {"type": "FeatureCollection", "features": feats, "view": view.isoformat(), "known": known.isoformat(), "mode": mode}


# ---------- heads-up sentences ----------

SITES_SQL = """
SELECT j.id, coalesce(j.parent_job_id, j.id) AS project, j.name, j.phase,
       ST_Y(ST_PointOnSurface(j.geom::geometry)) AS lat, ST_X(ST_PointOnSurface(j.geom::geometry)) AS lon
FROM job j JOIN outlook o ON o.id = %(id)s AND o.valid_from = %(vf)s
WHERE j.horizon = 'near' AND j.work_window @> %(view)s::timestamptz AND ST_Intersects(j.geom, o.geom)
"""
ASSETS_SQL = """
SELECT a.org_id, count(*) AS n FROM asset a JOIN outlook o ON o.id = %(id)s AND o.valid_from = %(vf)s
WHERE ST_Intersects(a.geom, o.geom) GROUP BY a.org_id
"""
HOME_SQL = """
WITH h AS (SELECT ST_GeomFromText(%(home)s, 4326) AS g)
SELECT ST_Intersects(o.geom::geometry, h.g) AS home,
       ST_AsGeoJSON(ST_Envelope(ST_Intersection(o.geom::geometry, h.g)))::json AS env
FROM outlook o, h WHERE o.id = %(id)s AND o.valid_from = %(vf)s
"""
WATCH_SQL = """
SELECT e.id, e.payload,
       (SELECT count(DISTINCT coalesce(j.parent_job_id, j.id)) FROM job j WHERE e.geom IS NOT NULL AND j.horizon = 'near'
        AND j.work_window @> %(known)s::timestamptz AND ST_Intersects(j.geom, e.geom)) AS sites
FROM storm_event e
WHERE e.kind = 'nws_alert' AND coalesce(e.payload->>'mode', 'replay') = %(mode)s AND e.payload->>'label' ILIKE '%%watch%%'
  AND e.ts <= %(known)s AND (e.payload->>'expire')::timestamptz > %(known)s
"""
UTILITY = {"gpc": "Georgia Power", "desc": "DESC"}


def home_wkt(cache={}):
    """Georgia plus South Carolina, simplified. Falls back to their bounding box when the state layer is missing."""
    if "wkt" not in cache:
        path = ROOT / "data/layers/states/cb_2023_us_state_500k.shp"
        try:
            r = shapefile.Reader(str(path))
            states = [shape(s.__geo_interface__) for rec, s in zip(r.records(), r.shapes()) if rec["STUSPS"] in ("GA", "SC")]
            cache["wkt"] = unary_union(states).simplify(0.01).wkt
        except (shapefile.ShapefileException, OSError):
            cache["wkt"] = box(*HOME).wkt
    return cache["wkt"]


def nearest_city(lat, lon):
    return min(CITIES, key=lambda c: (c[1] - lat) ** 2 + ((c[2] - lon) * 0.85) ** 2)[0]


def day_label(view, known):
    d = (view.astimezone(ET).date() - known.astimezone(ET).date()).days
    return "Today" if d == 0 else "Tomorrow" if d == 1 else view.astimezone(ET).strftime("%A")


def clock(t):
    t = t.astimezone(ET)
    return f"{t.strftime('%A')} {t.hour % 12 or 12} {'AM' if t.hour < 12 else 'PM'}"


def pause_text(pause_at, known):
    if pause_at <= known:
        return "pause crane and line work now"
    d = (pause_at.astimezone(ET).date() - known.astimezone(ET).date()).days
    return f"pause crane and line work by noon {'today' if d == 0 else 'tomorrow' if d == 1 else pause_at.astimezone(ET).strftime('%A')}"


BASINS = [("the Caribbean", box(-89, 9, -59, 21.5)), ("the Gulf of Mexico", box(-98, 21.5, -81, 31)),
          ("the Atlantic off the Southeast coast", box(-81, 24, -70, 37))]


def basin_region(geom):
    """Named waters that hold at least a fifth of an outlook area."""
    names = [n for n, b in BASINS if geom.intersection(b).area >= 0.2 * geom.area]
    return " and ".join(names) if names else "the Atlantic"


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def exposure(sites, assets):
    """'12 active work sites and 40 substations (Georgia Power 30, DESC 10) inside'."""
    subs = sum(assets.values())
    parts = ", ".join(f"{UTILITY.get(k, k)} {n}" for k, n in sorted(assets.items(), key=lambda x: -x[1]) if n)
    if not sites and not subs:
        return "no active work sites or substations inside"
    s = plural(len(sites), "active work site") if sites else "no active work sites"
    return f"{s} and {plural(subs, 'substation')}{f' ({parts})' if parts else ''} inside"


def describe(f):
    """Plain sentence from computed facts, so the wording is testable without a database."""
    where = exposure(f.get("sites", []), f.get("assets", {}))
    if f["kind"] in ("severe", "severe48"):
        act = f"; {pause_text(f['pause_at'], f['known'])}" if f.get("work_sites") else ""
        return f"{f['day']}: severe storms possible ({f['label']}) around {f['city']}; {where}{act}"
    if f["kind"] == "flood":
        act = "; plan crews around low-lying access roads" if f.get("sites") else ""
        return f"{f['day']}: flash flooding possible ({f['label']}) around {f['city']}; {where}{act}"
    if f["kind"] == "wind":
        act = "; line up storm crews and secure laydown yards" if f.get("sites") else ""
        return f"{f['level']} or higher chance of tropical-storm-force winds around {f['city']} in the next 5 days (NHC); {where}{act}"
    if f["kind"] == "tropical":
        return f"NHC gives a {f['prob']} chance of a tropical storm forming in {f['region']} within 7 days ({f['risk'].lower()} risk)"
    if f["kind"] == "watch":
        return f"{f['label']} until {clock(f['until'])} for {f['places']}; {plural(f.get('n_sites', 0), 'active work site')} inside"
    return f.get("label", "")


def _facts(conn, r, view):
    ids = {"id": r["id"], "vf": r["valid_from"], "view": view}
    home = conn.execute(HOME_SQL, {**ids, "home": home_wkt()}).fetchone()
    if not home or not home["home"]:
        return None
    by_project = {}
    for s in conn.execute(SITES_SQL, ids).fetchall():
        by_project.setdefault(s["project"], s)  # phases of one project count once
    sites = list(by_project.values())
    assets = {a["org_id"]: a["n"] for a in conn.execute(ASSETS_SQL, ids).fetchall()}
    ring = home["env"]["coordinates"][0] if home["env"] and home["env"].get("coordinates") else [[HOME[0], HOME[1]], [HOME[2], HOME[3]]]
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    if sites:
        lats, lons = [s["lat"] for s in sites], [s["lon"] for s in sites]
        lat, lon = sum(lats) / len(lats), sum(lons) / len(lons)
    else:
        lat, lon = (min(ys) + max(ys)) / 2, (min(xs) + max(xs)) / 2
    return {"sites": [s["name"] for s in sites], "work_sites": [s["name"] for s in sites if s["phase"] in WORK_PHASES],
            "assets": assets, "city": nearest_city(lat, lon), "bbox": [min(xs), min(ys), max(xs), max(ys)]}


def _item(kind, product, r, view, known, facts, **extra):
    f = {"kind": kind, "day": day_label(view, known), "label": r["label"], "level": r["level"], "known": known, **facts, **extra}
    return {"id": f"{product}-{view:%Y%m%d}-{r['level']}", "kind": kind, "product": product, "level": r["level"], "rank": r["rank"],
            "when": view.isoformat(), "day": f["day"], "text": describe(f), "sites": facts.get("sites", []),
            "assets": facts.get("assets", {}), "bbox": facts.get("bbox"), "issued": r["issued"].isoformat()}


def _pick(conn, rows, view):
    """Worst level that reaches a work site, else the worst level over ga/sc."""
    fallback = None
    for r in sorted(rows, key=lambda x: -x["rank"]):
        facts = _facts(conn, r, view)
        if facts and facts["sites"]:
            return r, facts
        fallback = fallback or (facts and (r, facts))
    return fallback


def heads_up(conn, known, mode, days=7):
    """What is coming in the next week, in plain sentences, soonest first."""
    items = []
    for i in range(days):
        local = (known.astimezone(ET) + timedelta(days=i)).date()
        view = max(datetime(local.year, local.month, local.day, PEAK_HOUR, tzinfo=ET).astimezone(timezone.utc), known)
        pause_at = datetime(local.year, local.month, local.day, PAUSE_HOUR, tzinfo=ET).astimezone(timezone.utc)
        by_product = {}
        for r in rows_at(conn, view, known, mode):
            by_product.setdefault(r["product"], []).append(r)
        for product, kind in (("spc", "severe"), ("spc48", "severe48"), ("wpc_ero", "flood")):
            pick = _pick(conn, by_product.get(product, []), view)
            if pick:
                items.append(_item(kind, product, pick[0], view, known, pick[1], pause_at=pause_at))
    now_rows = rows_at(conn, known, known, mode)
    pick = _pick(conn, [r for r in now_rows if r["product"] == "nhc_wsp"], known)
    if pick:
        items.append(_item("wind", "nhc_wsp", pick[0], known, known, pick[1]))
    for r in now_rows:
        if r["product"] != "nhc_gtwo":
            continue
        g = shape(conn.execute("SELECT ST_AsGeoJSON(geom)::json AS g FROM outlook WHERE id = %s AND valid_from = %s",
                               (r["id"], r["valid_from"])).fetchone()["g"])
        if g.centroid.x < -98 or g.centroid.x > -65:
            continue  # the open Atlantic is weeks away from ga and sc if it comes at all
        facts = {"sites": [], "assets": {}, "bbox": list(g.bounds)}
        items.append(_item("tropical", "nhc_gtwo", r, known, known, facts, prob=r["props"].get("prob7day"),
                           risk=r["props"].get("risk7day", "Low"), region=basin_region(g)))
    for w in conn.execute(WATCH_SQL, {"mode": mode, "known": known}).fetchall():
        p = w["payload"]
        until = datetime.fromisoformat(str(p["expire"]).replace("Z", "+00:00"))
        places = p.get("places") or ""
        text = describe({"kind": "watch", "label": p.get("label"), "until": until, "places": places if len(places) < 90 else places[:87] + "...",
                         "n_sites": w["sites"]})
        items.append({"id": f"watch-{w['id']}", "kind": "watch", "product": "nws_watch", "level": p.get("label"), "rank": 3,
                      "when": known.isoformat(), "day": "Now", "text": text, "sites": [], "assets": {}, "bbox": None, "issued": None})
    order = {"watch": 0, "wind": 1, "severe": 2, "flood": 2, "severe48": 3, "tropical": 4}
    items.sort(key=lambda x: (x["when"][:10], order[x["kind"]], -x["rank"]))
    return items




def available(conn, mode):
    """Which products exist for a mode, so the UI can say what is missing instead of guessing."""
    rows = conn.execute("SELECT product, count(*) AS n, min(valid_from) AS first, max(valid_to) AS last FROM outlook WHERE mode = %s GROUP BY product", (mode,)).fetchall()
    have = {r["product"]: {"n": r["n"], "first": r["first"].isoformat(), "last": r["last"].isoformat()} for r in rows}
    if mode == "replay" and "wpc_ero" not in have:
        have["wpc_ero"] = {"n": 0, "note": "WPC does not publish an archive of rainfall outlook shapes"}
    return have
