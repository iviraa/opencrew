import json
import math
import re
from collections import Counter

import httpx
from shapely import STRtree
from shapely.geometry import LineString, Point, shape
from shapely.ops import transform

from app.db import ROOT

RAW = ROOT / "data/raw/hazards"
HEADERS = {"User-Agent": "opencrew/0.1 (hackathon)"}
HURDAT_DIR = "https://www.nhc.noaa.gov/data/hurdat/"
NFHL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
SINCE = 1950  # tracks before aircraft recon are too rough to count
RADIUS_KM = 80.5  # 50 miles
HURRICANE_FLAG = 5  # hurricanes within 50 miles since 1950 that make a site worth planning around
KM_LAT, KM_LON = 110.57, 111.32 * math.cos(math.radians(32.5))  # flat projection good enough across ga and sc
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def km(geom):
    return transform(lambda x, y, z=None: (x * KM_LON, y * KM_LAT), geom)


def parse_hurdat(text, since=SINCE):
    """HURDAT2 Atlantic best tracks. Returns [{id, name, year, points: [(lon, lat, status, month)]}]."""
    storms, cur = [], None
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3 and re.match(r"^AL\d{6}$", parts[0]):
            cur = {"id": parts[0], "name": parts[1].title(), "year": int(parts[0][4:]), "points": []}
            storms.append(cur)
        elif cur is not None and len(parts) >= 8 and parts[0][:4].isdigit():
            lat = float(parts[4][:-1]) * (1 if parts[4].endswith("N") else -1)
            lon = float(parts[5][:-1]) * (-1 if parts[5].endswith("W") else 1)
            cur["points"].append((lon, lat, parts[3], int(parts[0][4:6])))
    return [s for s in storms if s["year"] >= since and len(s["points"]) >= 1]


def track_pieces(storms):
    """One piece per track segment, tagged with storm, whether it was a hurricane, and the month."""
    geoms, meta = [], []
    for s in storms:
        pts = s["points"]
        for a, b in zip(pts, pts[1:] or pts):
            g = LineString([(a[0], a[1]), (b[0], b[1])]) if a[:2] != b[:2] else Point(a[0], a[1])
            geoms.append(km(g))
            meta.append((s["id"], a[2] == "HU" or b[2] == "HU", a[3]))
    return geoms, meta


def climatology(geom, tree, geoms, meta, radius=RADIUS_KM):
    """Storms and hurricanes whose track passed within `radius` of the site."""
    g = km(geom)
    storms, hurricanes, months = set(), set(), Counter()
    for i in tree.query(g.buffer(radius)):
        if geoms[i].distance(g) <= radius:
            sid, hu, month = meta[i]
            if sid not in storms:
                months[month] += 1
            storms.add(sid)
            if hu:
                hurricanes.add(sid)
    return {"storms_50mi": len(storms), "hurricanes_50mi": len(hurricanes), "peak_month": months.most_common(1)[0][0] if months else None}


def parse_nfhl(saved):
    """FEMA flood zones the site touches. `saved` is {sfha: query of 100-year zones, mapped: count of any zone}.
    Returns (in_floodplain, zones); in_floodplain is None when FEMA has no flood map there."""
    zones = sorted({f["attributes"]["FLD_ZONE"] for f in saved["sfha"].get("features", []) if f["attributes"].get("FLD_ZONE")})
    if zones:
        return True, zones
    return (False, []) if saved.get("mapped") else (None, [])


def esri(geom):
    g = geom.simplify(0.002) if geom.geom_type == "LineString" else geom
    if g.geom_type == "Point":
        return {"x": g.x, "y": g.y, "spatialReference": {"wkid": 4326}}, "esriGeometryPoint"
    return {"paths": [list(g.coords)], "spatialReference": {"wkid": 4326}}, "esriGeometryPolyline"


def nfhl(geom, kind, **params):
    extra = {"distance": 100, "units": "esriSRUnit_Meter"} if kind == "esriGeometryPoint" else {}  # the service rejects a distance on lines
    r = httpx.post(NFHL, data={"geometry": json.dumps(geom), "geometryType": kind, "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
                               "returnGeometry": "false", "f": "json", **extra, **params}, headers=HEADERS, timeout=90)
    data = r.json()
    if "error" in data:
        raise httpx.HTTPError(str(data["error"])[:120])
    return data


def floodplain(job_id, geom, refresh=False):
    path = RAW / f"nfhl_{job_id}.json"
    if refresh or not path.exists():
        g, kind = esri(geom)
        saved = {"sfha": nfhl(g, kind, where="SFHA_TF = 'T'", outFields="FLD_ZONE")}
        if not saved["sfha"].get("features"):
            saved["mapped"] = nfhl(g, kind, where="1=1", returnCountOnly="true").get("count", 0)
        RAW.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(saved))
    return parse_nfhl(json.loads(path.read_text()))


def hurdat_text():
    cached = sorted(RAW.glob("hurdat2-1851-*.txt"))
    if cached:
        return cached[-1].read_text()
    names = sorted(set(re.findall(r"hurdat2-1851-\d{4}-\d+\.txt", httpx.get(HURDAT_DIR, headers=HEADERS, timeout=60).text)),
                   key=lambda n: (n.split("-")[2], len(n.split("-")[3]), n.split("-")[3]))
    text = httpx.get(HURDAT_DIR + names[-1], headers=HEADERS, timeout=120).text
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / names[-1]).write_text(text)
    return text


def compute(conn, refresh=False):
    """Floodplain and hurricane history for every long-range job. Stored by job id so reloads keep it."""
    storms = parse_hurdat(hurdat_text())
    geoms, meta = track_pieces(storms)
    tree = STRtree(geoms)
    jobs = conn.execute("SELECT id, ST_AsGeoJSON(geom)::json AS g FROM job WHERE horizon = 'long'").fetchall()
    out = {"jobs": len(jobs), "flood_errors": 0}
    for j in jobs:
        geom = shape(j["g"])
        clim = climatology(geom, tree, geoms, meta)
        try:
            sfha, zones = floodplain(j["id"], geom, refresh)
        except (httpx.HTTPError, ValueError) as e:
            sfha, zones, out["flood_errors"] = None, [], out["flood_errors"] + 1
            print("nfhl", j["id"], str(e)[:80])
        conn.execute("""INSERT INTO job_hazard (job_id, in_floodplain, flood_zones, hurricanes_50mi, storms_50mi, peak_month, since_year, checked_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, now())
                        ON CONFLICT (job_id) DO UPDATE SET in_floodplain = EXCLUDED.in_floodplain, flood_zones = EXCLUDED.flood_zones,
                          hurricanes_50mi = EXCLUDED.hurricanes_50mi, storms_50mi = EXCLUDED.storms_50mi, peak_month = EXCLUDED.peak_month,
                          since_year = EXCLUDED.since_year, checked_at = now()""",
                     (j["id"], sfha, zones, clim["hurricanes_50mi"], clim["storms_50mi"], clim["peak_month"], SINCE))
    return out


def describe(h, year=2026):
    """Plain facts for one job: flags plus sentences."""
    years = year - (h.get("since_year") or SINCE)
    hu = h.get("hurricanes_50mi") or 0
    flags = {"in_floodplain": h.get("in_floodplain"), "hurricane_exposure": hu >= HURRICANE_FLAG}
    lines = []
    if h.get("in_floodplain") is None:
        lines.append("FEMA has no flood map here")
    elif h["in_floodplain"]:
        special = [z for z in h.get("flood_zones") or [] if z.startswith(("A", "V"))]
        lines.append(f"Crosses a FEMA 100-year floodplain (zone {', '.join(special)})")
    else:
        lines.append("Outside the FEMA 100-year floodplain")
    if hu:
        every = years / hu
        lines.append(f"{hu} hurricane{'s' if hu != 1 else ''} passed within 50 miles since {h.get('since_year') or SINCE}, about one every {round(every)} years")
    else:
        lines.append(f"No hurricane passed within 50 miles since {h.get('since_year') or SINCE}")
    if h.get("peak_month"):
        lines.append(f"Storms here peak in {MONTHS[h['peak_month'] - 1]}; avoid long outages then")
    return {**flags, "lines": lines}


HAZARD_SQL = """SELECT h.*, j.name FROM job_hazard h JOIN job j ON j.id = h.job_id"""


def all_hazards(conn):
    return {r["job_id"]: {**{k: r[k] for k in ("in_floodplain", "flood_zones", "hurricanes_50mi", "storms_50mi", "peak_month", "since_year")},
                          "name": r["name"], **describe(r)} for r in conn.execute(HAZARD_SQL).fetchall()}


def one(conn, job_id):
    r = conn.execute(HAZARD_SQL + " WHERE h.job_id = %s OR h.job_id = (SELECT parent_job_id FROM job WHERE id = %s)", (job_id, job_id)).fetchone()
    if not r:
        return None
    return {**{k: r[k] for k in ("job_id", "name", "in_floodplain", "flood_zones", "hurricanes_50mi", "storms_50mi", "peak_month", "since_year")}, **describe(r)}
