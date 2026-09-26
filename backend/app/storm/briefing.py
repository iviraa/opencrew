import io
import json
import math
import zipfile
from datetime import datetime, timedelta, timezone
from functools import cache

import httpx
import shapefile
from shapely.geometry import MultiPoint, Point, mapping, shape
from shapely.ops import nearest_points, unary_union

from app.db import ROOT
from app.geo.drive import CACHE as DRIVE_CACHE, HEADERS, OSRM
from app.storm import helene

FCST = "https://www.nhc.noaa.gov/gis/forecast/archive/al092024_fcst_{n:03d}.zip"
COUNTIES = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_20m.zip"
NM_KM = 1.852
DEFAULTS = {"safety_margin_h": 12, "crews_per_substation": 0.2, "max_drive_min": 45, "default_r34_nm": 150}
ORG_NAME = {"desc": "Dominion Energy SC", "gpc": "Georgia Power"}
QUADS = ("NE", "SE", "SW", "NW")


def fldate(text):
    """'2024-09-27 2:00 AM Fri EDT' -> utc datetime."""
    date, clock, ampm, _, tz = text.split()
    local = datetime.strptime(f"{date} {clock} {ampm}", "%Y-%m-%d %I:%M %p")
    return (local - timedelta(hours=helene.TZ[tz])).replace(tzinfo=timezone.utc)


@cache
def advisories():
    """Every Helene advisory: issue time, forecast points and 34/64-kt radii per forecast hour."""
    out = []
    for n in range(1, 30):
        cone = helene.fetch(helene.CONE.format(n=n), f"cone_{n:03d}.zip")
        if not cone:
            continue
        pts = helene.read_shp(cone, "_5day_pts")
        pgn = helene.read_shp(cone, "_5day_pgn")
        if not pts or not pgn:
            continue
        radii = {}
        fz = helene.fetch(FCST.format(n=n), f"fcst_{n:03d}.zip")
        for rec, _ in (helene.read_shp(fz, "_forecastradii") if fz else []):
            valid = datetime.strptime(str(rec["VALIDTIME"]), "%Y%m%d%H").replace(tzinfo=timezone.utc)
            radii[(valid, int(rec["RADII"]))] = {q: float(rec[q] or 0) for q in QUADS}
        points = sorted(({"t": fldate(r["FLDATELBL"]), "lon": g.x, "lat": g.y, "wind_kt": r["MAXWIND"], "label": r["TCDVLP"]} for r, g in pts),
                        key=lambda p: p["t"])
        for p in points:
            p["r34"] = radii.get((p["t"], 34))
            p["r50"] = radii.get((p["t"], 50))
            p["r64"] = radii.get((p["t"], 64))
        out.append({"advisory": pgn[0][0]["ADVISNUM"], "issued": helene.adv_time(pgn[0][0]["ADVDATE"]), "cone": pgn[0][1],
                    "points": points, "has_radii": bool(radii)})
    return sorted(out, key=lambda a: a["issued"])


def advisory_at(t):
    live = [a for a in advisories() if a["issued"] <= t]
    return live[-1] if live and t <= helene.REPLAY[1] else None


def radius_km(r, bearing, fallback_nm):
    """Wind radius toward a bearing, from the quadrant values (nm)."""
    if r is None:
        return fallback_nm * NM_KM
    return r[QUADS[int(((bearing % 360)) // 90)]] * NM_KM


def km(a_lon, a_lat, b_lon, b_lat):
    la1, la2 = math.radians(a_lat), math.radians(b_lat)
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(math.radians(b_lon - a_lon) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def bearing(a_lon, a_lat, b_lon, b_lat):
    y = math.sin(math.radians(b_lon - a_lon)) * math.cos(math.radians(b_lat))
    x = math.cos(math.radians(a_lat)) * math.sin(math.radians(b_lat)) - math.sin(math.radians(a_lat)) * math.cos(math.radians(b_lat)) * math.cos(math.radians(b_lon - a_lon))
    return math.degrees(math.atan2(y, x))


def hourly(adv, key="r34", fallback_nm=None):
    """Storm center and wind radius for every hour of the forecast (linear between forecast points)."""
    pts = adv["points"]
    for a, b in zip(pts, pts[1:]):
        hours = max(1, int((b["t"] - a["t"]).total_seconds() // 3600))
        for h in range(hours):
            f = h / hours
            ra, rb = a[key], b[key]
            r = None if ra is None and rb is None else {q: (1 - f) * (ra or {q: 0 for q in QUADS})[q] + f * (rb or {q: 0 for q in QUADS})[q] for q in QUADS}
            yield a["t"] + timedelta(hours=h), a["lon"] + f * (b["lon"] - a["lon"]), a["lat"] + f * (b["lat"] - a["lat"]), r


def arrival(adv, lon, lat, key="r34", fallback_nm=None):
    """First forecast hour when the wind radius covers the point."""
    for t, clon, clat, r in hourly(adv, key):
        if r is None and fallback_nm is None:
            continue
        if km(clon, clat, lon, lat) <= radius_km(r, bearing(clon, clat, lon, lat), fallback_nm):
            return t
    return None


def band(adv, key="r34", fallback_nm=None):
    """Area the wind field sweeps over: hull of consecutive radius circles, from the forecast radii."""
    shapes = []
    for t, clon, clat, r in hourly(adv, key):
        if r is None and fallback_nm is None:
            continue
        ring = []
        for deg in range(0, 360, 15):
            d = radius_km(r, deg, fallback_nm)
            if d <= 0:
                ring.append((clon, clat))
                continue
            ring.append((clon + d * math.sin(math.radians(deg)) / (111.32 * math.cos(math.radians(clat))), clat + d * math.cos(math.radians(deg)) / 110.57))
        hull = MultiPoint(ring).convex_hull
        if hull.area > 0:  # zero radius gives a point, not an area
            shapes.append(hull)
    return unary_union(shapes) if shapes else None


@cache
def counties():
    path = ROOT / "data/layers/counties_20m.zip"
    if not path.exists():
        path.write_bytes(httpx.get(COUNTIES, headers=HEADERS, timeout=120, follow_redirects=True).raise_for_status().content)
    z = zipfile.ZipFile(path)
    base = next(n[:-4] for n in z.namelist() if n.endswith(".shp"))
    r = shapefile.Reader(shp=io.BytesIO(z.read(base + ".shp")), dbf=io.BytesIO(z.read(base + ".dbf")))
    return [(f"{rec['NAME']} County, {rec['STUSPS']}", shape(s.__geo_interface__)) for rec, s in zip(r.records(), r.shapes()) if rec["STATEFP"] in ("13", "45")]


def county_of(lon, lat):
    p = Point(lon, lat)
    return next((name for name, g in counties() if g.contains(p)), "Outside GA/SC")


def drive_table(sources, targets):
    """Road minutes from each source to each target (one OSRM table call, cached)."""
    key = "table:" + ";".join(f"{x:.3f},{y:.3f}" for x, y in sources) + "|" + ";".join(f"{x:.3f},{y:.3f}" for x, y in targets)
    cache_data = json.loads(DRIVE_CACHE.read_text()) if DRIVE_CACHE.exists() else {}
    if key not in cache_data:
        coords = ";".join(f"{x:.5f},{y:.5f}" for x, y in [*sources, *targets])
        params = {"sources": ";".join(map(str, range(len(sources)))), "destinations": ";".join(str(len(sources) + i) for i in range(len(targets)))}
        try:
            r = httpx.get(f"{OSRM}/table/v1/driving/{coords}", params=params, headers=HEADERS, timeout=30)
            secs = r.json()["durations"]
        except (httpx.HTTPError, ValueError, KeyError):
            return [[None] * len(targets) for _ in sources]  # routing down: callers fall back to straight-line estimates
        cache_data[key] = [[None if s is None else round(s / 60, 1) for s in row] for row in secs]
        DRIVE_CACHE.write_text(json.dumps(cache_data))
    return cache_data[key]


def hours_text(h):
    if h < 1:
        return "less than an hour"
    return f"{round(h)} hour{'s' if round(h) != 1 else ''}"


def stamp(t):
    return t.astimezone(timezone(timedelta(hours=-4))).strftime("%a %b %-d, %-I %p ET")


ASSETS_SQL = "SELECT id, org_id, name, ST_X(geom::geometry) AS lon, ST_Y(geom::geometry) AS lat FROM asset"
ACTIVE_SQL = """
SELECT j.id, j.org_id, j.name, j.phase, j.parent_job_id,
       ST_X(ST_PointOnSurface(j.geom::geometry)) AS lon, ST_Y(ST_PointOnSurface(j.geom::geometry)) AS lat
FROM job j WHERE j.horizon = 'near' AND j.work_window @> %(t)s::timestamptz AND j.phase <> 'survey & permitting'
"""


def build(conn, t, scenario="helene", options=None):
    opt = {**DEFAULTS, **{k: float(v) for k, v in (options or {}).items() if k in DEFAULTS}}
    if scenario != "helene":
        return {"storm": None, "reason": "No active storm near Georgia or South Carolina."}
    adv = advisory_at(t)
    if not adv:
        return {"storm": None, "reason": "No NHC forecast for this time."}
    fb = None if adv["has_radii"] else opt["default_r34_nm"]
    b34, b50, b64 = band(adv, "r34", fb), band(adv, "r50"), band(adv, "r64")
    cone = adv["cone"]
    assets = conn.execute(ASSETS_SQL).fetchall()

    hit, hit_rows = {}, {"desc": [], "gpc": []}
    for a in assets:
        p = Point(a["lon"], a["lat"])
        h = hit.setdefault(a["org_id"], {"org": a["org_id"], "name": ORG_NAME.get(a["org_id"], a["org_id"]), "in_cone": 0,
                                         "tropical_storm_winds": 0, "damaging_winds": 0, "hurricane_winds": 0, "counties": {}})
        h["in_cone"] += cone.contains(p)
        h["tropical_storm_winds"] += bool(b34 is not None and b34.contains(p))
        if b50 is not None and b50.contains(p):  # 50 kt and up is where lines and poles usually break
            h["damaging_winds"] += 1
            hit_rows.setdefault(a["org_id"], []).append(a)
            c = county_of(a["lon"], a["lat"])
            h["counties"][c] = h["counties"].get(c, 0) + 1
            h["hurricane_winds"] += bool(b64 is not None and b64.contains(p))
    for h in hit.values():
        h["counties"] = [{"county": k, "substations": v} for k, v in sorted(h["counties"].items(), key=lambda kv: -kv[1])[:6]]
        h["sentence"] = (f"{h['damaging_winds']} {h['name']} substations are forecast to get damaging winds (50 knots or more)"
                         + (f", {h['hurricane_winds']} of them hurricane-force" if h["hurricane_winds"] else "")
                         + f"; {h['tropical_storm_winds']} will see at least tropical-storm winds.")

    first = None  # earliest tropical-storm winds over any utility substation
    for org_rows in hit_rows.values():
        for a in org_rows:
            at = arrival(adv, a["lon"], a["lat"], "r34", fb)
            if at and (first is None or at < first[0]):
                first = (at, a)

    pause = []
    for s in conn.execute(ACTIVE_SQL, {"t": t}).fetchall():
        at = arrival(adv, s["lon"], s["lat"], "r34", fb)
        if not at:
            continue
        by = at - timedelta(hours=opt["safety_margin_h"])
        left = (by - t).total_seconds() / 3600
        status = "stop now" if left <= 0 else "pause soon" if left <= 24 else "watch"
        pause.append({"job_id": s["id"], "project": s["name"], "org": s["org_id"], "phase": s["phase"], "lon": s["lon"], "lat": s["lat"],
                      "arrival": at.isoformat(), "pause_by": by.isoformat(), "hours_left": round(left, 1), "status": status,
                      "sentence": (f"Tropical-storm winds reach the {s['phase']} site of {s['name']} around {stamp(at)}. "
                                   + (f"Stop crane and line work now." if left <= 0 else f"Pause crane and line work by {stamp(by)} ({hours_text(left)} from now)."))})
    pause.sort(key=lambda p: p["pause_by"])

    staging = suggest_staging(hit_rows, b64 if b64 is not None else b50, opt)  # yards sit outside the hurricane-force winds
    crews = {}
    for org, h in hit.items():
        n = math.ceil(h["damaging_winds"] * opt["crews_per_substation"])
        crews[org] = {"org": org, "name": h["name"], "substations": h["damaging_winds"], "crews": n,
                      "sentence": f"Have {n} crews ready for {h['name']} ({h['damaging_winds']} substations in the damaging-wind zone, {opt['crews_per_substation']:g} crews each)."}

    hours_to = (first[0] - t).total_seconds() / 3600 if first else None
    who = ORG_NAME.get(first[1]["org_id"], "") if first else ""
    headline = (f"Helene brings tropical-storm winds to {who} substations in {hours_text(hours_to)}" if first and hours_to > 0
                else f"Helene's tropical-storm winds are already over {who} substations" if first else "Helene's forecast wind field misses both utilities")
    return {
        "storm": {"name": "Helene", "advisory": adv["advisory"], "issued": adv["issued"].isoformat(), "at": t.isoformat(),
                  "first_winds": first[0].isoformat() if first else None, "hours_to_first_winds": None if hours_to is None else round(hours_to, 1),
                  "radii_source": "NHC forecast wind radii" if adv["has_radii"] else f"assumed {opt['default_r34_nm']:g} nm radius",
                  "cone": mapping(cone), "wind_zone": mapping(b34) if b34 is not None else None, "damage_zone": mapping(b50) if b50 is not None else None,
                  "hurricane_zone": mapping(b64) if b64 is not None else None},
        "headline": headline,
        "likely_hit": [hit[o] for o in ("gpc", "desc") if o in hit],
        "pause": pause,
        "staging": staging,
        "crews": [crews[o] for o in ("gpc", "desc") if o in crews],
        "assumptions": {"safety_margin_h": {"value": opt["safety_margin_h"], "label": "Hours before winds to stop crane and line work"},
                        "crews_per_substation": {"value": opt["crews_per_substation"], "label": "Crews to ready per substation in the damaging-wind zone"},
                        "max_drive_min": {"value": opt["max_drive_min"], "label": "Longest drive from a staging yard"}},
    }


def clusters(rows, k=3):
    """Group a utility's hit substations into up to k areas (simple k-means on lon/lat, deterministic start)."""
    if not rows:
        return []
    pts = sorted(((r["lon"], r["lat"]) for r in rows))
    k = min(k, len(pts))
    centers = [pts[int(i * (len(pts) - 1) / max(1, k - 1))] for i in range(k)]
    for _ in range(12):
        groups = [[] for _ in centers]
        for p in pts:
            groups[min(range(len(centers)), key=lambda i: (p[0] - centers[i][0]) ** 2 + (p[1] - centers[i][1]) ** 2)].append(p)
        centers = [(sum(x for x, _ in g) / len(g), sum(y for _, y in g) / len(g)) if g else c for g, c in zip(groups, centers)]
    return [{"lon": c[0], "lat": c[1], "substations": len(g)} for c, g in zip(centers, groups) if g]


def suggest_staging(hit_rows, zone, opt):
    """Yards just outside the wind zone that reach both utilities' hit areas within the drive limit."""
    areas = [{**c, "org": org} for org, rows in hit_rows.items() for c in clusters(rows, 3 if len(rows) > 20 else 1)]
    if not areas or zone is None:
        return []
    cands = []
    for a in areas:  # stage at the area itself when it is outside the worst winds, else 15 km beyond the zone edge
        p = Point(a["lon"], a["lat"])
        if not zone.contains(p):
            cands.append((a["lon"], a["lat"]))
            continue
        near = nearest_points(zone.boundary, p)[0]
        dx, dy = near.x - a["lon"], near.y - a["lat"]
        norm = math.hypot(dx, dy) or 1
        c = (near.x + dx / norm * 0.15, near.y + dy / norm * 0.15)
        if zone.contains(Point(c)):
            c = (near.x - dx / norm * 0.15, near.y - dy / norm * 0.15)
        cands.append(c)
    table = drive_table(cands, [(a["lon"], a["lat"]) for a in areas])
    picked, covered = [], set()
    for _ in range(3):
        best = None
        for i, c in enumerate(cands):
            reach = {j for j, m in enumerate(table[i]) if m is not None and m <= opt["max_drive_min"] and j not in covered}
            orgs = {areas[j]["org"] for j in reach}
            score = (len(orgs) > 1, sum(areas[j]["substations"] for j in reach))
            if reach and (best is None or score > best[0]):
                best = (score, i, reach)
        if not best:
            break
        _, i, reach = best
        covered |= reach
        serves = [{"org": areas[j]["org"], "name": ORG_NAME.get(areas[j]["org"], areas[j]["org"]), "substations": areas[j]["substations"],
                   "minutes": table[i][j], "county": county_of(areas[j]["lon"], areas[j]["lat"])} for j in sorted(reach)]
        shared = len({s["org"] for s in serves}) > 1
        who = " and ".join(sorted({s["name"] for s in serves}))
        picked.append({"lon": cands[i][0], "lat": cands[i][1], "county": county_of(*cands[i]), "shared": shared, "serves": serves,
                       "sentence": (f"{'Shared yard' if shared else 'Staging yard'} near {county_of(*cands[i])}, outside the hurricane-force winds: "
                                    f"within {opt['max_drive_min']:g} minutes of {sum(s['substations'] for s in serves)} likely-hit substations for {who}.")})
    if not picked:  # nothing within the limit: offer the closest safe site per utility, with the real drive time
        for org in sorted({a["org"] for a in areas}):
            js = [j for j, a in enumerate(areas) if a["org"] == org]
            best = min(((table[i][j], i, j) for i in range(len(cands)) for j in js if table[i][j] is not None), default=None)
            if best:
                m, i, j = best
                picked.append({"lon": cands[i][0], "lat": cands[i][1], "county": county_of(*cands[i]), "shared": False,
                               "serves": [{"org": org, "name": ORG_NAME.get(org, org), "substations": areas[j]["substations"], "minutes": m,
                                           "county": county_of(areas[j]["lon"], areas[j]["lat"])}],
                               "sentence": f"Closest safe yard for {ORG_NAME.get(org, org)} is {round(m)} minutes from its hit area, beyond the {opt['max_drive_min']:g} minute goal."})
    return picked
