import json
import math
import re

import openpyxl
from rapidfuzz import fuzz

from app.db import ROOT

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


class Locator:
    def __init__(self):
        self.gold, self.gold_project = organizer_points()
        path = ROOT / "data/layers/osm_substations.json"
        self.osm = json.loads(path.read_text()) if path.exists() else []
        for s in self.osm:
            s["norm"] = norm(s["name"])

    def candidates(self, org, name, near=None, project=""):
        key = norm(name)
        if not key:
            return []
        point = self.gold_project.get((squash(project), key)) or self.gold.get((org, key))
        if point:
            lat, lon = point
            return [{"lat": lat, "lon": lon, "conf": 1.0, "via": "organizer", "name": name}]
        out = []
        for s in self.osm:
            sc = fuzz.token_sort_ratio(key, s["norm"])
            if sc < 80:
                continue
            conf = sc / 100 * (1.0 if OPERATORS[org].search(s.get("operator") or "") else 0.85)
            out.append({"lat": s["lat"], "lon": s["lon"], "conf": round(conf, 3), "via": s["osm"], "name": s["name"]})
        out.sort(key=lambda c: -c["conf"])
        top = [c for c in out if c["conf"] >= out[0]["conf"] - 0.03] if out else []
        if near and len(top) > 1:
            top.sort(key=lambda c: km((c["lat"], c["lon"]), near))  # tie-break: closest to the other endpoint
        return top + [c for c in out if c not in top]

    def place(self, org, endpoints, project=""):
        first = [self.candidates(org, e, project=project) for e in endpoints]
        picks = []
        for i, cands in enumerate(first):
            other = next((f[0] for j, f in enumerate(first) if j != i and f), None)
            near = (other["lat"], other["lon"]) if other else None
            ranked = self.candidates(org, endpoints[i], near, project) if len(cands) > 1 else cands
            picks.append(ranked[0] if ranked else None)
        return picks
