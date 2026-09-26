import json
import math
import re

import openpyxl
import shapefile
from rapidfuzz import fuzz
from shapely.geometry import Point, shape
from shapely.prepared import prep

from app.db import ROOT
from app.geo.nominatim import geocode

HOME = {"desc": "SC", "gpc": "GA"}
MAX_SPAN_KM = 100  # longest plausible line in these filings
MIN_CONF = 0.6
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
        for s in self.osm:
            sc = fuzz.token_sort_ratio(key, s["norm"])
            if sc < 80:
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

    def place(self, org, endpoints, project=""):
        cands = [self.candidates(org, e, project)[:5] for e in endpoints]
        if len(cands) == 2 and cands[0] and cands[1]:
            pairs = [(a, b) for a in cands[0] for b in cands[1] if km((a["lat"], a["lon"]), (b["lat"], b["lon"])) <= MAX_SPAN_KM]
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
