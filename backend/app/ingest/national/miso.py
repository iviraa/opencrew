"""MISO MTEP Appendix A: one job per facility for the chosen owner in each state."""
import json

import pandas as pd

from app.db import ROOT
from app.ingest.national.common import clean, clear, register_org, register_source, save, to_date

OWNERS = {  # state -> Submitting TO values that belong to that state's utility
    "MN": ["NORTHERN STATES POWER COMPANY"], "WI": ["AMERICAN TRANSMISSION COMPANY"], "MI": ["METC"], "IA": ["ITC MIDWEST"],
    "IL": ["AMEREN ILLINOIS", "AMEREN TRANSMISSION COMPANY OF ILLINOIS"], "IN": ["DUKE ENERGY INDIANA, LLC CIN"], "MO": ["AMEREN MISSOURI"],
    "AR": ["ENTERGY ARKANSAS, LLC EATO", "ENTERGY SERVICES, LLC."], "LA": ["ENTERGY SERVICES, LLC."],
    "MS": ["ENTERGY MISSISSIPPI, LLC. EMTO", "ENTERGY SERVICES, LLC."],
}
LIVE = {"M2 - Appendix A Approved": "approved", "M3 - Under Construction": "under construction"}
FILE = "data/raw/national/miso-mtep/appendix_a_status_report.xlsx"


def need(project_type):
    return {"BaseRel": "reliability", "MVP": "multi-value (policy and reliability)", "Other": "local need", "TO-Economic": "economic",
            "GIP": "generator interconnection", "LRTP": "long-range plan"}.get(project_type, project_type)


def rows(df, state):
    mine = df[df["Submitting TO"].isin(OWNERS[state]) & df["Planning Status"].isin(LIVE)
              & ((df["State 1"] == state) | (df["State 2"] == state))]
    for _, r in mine.iterrows():
        isd = to_date(r["Expected ISD"])
        if isd and isd.year < 2024:
            continue
        miles = (r["Estimated Miles New"] if pd.notna(r["Estimated Miles New"]) else 0) + (r["Estimated Miles Upgrade"] if pd.notna(r["Estimated Miles Upgrade"]) else 0)
        yield {
            "id": f"miso-{int(r['MTEP Project ID'])}-{int(r['Facility ID'])}", "name": str(r["Name"] if pd.notna(r["Name"]) else r["Project"])[:200],
            "description": clean(r["Facility Description"]), "voltage_kv": int(r["Max kV"]) if pd.notna(r["Max kV"]) else None,
            "in_service": isd, "start": None, "status": LIVE[r["Planning Status"]], "need": need(clean(r["Project Type"])),
            "length_mi": float(miles) or None, "cost_usd": float(r["Current Cost"]) if pd.notna(r["Current Cost"]) else None,
            "ends": [clean(r["From Sub"]), clean(r["To Sub"])],
            "states": list(dict.fromkeys(s for s in (state, clean(r["State 1"]), clean(r["State 2"])) if s)), "counties": None,
            "source_project_id": f"MTEP {int(r['MTEP Project ID'])} / facility {int(r['Facility ID'])}", "planner": "MISO", "state": state,
            "raw": {k: clean(v) for k, v in r.items()},
        }


def load(conn, only=None, manifest="data/raw/national/manifest_central.json"):
    df = pd.read_excel(ROOT / FILE, 0, header=2)
    out = {}
    for m in json.loads((ROOT / manifest).read_text()):
        if m["state"] not in OWNERS or (only and m["state"] not in only):
            continue
        org = m["slug"]
        register_org(conn, org, m["utility"], m["utility"].split(" (")[0].split(" / ")[0], m["state"], "MISO", m["slug"])
        clear(conn, org)
        doc = register_source(conn, org, "MISO MTEP Appendix A Quarterly Status Report", m["url"], FILE, "MISO", "MTEP10-MTEP26, 2026-05-14")
        counts = {"placed": 0, "review": 0}
        for p in rows(df, m["state"]):
            counts[save(conn, {**p, "org_id": org}, doc)] += 1
        out[m["state"]] = {"org": org, **counts}
        print(m["state"], org, counts, flush=True)
    return out
