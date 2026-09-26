"""ERCOT TPIT (July 2026, no-cost edition): Oncor's planned and conceptual projects in Texas."""
import json

import pandas as pd

from app.db import ROOT
from app.ingest.national.common import clean, clear, register_org, register_source, save, to_date
from app.ingest.national.south_names import ends_from_title, station

FILE = "data/raw/national/ercot-tpit/ercot_tpit_2026_07.xlsx"
SHEETS = ["FutureTPIT071326NoCost", "PlannedTPIT071326NoCost"]
PRIVATE = {"TSP/Company Contact"}  # a named person's email and phone: not ours to keep
COL = {  # short names for the long TPIT headers
    "num": "ERCOT Project Number", "title": "Project Title (text, please start with location name first)", "desc": "Project Description (text)",
    "from": 'Terminal "from" Location', "to": 'Terminal "to" Location', "status": 'Transmission Status "under construction, planned or conceptual"',
    "owner": "Transmission Owner (text)", "own_id": "Transmission Owner Project Number (Optional)", "isd": "Projected In-Service Date (Month/Yr)",
    "kv": "Service Level kV", "new_mi": "Trans Circuit Miles New", "up_mi": "Trans Circuit Miles Rebuilt, Reconductored or Upgraded",
    "county_a": "County Location for Substation or Starting Point for a Line", "county_b": "County Location for Ending Point for a Line (Optional for Substation projects)",
    "tier": "Planning Charter Tier ",
}


def cell(v):
    """clean() that also drops pandas' NaT."""
    return None if not isinstance(v, (list, dict)) and pd.isna(v) else clean(v)


def num(v):
    try:
        return float(v) if v is not None and str(v).strip() not in ("", "nan") else None
    except ValueError:
        return None


def mapped(r, sheet):
    """One TPIT row as a normalized project, or None when it's not Oncor's."""
    g = lambda k: cell(r.get(COL[k]))  # noqa: E731
    if not str(g("owner") or "").upper().startswith("ONCOR"):
        return None
    a, b = station(g("from")), station(g("to"))
    ends = [e for e in dict.fromkeys([a, b]) if e] or ends_from_title(g("title"))
    kv = num(g("kv"))
    miles = (num(g("new_mi")) or 0) + (num(g("up_mi")) or 0)
    counties = [c for c in dict.fromkeys([g("county_a"), g("county_b")]) if c]
    tier = str(g("tier") or "").strip()
    pid = str(g("num")).removesuffix(".0")  # numbers like 99391B carry a letter
    return {
        "id": f"ercot-{pid}", "name": str(g("title"))[:200], "description": g("desc"), "voltage_kv": int(kv) if kv else None,
        "in_service": to_date(g("isd")), "start": None, "status": str(g("status") or "planned").lower(),
        "need": f"ERCOT planning {tier.lower()} project" if tier else None, "length_mi": miles or None, "cost_usd": None,
        "ends": ends, "states": ["TX"], "counties": counties or None,
        "source_project_id": f"ERCOT {pid}" + (f" / Oncor {g('own_id')}" if g("own_id") else ""),
        "planner": "ERCOT", "state": "TX",
        "raw": {"sheet": sheet, **{k: cell(v) for k, v in r.items() if k not in PRIVATE}},
    }


def rows():
    x = pd.ExcelFile(ROOT / FILE)
    seen = set()
    for sheet in SHEETS:
        for _, r in pd.read_excel(x, sheet, header=1).iterrows():
            if pd.isna(r.get(COL["num"])):
                continue
            p = mapped(r.to_dict(), sheet)
            if p and p["id"] not in seen:
                seen.add(p["id"])
                yield p


def load(conn, manifest="data/raw/national/manifest_south.json"):
    m = next(e for e in json.loads((ROOT / manifest).read_text()) if e["slug"] == "oncor")
    register_org(conn, "oncor", m["utility"], "Oncor", "TX", "ERCOT", "oncor")
    clear(conn, "oncor")
    doc = register_source(conn, "oncor", "ERCOT Transmission Project and Information Tracking (TPIT), no-cost edition", m["url"], FILE, "ERCOT", "July 2026")
    counts = {"placed": 0, "review": 0}
    for p in rows():
        counts[save(conn, {**p, "org_id": "oncor"}, doc)] += 1
    print("TX oncor", counts, flush=True)
    return {"TX": {"org": "oncor", **counts}}
