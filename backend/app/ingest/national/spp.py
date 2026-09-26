"""SPP STEP 2026 Appendix 1: one job per upgrade for the chosen owner in each state."""
import json
import re

import pandas as pd

from app.db import ROOT
from app.ingest.national.common import clean, clear, register_org, register_source, save, to_date

OWNERS = {  # state -> SPP owner codes that belong to that state's utility
    "ND": ["BEPC"], "SD": ["EREC"], "NE": ["NPPD"], "KS": ["EKC", "WR", "EM", "EMW", "KCPL"], "OK": ["OGE"], "NM": ["SPS"],
}
DONE = {"Complete", "Closed Out", "In Service"}
FILE = "data/raw/national/spp-step/step2026_appendix1.xlsx"
ISD, NEED, NTC = "Project Owner Indicated\nIn-Service Date", "RTO Determined Need Date", "Letter of Notification \nto Construct Issue Date"

JUNK = re.compile(r"\([^)]*\)|\bGEN-\d{4}-\d+\w*\b|\bDISIS-[\w-]+\b|\d+(?:/\d+)*\s*-?\s*kv\b|\bckt\s*\d+\b|#\s*\d+|\bno\.\s*\d+\b", re.I)
WORDS = re.compile(r"\b(multi|line|sub|rebuild|reconductor|convert|conversion|voltage|tap|terminal|equipment|substation|transformer|"
                   r"reconfiguration|reconfig|switching|station|interconnection|costs?|upgrade|new|install|replace|replacement|"
                   r"expansion|capacitor|capacitive|reactive|support|cap|bank|reactor|breaker|toif|nu|manual|area|project|switch|xfr|xfmr|upgrades|"
                   r"add|addition|second|third)\b", re.I)


def stations(name):
    """Station names inside an SPP title: 'Hugo - Sunnyside 345 kV' -> ['Hugo', 'Sunnyside']."""
    s = JUNK.sub(" ", name or "")
    parts = re.split(r"\s+[-–—]\s+|\s+to\s+", s)
    out = []
    for p in parts:
        p = tidy(WORDS.sub(" ", p).replace("&", " "))
        if len(p) >= 3 and not p.isdigit():
            out.append(p)
    return out[:2]


def tidy(s):
    s = re.sub(r"\b\d+k\b|^\s*at\s+|\s+\d+(\.\d+)?\s*$", " ", " ".join(s.split()), flags=re.I)  # "Hoskins 345k", "at Phantom", "Crossroads 2"
    return " ".join(s.split()).strip(" -,/")


def bus(name):
    if not isinstance(name, str) or not name.strip():
        return None
    s = tidy(JUNK.sub(" ", name))  # "CUSHING 69" is the 69 kV bus at Cushing
    return s if len(s) >= 3 and s.lower() not in ("sub", "xfr", "bus") else None


def kv(v):
    nums = [int(x) for x in re.findall(r"\d+", str(v))] if v is not None and str(v) != "nan" else []
    return max(nums) if nums else None


def row_states(v):
    return [s.strip() for s in str(v or "").split("/") if s.strip() and s.strip() != "nan"]


def ends_for(r):
    ends = [e for e in (bus(r["From Bus Name"]), bus(r["To Bus Name"])) if e]
    return ends or stations(r["Upgrade Name"]) or stations(r["Project Name"])


def number(v):
    return float(v) if v is not None and pd.notna(v) else None


def mapped(r, state):
    """Normalized project for one SPP upgrade row, or None when it is done or out of range."""
    if r["Project Status"] in DONE:
        return None
    owner_isd, need_date = to_date(r[ISD]), to_date(r[NEED])
    isd = owner_isd or need_date
    if isd and isd.year < 2024:
        return None
    miles = sum(x for x in (number(r["Number of New"]), number(r["Number of Rebuild/Reconductor"]), number(r["Number of Voltage Conversion"])) if x)
    cost = number(r["Current Cost Estimate"]) or number(r["Baseline Cost Estimate with Escalation"]) or number(r["Baseline Cost Estimate"])
    raw = {k.replace("\n", " "): clean(v) for k, v in r.items()}
    raw["in_service_from"] = "owner" if owner_isd else "rto_need_date" if need_date else None  # which date we used
    ends = ends_for(r)
    return {
        "id": f"spp-{int(r['Upgrade ID'])}", "name": str(r["Upgrade Name"] if isinstance(r["Upgrade Name"], str) else r["Project Name"])[:200],
        "description": clean(r["Project Description/ Comments"]) or clean(r["Project Name"]), "voltage_kv": kv(r["Voltages (kV)"]),
        "in_service": isd, "start": to_date(r[NTC]), "status": str(r["Project Status"]).lower(),
        "need": " ".join(str(r["Project Type"]).split()).lower() if isinstance(r["Project Type"], str) else None,
        "length_mi": miles or None, "cost_usd": cost, "ends": ends,
        "states": list(dict.fromkeys([state, *row_states(r["State(s)"])])),
        "counties": [e for e in ends if e.lower().endswith(" county")] or None,  # stations named after a county can fall back to it
        "source_project_id": f"SPP project {int(r['Project ID'])} / upgrade {int(r['Upgrade ID'])}"
                             + (f" / NTC {int(r['NTC ID'])}" if pd.notna(r["NTC ID"]) else ""),
        "planner": "SPP", "state": state, "raw": raw,
    }


def rows(df, state):
    mine = df[df["Project Owner"].isin(OWNERS[state]) & df["State(s)"].map(lambda v: state in row_states(v))]
    seen = set()
    for _, r in mine.iterrows():
        p = mapped(r, state)
        if p and p["id"] not in seen:  # an upgrade listed twice keeps its first row
            seen.add(p["id"])
            yield p


def load(conn, only=None, manifest="data/raw/national/manifest_central.json"):
    df = pd.read_excel(ROOT / FILE, header=13)
    out = {}
    for m in json.loads((ROOT / manifest).read_text()):
        if m["state"] not in OWNERS or (only and m["state"] not in only):
            continue
        org = m["slug"]
        register_org(conn, org, m["utility"], m["utility"].split(" (")[0].split(" / ")[0], m["state"], "SPP", m["slug"])
        clear(conn, org)
        doc = register_source(conn, org, "SPP 2026 STEP Report Appendix 1", m["url"], FILE, "SPP", "STEP 2026, 2026-05-15")
        counts = {"placed": 0, "review": 0}
        for p in rows(df, m["state"]):
            counts[save(conn, {**p, "org_id": org}, doc)] += 1
        out[m["state"]] = {"org": org, **counts}
        print(m["state"], org, counts, flush=True)
    return out
