"""SERTP expansion plans: TVA (TN) and Alabama Power (AL) blocks, 2026 preliminary plan plus 2026 in-service projects from the final 2025 plan."""
import json
import re
import subprocess
from datetime import date
from functools import lru_cache

from rapidfuzz import fuzz, process

from app.db import ROOT
from app.geo.geolocate import norm
from app.ingest.national.common import clear, find_station, register_org, register_source, save
from app.ingest.national.south_names import ends_from_title, stable_id

PLAN_2026 = "data/raw/national/sertp-2026/sertp_2026_prelim_expansion_plan.pdf"
PLAN_2025 = "data/raw/national/sertp-2025/sertp_2025_rtp.pdf"
AREA = re.compile(r"^\s{15,}(?P<a>AECI|DUKE\s+CAROLINAS|DUKE\s+PROGRESS\s+EAST|DUKE\s+PROGRESS\s+WEST|LG&E/KU|KU|SOUTHERN|TVA|OVEC|POWERSOUTH)\s")
YEAR = re.compile(r"^\s*In-\s?Service\s+(?P<y>\d{4})")
FIELD = re.compile(r"^\s*(?P<k>Project Name|Description|Supporting|Statements?)(?::|\s{2,}|\s*$)\s*(?P<v>.*)$")  # "Supporting" wraps before "Statement:"
CONT = re.compile(r"^\s{12,}(?P<v>\S.*)$")
NOISE = re.compile(r"SERTP|TRANSMISSION\s+PROJECTS|Balancing|Page \d+ of|^\s*\d{2}/\d{2}/\d{4}|^\s*Year:\s*$")
TVA_STATES = ["TN", "AL", "MS", "KY", "GA"]
MILES = re.compile(r"([\d.]+)\s*(?:-|\s)?mile", re.I)


def text(path):
    txt = ROOT / path.replace(".pdf", ".txt")
    if not txt.exists():
        subprocess.run(["pdftotext", "-layout", str(ROOT / path), str(txt)], check=True)
    return txt.read_text()


def blocks(lines):
    """Project blocks: area, in-service year, name, description, supporting statement."""
    area, cur, field = None, None, None
    for line in lines:
        a = AREA.match(line)
        if a:
            area = re.sub(r"\s+", " ", a["a"])
            continue
        y = YEAR.match(line)
        if y:
            if cur and cur.get("name"):
                yield cur
            cur, field = {"area": area, "year": int(y["y"]), "name": "", "description": "", "support": ""}, None
            continue
        if cur is None or NOISE.search(line):
            continue
        f = FIELD.match(line)
        if f:
            field = {"Project Name": "name", "Description": "description"}.get(f["k"], "support")
            cur[field] = (cur[field] + " " + f["v"]).strip()
            continue
        c = CONT.match(line)
        if c and field:
            cur[field] = (cur[field] + " " + c["v"]).strip()
    if cur and cur.get("name"):
        yield cur


def mapped(b, org, state, source):
    ends = ends_from_title(b["name"])
    mi = MILES.search(b["description"])
    kv = re.search(r"(\d{2,3})\s*KV", b["name"], re.I)
    title = b["name"].title().replace(" Kv ", " kV ")
    return {
        "id": stable_id(f"sertp-{org}", b["name"]), "name": title[:200], "description": b["description"] or None,
        "voltage_kv": int(kv[1]) if kv else None, "in_service": date(b["year"], 12, 1), "start": None, "status": "planned",
        "need": b["support"][:500] or None, "length_mi": float(mi[1]) if mi else None, "cost_usd": None, "ends": ends,
        "states": TVA_STATES if org == "tva" else ["AL"], "counties": None,
        "source_project_id": f"SERTP {source} ({b['area']} area)", "planner": "SERTP", "state": state, "raw": {**b, "source": source},
    }


def area_blocks(area):
    """2026 prelim blocks, plus 2026 in-service blocks from the final 2025 plan the prelim no longer lists."""
    new = [b for b in blocks(text(PLAN_2026).splitlines()) if b["area"] == area]
    names = {norm(b["name"]) for b in new}
    old = [b for b in blocks(text(PLAN_2025).splitlines()) if b["area"] == area and b["year"] >= 2026 and norm(b["name"]) not in names]
    return [(b, "2026 preliminary plan") for b in new] + [(b, "2025 final plan") for b in old]


@lru_cache
def georgia_names():
    """Georgia and Carolina substations from the original two-state osm file (no per-state GA file yet)."""
    path = ROOT / "data/layers/osm_substations.json"
    return [norm(r["name"]) for r in json.loads(path.read_text()) if r.get("name")] if path.exists() else []


def other_score(name):
    """Best match for this station in Georgia or Mississippi, to tell Alabama Power blocks from its sister companies'."""
    ms = find_station(name, ["MS"])
    hit = process.extractOne(norm(name), georgia_names(), scorer=fuzz.token_sort_ratio, score_cutoff=90)
    return max(ms["score"] if ms else 0, hit[1] if hit else 0)


def alabama(b, p):
    """Southern area mixes Alabama, Georgia and Mississippi Power: keep a block only when it is clearly in Alabama."""
    if re.search(r"\(APC\)|Alabama", f"{b['name']} {b['description']} {b['support']}", re.I):
        return True
    for e in p["ends"]:
        al = find_station(e, ["AL"])
        if al and al["score"] > other_score(e):
            return True
    return False


def rows(org):
    area, state = ("TVA", "TN") if org == "tva" else ("SOUTHERN", "AL")
    for b, source in area_blocks(area):
        if b["year"] < 2024:
            continue
        p = mapped(b, org, state, source)
        if org == "alabamapower" and not alabama(b, p):
            continue  # Georgia Power or Mississippi Power project
        if org == "tva":
            hit = next((h for h in (find_station(e, TVA_STATES) for e in p["ends"]) if h), None)
            p["state"] = hit.get("state", "TN") if hit else "TN"  # where the station actually is
        yield p


def load(conn, manifest="data/raw/national/manifest_south.json"):
    out = {}
    for m in json.loads((ROOT / manifest).read_text()):
        if m["slug"] not in ("tva", "alabamapower"):
            continue
        org = m["slug"]
        short = "TVA" if org == "tva" else "Alabama Power"
        register_org(conn, org, m["utility"], short, m["state"], "SERTP", org)
        clear(conn, org)
        doc = register_source(conn, org, "SERTP 2026 Preliminary Expansion Plan (Non-CEII)", m["url"], PLAN_2026, "SERTP", "2026 preliminary")
        counts = {"placed": 0, "review": 0}
        for p in rows(org):
            counts[save(conn, {**p, "org_id": org}, doc)] += 1
        out[m["state"]] = {"org": org, **counts}
        print(m["state"], org, counts, flush=True)
    return out
