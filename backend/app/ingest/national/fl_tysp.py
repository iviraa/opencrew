"""FPL 2026 Ten-Year Site Plan: the siting-act bulk lines (Table III.E.1) and each plant's interconnection scope."""
import json
import re
import subprocess
from datetime import date, datetime

from app.db import ROOT
from app.ingest.national.common import clear, register_org, register_source, save
from app.ingest.national.south_names import stable_id, station

FILE = "data/raw/national/fl-psc-tysp-2026/fpl_tysp_2026.pdf"
LINE = re.compile(r"^\s*FPL\s+(?P<to>[A-Za-z .'-]+?)\s*(?:\d/)?\s{2,}(?P<frm>[A-Za-z .'-]+?)\s{2,}(?P<mi>[\d.]+)\s+(?P<mon>[A-Za-z]+)/(?P<yr>\d{4})"
                  r"\s+(?P<kv>\d+)\s+(?P<mva>[\d,]+)\s*$")
SECTION = re.compile(r"^\s*III\.E\.(?P<n>\d+)\s+Transmission Facilities for the (?P<title>.+)$")
WHEN = re.compile(r"in the (?P<q>\d)\s?(?:st|nd|rd|th) Quarter of (?P<yr>\d{4})", re.I)
COUNTY = re.compile(r"\bin (?P<c>[A-Z][A-Za-z. ]+?) County\b")
NEW_SUB = re.compile(r"new [^.]*?substation \((?P<n>[A-Z][\w .'-]+?)\)", re.I)
STATION = re.compile(r"(?:\bat |\bfrom |\bto |\badjacent |\bLoop the adjacent |\binto )(?P<n>[A-Z][A-Za-z.'-]+(?: [A-Z][A-Za-z.'-]+){0,3})"
                     r"(?= \d{2,3}\s?kV| [Ss]ubstation| -| –)")
QUARTER_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
FOOTER = re.compile(r"Florida Power & Light Company\s+\d+\s*$")


def text():
    txt = ROOT / FILE.replace(".pdf", ".txt")
    if not txt.exists():
        subprocess.run(["pdftotext", "-layout", str(ROOT / FILE), str(txt)], check=True)
    return txt.read_text()


def bulk_lines(lines):
    """Table III.E.1: five siting-act lines with both terminals."""
    start = next(i for i, l in enumerate(lines) if "Table III.E.1: List of Proposed Power Lines" in l)
    for l in lines[start:start + 20]:
        m = LINE.match(l)
        if m:
            isd = datetime.strptime(f"{m['mon']} {m['yr']}", "%B %Y").date()
            yield {"kind": "bulk line", "to": m["to"].strip(), "from": m["frm"].strip(), "miles": float(m["mi"]), "in_service": isd,
                   "kv": int(m["kv"]), "mva": int(m["mva"].replace(",", ""))}


def hookups(lines):
    """Each "III.E.n Transmission Facilities for the X Energy Center in Y County" section, title unwrapped, text kept whole."""
    heads = [i for i, l in enumerate(lines) if SECTION.match(l)]
    for k, i in enumerate(heads):
        end = heads[k + 1] if k + 1 < len(heads) else min(len(lines), i + 60)
        body = [l for l in lines[i:end] if not FOOTER.search(l)]
        m = SECTION.match(body[0])
        title = m["title"].strip()
        if not re.search(r"County\s*$", title) and len(body) > 1 and body[1].strip():  # title wraps onto the next line
            title = f"{title} {body[1].strip()}"
        flat = re.sub(r"\s+", " ", " ".join(body))
        yield {"kind": "plant interconnection", "section": f"III.E.{m['n']}", "title": title, "text": flat}


def mapped_line(r):
    return {
        "id": stable_id("fpl-line", r["from"], r["to"], r["kv"]), "name": f"{r['from']} - {r['to']} {r['kv']} kV line",
        "description": f"New {r['kv']} kV line, {r['miles']} miles, {r['mva']} MVA (Transmission Line Siting Act)", "voltage_kv": r["kv"],
        "in_service": r["in_service"], "start": None, "status": "planned", "need": "bulk system (siting act line)", "length_mi": r["miles"],
        "cost_usd": None, "ends": [station(r["from"]), station(r["to"])], "states": ["FL"], "counties": None,
        "source_project_id": "FPL TYSP 2026 Table III.E.1", "planner": "FL PSC", "state": "FL",
        "raw": {**r, "in_service": r["in_service"].isoformat()},
    }


def mapped_hookup(r):
    w = WHEN.search(r["text"])
    if not w:
        return None
    mo, dy = QUARTER_END[int(w["q"])]
    county = COUNTY.search(r["title"]) or COUNTY.search(r["text"])
    new = {n.strip().lower() for n in NEW_SUB.findall(r["text"])}
    seen = [s for s in dict.fromkeys(m.strip() for m in STATION.findall(r["text"])) if s.lower() not in new]
    ends = [e for e in (station(s) for s in seen) if e][:1]  # the existing station it ties into; the new one isn't mapped yet
    kv = re.search(r"(\d{3}) ?kV", r["text"])
    mw = re.search(r"([\d.,]+) MW", r["text"])
    plant = re.sub(r"\s+in [A-Z][\w. ]+ County$", "", r["title"]).strip()
    return {
        "id": stable_id("fpl-hookup", plant), "name": f"{plant} interconnection"[:200], "description": r["text"][:1500],
        "voltage_kv": int(kv[1]) if kv else None, "in_service": date(int(w["yr"]), mo, dy), "start": None, "status": "planned",
        "need": "generator interconnection" + (f" ({mw[1]} MW)" if mw else ""), "length_mi": None, "cost_usd": None,
        "ends": ends, "states": ["FL"], "counties": [county["c"].strip()] if county else None,
        "source_project_id": f"FPL TYSP 2026 {r['section']}", "planner": "FL PSC", "state": "FL",
        "raw": {**r, "new_substations": sorted(new), "stations_mentioned": seen},
    }


def rows():
    lines = text().splitlines()
    for r in bulk_lines(lines):
        yield mapped_line(r)
    for r in hookups(lines):
        p = mapped_hookup(r)
        if p:
            yield p


def load(conn, manifest="data/raw/national/manifest_south.json"):
    m = next(e for e in json.loads((ROOT / manifest).read_text()) if e["slug"] == "fpl")
    register_org(conn, "fpl", m["utility"], "FPL", "FL", "FL PSC", "fpl")
    clear(conn, "fpl")
    doc = register_source(conn, "fpl", "Florida Power & Light 2026 Ten-Year Site Plan", m["url"], FILE, "FL PSC", "2026")
    counts = {"placed": 0, "review": 0}
    for p in rows():
        counts[save(conn, {**p, "org_id": "fpl"}, doc)] += 1
    print("FL fpl", counts, flush=True)
    return {"FL": {"org": "fpl", **counts}}
