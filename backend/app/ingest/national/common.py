"""Shared loader for regional planner lists: register the utility and source file, place each project, keep the whole row."""
import hashlib
import io
import json
import re
import zipfile
from datetime import date, datetime
from functools import lru_cache

from dateutil.relativedelta import relativedelta
import shapefile
from rapidfuzz import fuzz, process
from shapely.geometry import shape

from app.config import DEFAULT_DURATION_MONTHS
from app.db import ROOT
from app.geo.geolocate import km, norm

MATCH_MIN = 90  # name similarity needed to trust an osm substation
MAX_SPAN_KM = 250  # longest plausible line in a regional plan
COUNTY_CONF = 0.3  # a county centroid is only an area, never a site
PALETTE = ["#00a6a6", "#e07a1f", "#8e44ad", "#2e9e4f", "#d6336c", "#1c7ed6", "#b8860b", "#5c7cfa", "#c2255c", "#0ca678",
           "#f76707", "#7048e8", "#37b24d", "#e64980", "#1098ad", "#a61e4d", "#74b816", "#3b5bdb", "#d9480f", "#9c36b5"]


def color_for(org_id):
    return PALETTE[int(hashlib.md5(org_id.encode()).hexdigest(), 16) % len(PALETTE)]  # stable per utility


def register_org(conn, org_id, name, short, state, planner, login):
    conn.execute("""INSERT INTO org (id, name, kind, color, state, planner, short, login) VALUES (%s, %s, 'utility', %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, state = EXCLUDED.state, planner = EXCLUDED.planner,
                    short = EXCLUDED.short, login = EXCLUDED.login""", (org_id, name, color_for(org_id), state, planner, short, login))


def register_source(conn, org_id, title, url, path, planner, edition):
    full = ROOT / path
    sha = hashlib.sha256(full.read_bytes()).hexdigest()
    row = conn.execute("SELECT id FROM source_doc WHERE org_id = %s AND sha256 = %s", (org_id, sha)).fetchone()
    if row:
        return row["id"]
    return conn.execute("""INSERT INTO source_doc (org_id, title, url, local_path, kind, ceii_flag, planner, edition, sha256)
                           VALUES (%s, %s, %s, %s, 'regional_plan', FALSE, %s, %s, %s) RETURNING id""",
                        (org_id, title, url, str(path), planner, edition, sha)).fetchone()["id"]


@lru_cache
def stations(state):
    path = ROOT / f"data/layers/osm_states/{state}.json"
    rows = json.loads(path.read_text()) if path.exists() else []
    return [r for r in rows if r.get("name")], [norm(r["name"]) for r in rows if r.get("name")]


COMPASS = {"north", "south", "east", "west", "n", "s", "e", "w", "ne", "nw", "se", "sw", "northeast", "northwest", "southeast", "southwest", "upper", "lower", "new", "old"}


def same_compass(a, b):
    return {w for w in a.split() if w in COMPASS} == {w for w in b.split() if w in COMPASS}  # "west devon" is not "east devon"


def find_station(name, states):
    """Best osm substation for a planner's station name in the given states, or None when unsure."""
    key = norm(re.sub(r"\b\d+(\.\d+)?\s*kv\b|\bckt\b.*|\bline\b.*", " ", str(name), flags=re.I))  # "crooked lake 161kv" -> "crooked lake"
    if len(key) < 3:
        return None
    best = None
    for st in states:
        rows, keys = stations(st)
        hits = process.extract(key, keys, scorer=fuzz.token_sort_ratio, limit=3, score_cutoff=MATCH_MIN)
        for _, score, i in hits:
            if not same_compass(key, keys[i]):
                continue
            if not best or score > best["score"]:
                best = {**rows[i], "score": score}
            elif score == best["score"] and km((rows[i]["lat"], rows[i]["lon"]), (best["lat"], best["lon"])) > 15:
                best = {**best, "ambiguous": True}  # two far apart stations share the name
    if not best:  # "el dorado donan" vs "donan": accept a subset match only when it is the one station that fits
        hits = [(rows[i], st) for st in states for rows, keys in [stations(st)] for i, k in enumerate(keys)
                if len(k) >= 5 and len(key) >= 5 and key.split()[-1] in k.split() and same_compass(key, k) and fuzz.token_set_ratio(key, k) >= 97]  # the distinctive word must match
        spots = {(round(r["lat"], 2), round(r["lon"], 2)) for r, _ in hits}
        if len(spots) == 1:
            best = {**hits[0][0], "score": 85.0}
    return None if not best or best.get("ambiguous") else best


@lru_cache
def county_centroids():
    z = zipfile.ZipFile(ROOT / "data/layers/counties_20m.zip")
    base = next(n for n in z.namelist() if n.endswith(".shp"))[:-4]
    r = shapefile.Reader(shp=io.BytesIO(z.read(base + ".shp")), dbf=io.BytesIO(z.read(base + ".dbf")))
    out = {}
    for rec, shp in zip(r.records(), r.shapes()):
        c = shape(shp.__geo_interface__).centroid
        out[(rec["STUSPS"], rec["NAME"].lower())] = (c.y, c.x)
    return out


def find_county(name, states):
    key = str(name or "").lower().replace(" county", "").replace(" parish", "").strip()
    return next(({"lat": c[0], "lon": c[1], "county": key, "state": st} for st in states if (c := county_centroids().get((st, key)))), None)


def job_type(text, has_two_ends):
    t = (text or "").lower()
    if any(w in t for w in ("substation", "transformer", "xfmr", "capacitor", "breaker", "statcom", "reactor", "switching station")) and not has_two_ends:
        return "substation"
    if any(w in t for w in ("new ", "construct", "build ")) and has_two_ends:
        return "new_line"
    return "line_upgrade"


def window(kind, start, in_service):
    """Build window: the planner's start when given, else a typical duration before in-service."""
    if start and in_service and start < in_service:
        return start, in_service, "filed"
    return in_service - relativedelta(months=DEFAULT_DURATION_MONTHS[kind]), in_service, "default_duration"


def to_date(v):
    if v is None or v == "" or (isinstance(v, float) and v != v):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return datetime.fromisoformat(str(v)[:10]).date()
    except ValueError:
        return None


def clean(v):
    """JSON-safe copy of a source cell."""
    if v is None or (isinstance(v, float) and v != v):
        return None
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v if isinstance(v, (int, float, str, bool)) else str(v)


UPSERT = """
INSERT INTO job (id, org_id, name, ref, description, horizon, job_type, voltage_kv, endpoints, geom, geom_quality, work_window, window_basis,
                 in_service, cost_usd, source_doc_id, extraction, confidence, located_via, resources, state, planner, source_project_id,
                 status, need, length_mi, counties, raw)
VALUES (%(id)s, %(org_id)s, %(name)s, %(ref)s, %(description)s, 'long', %(job_type)s, %(voltage_kv)s, %(endpoints)s, ST_GeogFromText(%(wkt)s),
        %(quality)s, tstzrange(%(start)s, %(in_service)s), %(basis)s, %(in_service)s, %(cost_usd)s, %(doc)s, 'parser', %(conf)s, %(via)s,
        ARRAY['crews', 'row', 'staging'], %(state)s, %(planner)s, %(source_project_id)s, %(status)s, %(need)s, %(length_mi)s, %(counties)s, %(raw)s)
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description, job_type = EXCLUDED.job_type,
  voltage_kv = EXCLUDED.voltage_kv, endpoints = EXCLUDED.endpoints, geom = EXCLUDED.geom, geom_quality = EXCLUDED.geom_quality,
  work_window = EXCLUDED.work_window, window_basis = EXCLUDED.window_basis, in_service = EXCLUDED.in_service, cost_usd = EXCLUDED.cost_usd,
  source_doc_id = EXCLUDED.source_doc_id, confidence = EXCLUDED.confidence, located_via = EXCLUDED.located_via, status = EXCLUDED.status,
  need = EXCLUDED.need, length_mi = EXCLUDED.length_mi, counties = EXCLUDED.counties, raw = EXCLUDED.raw
"""


def save(conn, p, doc):
    """Place and store one normalized project; unplaceable ones go to job_review with the whole row.

    p: id, org_id, name, description, voltage_kv, in_service (date), start (date|None), status, need, length_mi, cost_usd,
       ends (station names), states (where to look), counties, source_project_id, planner, state, raw (dict)
    """
    ends = [e for e in (p.get("ends") or []) if e and str(e).strip()][:2]
    if not p.get("in_service"):
        conn.execute("INSERT INTO job_review (org_id, raw, reason, source_doc_id) VALUES (%s, %s, %s, %s)",
                     (p["org_id"], json.dumps(p["raw"]), "no in-service date", doc))
        return "review"
    picks = [find_station(e, p["states"]) for e in ends]
    found = [x for x in picks if x]
    if len(found) == 2 and found[0]["osm"] == found[1]["osm"]:
        found = found[:1]  # both names landed on one station: it is only a point
    if len(found) == 2 and km((found[0]["lat"], found[0]["lon"]), (found[1]["lat"], found[1]["lon"])) > MAX_SPAN_KM:
        found = found[:1]  # the second match is implausibly far: keep the first end only
    county = None if found else next((c for c in (find_county(n, p["states"]) for n in p.get("counties") or []) if c), None)
    if not found and not county:
        conn.execute("INSERT INTO job_review (org_id, raw, reason, source_doc_id) VALUES (%s, %s, %s, %s)",
                     (p["org_id"], json.dumps(p["raw"]), f"no osm substation matched {ends or 'no station names'}", doc))
        return "review"
    kind = job_type(f"{p['name']} {p.get('description') or ''}", len(ends) == 2)
    conf = round(min(x["score"] for x in found) / 100, 3) if found else COUNTY_CONF
    if county:  # no station matched, but the source names the county
        conf, found = COUNTY_CONF, []
        wkt, quality = f"POINT({county['lon']} {county['lat']})", "county_area"
    elif len(found) == 2:
        wkt, quality = f"LINESTRING({found[0]['lon']} {found[0]['lat']}, {found[1]['lon']} {found[1]['lat']})", "straight_line"
    else:
        wkt, quality = f"POINT({found[0]['lon']} {found[0]['lat']})", "partial_point" if len(ends) == 2 else "matched_point"
        conf = round(conf * (0.8 if len(ends) == 2 else 1), 3)
    start, end, basis = window(kind, p.get("start"), p["in_service"])
    via = [{"county": county["county"], "state": county["state"], "centroid": True}] if county else [{"query": e, "osm": x["osm"], "name": x["name"], "score": x["score"]} if x else {"query": e, "found": False} for e, x in zip(ends, picks)]
    conn.execute(UPSERT, {**{k: p.get(k) for k in ("id", "org_id", "name", "description", "voltage_kv", "cost_usd", "state", "planner",
                                                   "source_project_id", "status", "need", "length_mi", "counties")},
                          "ref": p.get("source_project_id"), "job_type": kind, "endpoints": ends, "wkt": wkt, "quality": quality,
                          "start": start, "in_service": end, "basis": basis, "doc": doc, "conf": conf, "via": json.dumps(via),
                          "raw": json.dumps(p["raw"])})
    return "placed"


def clear(conn, org_id):
    """Drop a utility's earlier load so a rerun is clean (its overlaps are rebuilt afterwards)."""
    conn.execute("DELETE FROM opportunity WHERE job_a IN (SELECT id FROM job WHERE org_id = %(o)s) OR job_b IN (SELECT id FROM job WHERE org_id = %(o)s)",
                 {"o": org_id})
    conn.execute("DELETE FROM job WHERE org_id = %s", (org_id,))
    conn.execute("DELETE FROM job_review WHERE org_id = %s", (org_id,))
