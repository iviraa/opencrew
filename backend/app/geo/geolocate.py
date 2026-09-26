import json
import math
import re

import openpyxl
import shapefile
from rapidfuzz import fuzz
from shapely.geometry import Point, shape
from shapely.prepared import prep

from app.db import ROOT
from app.geo import llm_pick
from app.geo.names import endpoint_names, foreign, mentioned_stations, stated_full_miles
from app.geo.nominatim import TOWN, geocode, lookup

HOME = {"desc": "SC", "gpc": "GA"}
MAX_SPAN_KM = 100  # longest plausible line in these filings
MIN_CONF = 0.6
TOWN_CONF = 0.35  # a town centroid is only an area, never a site
LLM_CONF = 0.6
OUT_OF_STATE = 0.6  # tie lines cross the border, so penalise instead of reject

OPERATORS = {"desc": re.compile(r"dominion|sce&g|south carolina electric", re.I), "gpc": re.compile(r"georgia power|southern", re.I)}
SWAPS = {"ft": "fort", "st": "saint", "mt": "mount", "jct": "junction", "sav": "savannah"}
NOISE = re.compile(r"\b(sub|substation|ss|switching|station|primary|tap|transmission|distribution|area|plant|steam|generating|tie|line)\b")


def squash(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def norm(name):
    s = re.sub(r"\(.*?\)|#\s*\d+|[^a-z0-9 ]", " ", (name or "").lower())
    s = " ".join(SWAPS.get(w, w) for w in s.split())
    return " ".join(NOISE.sub(" ", s).split())


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def organizer_points():
    wb = openpyxl.load_workbook(ROOT / "data/raw/organizer_overlaps.xlsx", read_only=True)
    rows = list(wb["projects"].iter_rows(values_only=True))
    head = rows[0]
    by_name, by_project = {}, {}
    for r in rows[1:]:
        d = dict(zip(head, r))
        org = "desc" if d["project_id"].startswith("DESC") else "gpc"
        for side in ("a", "b"):
            if d[f"lat_{side}"] is not None:
                point = (d[f"lat_{side}"], d[f"lon_{side}"])
                by_name.setdefault((org, norm(d[f"name_{side}"])), point)
                by_project[(squash(d["project_name"]), norm(d[f"name_{side}"]))] = point  # sheet repeats some subs with slightly different coords
    return by_name, by_project


def home_states():
    r = shapefile.Reader(str(ROOT / "data/layers/states/cb_2023_us_state_500k.shp"))
    return {rec["STUSPS"]: (rec["NAME"], shp) for rec, shp in zip(r.records(), r.shapes())}


def register(org, state, name):
    HOME[org] = state
    OPERATORS[org] = re.compile(re.escape(name.split()[0]), re.I)  # e.g. "Santee" for Santee Cooper


class Locator:
    def __init__(self):
        self.gold, self.gold_project = organizer_points()
        self.states = home_states()
        self._prepared = {}
        path = ROOT / "data/layers/osm_substations.json"
        self.osm = json.loads(path.read_text()) if path.exists() else []
        for s in self.osm:
            s["norm"] = norm(s["name"])

    def candidates(self, org, name, project=""):
        key = norm(name)
        if not key:
            return []
        point = self.gold_project.get((squash(project), key)) or self.gold.get((org, key))
        if point:
            return [{"lat": point[0], "lon": point[1], "conf": 1.0, "via": "organizer", "name": name}]
        home = self.home(org)
        out = []
        short = len(key) < 6 and " " not in key  # "creek" must not match "acree"
        for s in self.osm:
            sc = fuzz.token_sort_ratio(key, s["norm"])
            if sc < 80 or (short and key != s["norm"]):
                continue
            conf = sc / 100 * (1.0 if OPERATORS[org].search(s.get("operator") or "") else 0.85)
            conf *= 1.0 if home.contains(Point(s["lon"], s["lat"])) else OUT_OF_STATE
            if conf >= MIN_CONF:
                out.append({"lat": s["lat"], "lon": s["lon"], "conf": round(conf, 3), "via": s["osm"], "name": s["name"]})
        return sorted(out, key=lambda c: -c["conf"])

    def home(self, org):
        state = HOME[org]
        if state not in self._prepared:
            self._prepared[state] = prep(shape(self.states[state][1].__geo_interface__).buffer(0.01))  # ~1 km slack for border substations
        return self._prepared[state]

    def fallback(self, org, name, near):
        key = norm(name)
        if len(key) < 4 or not self.osm:
            return None
        hit = geocode(self.states[HOME[org]][0], key.title())  # town-level guess, shown as approx
        return hit if hit and km((hit["lat"], hit["lon"]), near) <= 60 else None  # must sit near the located endpoint

    def loose(self, org, names, limit=8):
        """Weaker OSM matches inside the home state, for gemini to choose from."""
        home, out = self.home(org), {}
        for n in names:
            key = norm(n)
            if len(key) < 3:
                continue
            for s in self.osm:
                sc = fuzz.token_set_ratio(key, s["norm"])
                if sc >= 70 and home.contains(Point(s["lon"], s["lat"])):
                    out[s["osm"]] = max(out.get(s["osm"], (0, s)), (sc, s), key=lambda x: x[0])
        return [s for _, s in sorted(out.values(), key=lambda x: -x[0])[:limit]]

    def town(self, org, name):
        state = self.states[HOME[org]][0]
        hit = lookup(f"{name.title()}, {state}")
        if not hit or hit.get("addresstype") not in TOWN:
            return None  # a county or region is too vague for a station
        lat, lon = float(hit["lat"]), float(hit["lon"])
        if not self.home(org).contains(Point(lon, lat)):
            return None
        return {"lat": lat, "lon": lon, "conf": TOWN_CONF, "via": f"town:{hit.get('display_name', '')[:60]}", "name": name, "approx": True}

    def place_job(self, org, job):
        """Best defensible location for a filed project, or [None] with a reason."""
        names = endpoint_names(job)
        stated = stated_full_miles(job.get("description"))
        span = min(MAX_SPAN_KM, stated * 1.609 * 1.8 + 8) if stated else MAX_SPAN_KM  # the filing says how long the line is
        picks = self.place(org, names or [job["name"]], job["name"], span)
        if any(picks):
            return picks, None
        for n in mentioned_stations(job.get("description")):  # "install reactors at Anthony Shoals substation"
            c = self.candidates(org, n, job["name"])
            if c:
                return [{**c[0], "via": f"description:{c[0]['via']}"}], None
        mentioned = mentioned_stations(job.get("description"))
        options = self.loose(org, names + mentioned)
        if options:
            chosen = llm_pick.choose(job, options)
            if chosen:
                return [{"lat": chosen["lat"], "lon": chosen["lon"], "conf": LLM_CONF, "via": f"gemini:{chosen['osm']}", "name": chosen["name"]}], None
        local = [n for n, e in zip(names, job.get("endpoints") or names) if not foreign(e)] + mentioned
        for n in local:
            hit = self.town(org, n)
            if hit:
                return [hit], None
        return [None], "no substation, plant or town with this name was found in the utility's state"

    def place(self, org, endpoints, project="", max_span=MAX_SPAN_KM):
        cands = [self.candidates(org, e, project)[:5] for e in endpoints]
        if len(cands) == 2 and cands[0] and cands[1]:
            pairs = [(a, b) for a in cands[0] for b in cands[1] if km((a["lat"], a["lon"]), (b["lat"], b["lon"])) <= max_span]
            if pairs:
                return list(max(pairs, key=lambda p: p[0]["conf"] + p[1]["conf"]))
            keep = 0 if cands[0][0]["conf"] >= cands[1][0]["conf"] else 1  # endpoints disagree; keep the stronger one
            return [cands[0][0] if keep == 0 else None, cands[1][0] if keep == 1 else None]
        picks = [c[0] if c else None for c in cands]
        if len(picks) == 2 and (picks[0] is None) != (picks[1] is None):
            found = picks[0] or picks[1]
            i = picks.index(None)
            picks[i] = self.fallback(org, endpoints[i], (found["lat"], found["lon"]))
        return picks
