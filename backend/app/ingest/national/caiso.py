"""CAISO Transmission Development Forum: approved PG&E projects, stations read from the project names."""
import pandas as pd

from app.db import ROOT
from app.ingest.national.common import clean, to_date
from app.ingest.national.west_common import kv_of, pick_ends, run, start_org

FILE = "data/raw/national/caiso-tdf/approved-projects-transmission-planning-process-jul-2026.xlsx"
DONE = {"Cancelled", "In-Service"}
NEED = {"R": "reliability", "P": "policy", "E": "economic"}  # letter in the TP project id, e.g. 2526-R-02


def rows(df):
    seen = {}
    for _, r in df.iterrows():
        status = str(r["Project Status"]).strip()
        isd = to_date(r["Current In-Service July 2026 TDF"])
        if status in DONE or not isinstance(r["Project"], str):
            continue
        if isd and isd.year < 2024:
            continue
        tp = str(r["TP Project ID"])
        name = " ".join(r["Project"].split())
        seen[tp] = seen.get(tp, 0) + 1  # a few ids repeat for phases of one project
        pid = f"caiso-{tp}" if seen[tp] == 1 else f"caiso-{tp}-{seen[tp]}"
        yield {
            "id": pid, "name": name,
            "description": clean(r["Notes"]), "voltage_kv": kv_of(name), "in_service": isd, "start": to_date(r["Expected Construction Start"]),
            "status": status.lower().replace("in flight", "in-flight"), "need": NEED.get(tp.split("-")[1] if tp.count("-") >= 2 else "", None),
            "length_mi": None, "cost_usd": None, "ends": pick_ends(name, name, ["CA"]), "states": ["CA"], "counties": None,
            "source_project_id": tp, "planner": "CAISO", "state": "CA", "raw": {k: clean(v) for k, v in r.items()},
        }


def load(conn, only=None):
    if only and "CA" not in only:
        return {}
    df = pd.read_excel(ROOT / FILE, "PGaE", header=0)
    org, doc = start_org(conn, "CA", "CAISO", "CAISO Transmission Development Forum: approved TPP projects", "July 2026 TDF")
    out = {"CA": {"org": org, **run(conn, org, doc, rows(df))}}
    print("CA", out["CA"], flush=True)
    return out
