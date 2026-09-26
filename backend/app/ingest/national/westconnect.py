"""WestConnect public project list: Xcel Colorado (PSCo) and Cheyenne Light Fuel & Power in Wyoming."""
import re

import pandas as pd

from app.db import ROOT
from app.ingest.national.common import clean
from app.ingest.national.west_common import kv_of, pick_ends, run, start_org, title_ends, year_end

FILE = "data/raw/national/westconnect-tppl/02_10_26_wc_tppl_project_list_public.xlsm"
SPONSORS = {"CO": "Public Service Company of Colorado/ Xcel Energy", "WY": "Cheyenne Light Fuel and Power"}
LIVE = {"Planned", "Under Construction"}
STATE_NAMES = {"Colorado": "CO", "Wyoming": "WY", "Nebraska": "NE", "New Mexico": "NM", "Utah": "UT", "Kansas": "KS"}


def station(v):
    s = clean(v)
    return None if not s or s.upper() == "TBD" or re.fullmatch(r"[A-Za-z .]+,\s*[A-Z]{2}", s) else s  # "Cheyenne, WY" is a town, not a station


def rows(df, state):
    mine = df[(df["Sponsor"] == SPONSORS[state]) & df["Development"].isin(LIVE)]
    for _, r in mine.iterrows():
        yr = str(r["InService"]).strip()
        isd = year_end(yr[:4]) if re.fullmatch(r"20\d\d(\.0)?", yr) else None
        if isd and isd.year < 2024:
            continue
        length = pd.to_numeric(r["Length"], errors="coerce")
        text = f"{clean(r['Description']) or ''} {clean(r['Purpose']) or ''}".strip()
        ends = [e for v in (station(r["Origin"]), station(r["Termination"])) if v
                for e in (title_ends(v) if re.search(r"\bline\b|\s[–-]\s", v, re.I) else [v])][:2]  # a hookup on a line: that line's two ends
        if len(ends) == 2 and ends[0] == ends[1]:
            ends = ends[:1]  # a substation project lists itself as both ends
        states = list(dict.fromkeys([state] + [STATE_NAMES[s.strip()] for s in str(r["StateTraversed"]).split(",") if s.strip() in STATE_NAMES]))
        yield {
            "id": f"wc-{r['wcprojectID'] if pd.notna(r['wcprojectID']) else r['projectid']}", "name": clean(r["ProjectName"]), "description": text or None,
            "voltage_kv": kv_of(r["Voltage"]), "in_service": isd, "start": None, "status": str(r["Development"]).lower(),
            "need": clean(r["Drivers"]), "length_mi": float(length) if pd.notna(length) else None, "cost_usd": None,
            "ends": ends or pick_ends(clean(r["ProjectName"]), text, states), "states": states, "counties": None,
            "source_project_id": str(r["wcprojectID"]), "planner": "WestConnect", "state": state,
            "raw": {k: clean(v) for k, v in r.items() if not str(k).startswith("Unnamed")},
        }


def load(conn, only=None):
    df = pd.read_excel(ROOT / FILE, "All Projects", header=0)
    out = {}
    for state in SPONSORS:
        if only and state not in only:
            continue
        org, doc = start_org(conn, state, "WestConnect", "WestConnect regional transmission plan public project list", "02/10/2026")
        out[state] = {"org": org, **run(conn, org, doc, rows(df, state))}
        print(state, out[state], flush=True)
    return out
