"""Carolinas Transmission Planning Collaborative 2025-2035 plan: Duke Energy Carolinas and Progress projects."""
import json
import re
import subprocess
from datetime import datetime

from app.db import ROOT
from app.ingest.national.common import clear, find_station, register_org, register_source, save
from app.ingest.national.south_names import ends_from_title, resolve

FILE = "data/raw/national/ctpc-2025/ctpc_2025_2035_plan.pdf"
ROW = re.compile(r"^\s*(?P<id>[A-Z][A-Z0-9]{4,})\s{2,}(?P<name>.*?)\s{2,}(?P<owner>DEC/DEP|DEC|DEP)\s+(?P<status>Underway|Planned|Conceptual|In[- ]Service)"
                 r"\s+(?P<isd>\d{1,2}/\d{1,2}/\d{4}|TBD|N/A)(?:\s+(?P<cost>[\d.,]+))?(?:\s+(?P<study>[A-Za-z][A-Za-z ]*?))?\s*$")
NAME_ONLY = re.compile(r"^\s{12,}(?P<text>\S.*?)\s*$")  # a wrapped title line with no columns
APPENDIX = re.compile(r"^\s*Appendix (?P<a>[A-H])\s*$")
NEED = {"C": "reliability", "E": "public policy", "G": "multi-value strategic transmission"}
STUDY = {"TPL": "NERC TPL reliability study", "AS": "asset management", "TSR": "transmission service request", "GI": "generator interconnection",
         "LI": "load interconnection", "PP": "public policy"}
HEADER = re.compile(r"Project ID|Red items|Estimated|Transmission|Owner|Service Date|Study Type|\(\$M\)|Collaborative Transmission Plan|^\s*\d+\s*$")
OWNER = {"DEC": "Duke Energy Carolinas", "DEP": "Duke Energy Progress", "DEC/DEP": "Duke Energy Carolinas and Progress"}
KEEP = {"Underway": "under construction", "Planned": "planned"}


def text():
    txt = ROOT / FILE.replace(".pdf", ".txt")
    if not txt.exists():
        subprocess.run(["pdftotext", "-layout", str(ROOT / FILE), str(txt)], check=True)
    return txt.read_text()


def parse(lines):
    """Listing rows with titles rebuilt from the wrapped lines above them; first mention of an id wins."""
    appendix, pending, seen = None, [], set()
    for line in lines:
        a = APPENDIX.match(line)
        if a:
            appendix, pending = a["a"], []
            continue
        m = ROW.match(line)
        if m:
            name = " ".join(pending + [m["name"].strip()]).strip()
            pending = []
            if m["id"] not in seen and appendix in NEED:
                seen.add(m["id"])
                yield {**m.groupdict(), "name": re.sub(r"\s+", " ", name), "appendix": appendix}
            continue
        n = NAME_ONLY.match(line)
        if n and not HEADER.search(line) and len(n["text"]) < 90:
            pending.append(n["text"])
        else:
            pending = []


def mapped(r):
    """One listing row as a normalized project; SC projects keep Duke as owner but get their own state."""
    isd = datetime.strptime(r["isd"], "%m/%d/%Y").date() if "/" in r["isd"] and r["isd"] != "N/A" else None
    sc = bool(re.search(r"\bSC\b|South Carolina", r["name"]))
    ends = ends_from_title(r["name"])
    return {
        "id": f"ctpc-{r['id'].lower()}", "name": r["name"][:200], "description": r["name"], "voltage_kv": kv(r["name"]),
        "in_service": isd, "start": None, "status": KEEP.get(r["status"], r["status"].lower()),
        "need": NEED[r["appendix"]] + (f" ({STUDY.get(r['study'], r['study'])})" if r["study"] else ""), "length_mi": None,
        "cost_usd": float(r["cost"].replace(",", "")) * 1e6 if r["cost"] else None, "ends": ends, "states": ["SC", "NC"] if sc else ["NC", "SC"], "counties": None,
        "source_project_id": f"CTPC {r['id']} ({OWNER[r['owner']]})",
        "planner": "CTPC", "state": "SC" if sc else "NC", "raw": {**r, "appendix_name": NEED[r["appendix"]]},
    }


def kv(name):
    m = re.search(r"(\d{2,3})(?:/\d+)?\s*kV", name, re.I)
    return int(m[1]) if m else None


def rows():
    for r in parse(text().splitlines()):
        if r["status"] in KEEP:
            p = mapped(r)
            if not p["in_service"] or p["in_service"].year >= 2024:
                yield p


def load(conn, manifest="data/raw/national/manifest_south.json"):
    m = next(e for e in json.loads((ROOT / manifest).read_text()) if e["slug"] == "duke")
    register_org(conn, "duke", m["utility"], "Duke Energy", "NC", "CTPC", "duke")
    clear(conn, "duke")
    doc = register_source(conn, "duke", "CTPC 2025-2035 Collaborative Transmission Plan (final 2026-04-16)", m["url"], FILE, "CTPC", "2025-2035")
    counts = {"placed": 0, "review": 0}
    for p in rows():
        p["ends"] = resolve(p["ends"], p["states"], ["Duke", "Duke Energy"])
        hit = next((h for h in (find_station(e, p["states"]) for e in p["ends"]) if h), None)
        if hit:
            p["state"] = hit.get("state", p["state"])  # the station's state, NC or SC
        counts[save(conn, {**p, "org_id": "duke"}, doc)] += 1
    print("NC duke", counts, flush=True)
    return {"NC": {"org": "duke", **counts}}
