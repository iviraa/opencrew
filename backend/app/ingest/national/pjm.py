"""PJM Project Status & Cost Allocation export: one job per upgrade row for the chosen owner in each state."""
import json
import re

import pandas as pd

from app.db import ROOT
from app.ingest.national.common import clean, clear, register_org, register_source, save, to_date

OWNERS = {"PA": "PPL", "NJ": "JCPL", "MD": "APS", "DE": "DPL", "VA": "Dominion", "WV": "APS", "OH": "AEP", "KY": "EKPC"}  # PJM TO codes
SHORT = {"ppl": "PPL", "jcpl": "JCP&L", "potomac-edison": "Potomac Edison", "delmarva": "Delmarva Power", "dominion-va": "Dominion Virginia",
         "mon-power": "Mon Power", "aep-ohio": "AEP Ohio", "ekpc": "EKPC"}
STATUS = {"PL": "planned", "Active": "active", "EP": "engineering and procurement", "UC": "under construction",
          "UC-ISP": "under construction, in-service pending"}
FILE = "data/raw/national/pjm-rtep/ProjectConstructionUpgrades.xlsx"
URL = "https://www.pjm.com/m/ProjectConst/ProjectConstructionUpgrades"

QUEUE = re.compile(r"\b[a-z]{1,2}\d-\d{3}\b", re.I)  # interconnection queue ids like AD2-088 are not places
KV = re.compile(r"\b\d+(\.\d+)?\s*kv\b|\bckt\.?\s*\d+\b|\bcircuit\s*\d+\b|#\s*\d+", re.I)
JUNK = re.compile(r"\b(line|sub|substation|switchyard|switching station|switch|station|tap|new)\b", re.I)
SPLIT = re.compile(r"\s+[-–—]\s+|\s*[–—]\s*|\s+to\s+|\s*,\s*|(?<=[a-z])-(?=[A-Z])", re.I)


def station(part):
    s = KV.sub(" ", QUEUE.sub(" ", part.replace("\xa0", " ")))
    s = JUNK.sub(" ", s)
    s = re.sub(r"[()]", " ", s)
    return " ".join(s.split()).strip(" -") or None


def ends(location):
    """Station names in a PJM Location cell: one substation, or the two ends of a line."""
    loc = (location or "").replace("\xa0", " ").strip()
    if not loc or "ceii" in loc.lower() or "interconnection customer" in loc.lower():
        return []
    names = [station(p) for p in SPLIT.split(loc)]
    return [n for n in names if n and len(n) >= 3][:2]


def kv(v):
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(v or ""))]
    return int(max(nums)) if nums else None


def in_service(r):
    """Latest of the revised and projected dates (a stale revision should not hide a live project), else the ISA or required date."""
    dates = [d for d in (to_date(_us(r.get("Revised In-Service Date"))), to_date(_us(r.get("Projected In Service Date")))) if d]
    if dates:
        return max(dates)
    for k in ("ISA In-Service Date", "Required Date"):
        d = to_date(_us(r.get(k)))
        if d and d.year >= 2024:
            return d
    return None


def _us(v):
    """M/D/YYYY strings to ISO dates."""
    if isinstance(v, str) and re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", v.strip()):
        m, d, y = v.strip().split("/")
        return f"{y}-{int(m):02d}-{int(d):02d}"
    return v


def need(r):
    driver = clean(r.get("Driver")) or ""
    kind = (clean(r.get("Project Type")) or "").lower()
    return f"{kind}: {driver}".strip(": ")[:300] if driver or kind else None


def row(r, state):
    loc = clean(r.get("Location"))
    names = ends(loc)
    cost = r.get("Cost Estimate")
    desc = clean(r.get("Description")) or ""
    return {
        "id": f"pjm-{r['Upgrade Id']}", "name": (desc or f"{clean(r.get('Task'))} {clean(r.get('Equipment'))} at {loc}")[:200],
        "description": " ".join(x for x in (desc, f"({clean(r.get('Task')) or ''} {clean(r.get('Equipment')) or ''} at {loc})" if loc else "") if x),
        "voltage_kv": kv(r.get("Voltage")), "in_service": in_service(r), "start": None, "status": STATUS.get(r.get("Status"), r.get("Status")),
        "need": need(r), "length_mi": None,
        "cost_usd": float(cost) * 1e6 if pd.notna(cost) and float(cost) > 0 else None,  # PJM reports $M
        "ends": names, "states": [state], "counties": None, "source_project_id": f"PJM {r['Upgrade Id']}", "planner": "PJM", "state": state,
        "raw": {k: clean(v) for k, v in r.items()},
    }


def rows(df, state):
    mine = df[(df["Transmission Owner"] == OWNERS[state]) & df["Status"].isin(STATUS) & (df["State"].astype(str).str.strip() == state)]
    for _, r in mine.iterrows():
        p = row(r.to_dict(), state)
        if p["in_service"] and p["in_service"].year < 2024:
            continue
        yield p


def load(conn, manifest="data/raw/national/manifest_east.json", states=None):
    df = pd.read_excel(ROOT / FILE, "Data")
    out = {}
    for m in json.loads((ROOT / manifest).read_text()):
        if m["state"] not in OWNERS or (states and m["state"] not in states):
            continue
        org = m["slug"]
        register_org(conn, org, m["utility"], SHORT.get(org, m["utility"]), m["state"], "PJM", m["slug"])
        clear(conn, org)
        doc = register_source(conn, org, "PJM Project Status & Cost Allocation (Export to Excel)", URL, FILE, "PJM", "updated 2026-09-09")
        counts = {"placed": 0, "review": 0}
        for p in rows(df, m["state"]):
            counts[save(conn, {**p, "org_id": org}, doc)] += 1
        out[m["state"]] = {"org": org, **counts}
        print(m["state"], org, counts, flush=True)
    return out
