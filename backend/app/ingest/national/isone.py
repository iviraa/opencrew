"""ISO-NE RSP Project List and Asset Condition List (June 2026): kV and stations live in the description text."""
import json
import re

import pandas as pd

from app.db import ROOT
from app.ingest.national.common import clean, clear, find_station, register_org, register_source, save, to_date

DIR = "data/raw/national/isone-rsp"
LISTS = [("RSP", "final_rsp_project_list_jun_2026.xlsx", "RSP_sortable", "Project ID", "Project"),
         ("ACL", "final_asset_condition_list_jun_2026.xlsx", "ACL_sortable", "Asset Condition ID", "Description")]
OWNERS = {"CT": ["Eversource"], "MA": ["Eversource"], "NH": ["Eversource"], "ME": ["Central Maine Power Company"],
          "RI": ["Rhode Island Energy"], "VT": ["Vermont Electric Power Company"]}
LIVE = {"Planned": "planned", "Proposed": "proposed", "Under Construction": "under construction", "Concept": "concept"}
NEIGHBORS = {"CT": ["MA", "RI", "NY"], "MA": ["CT", "RI", "NH", "VT", "NY"], "NH": ["MA", "ME", "VT"], "ME": ["NH"],
             "RI": ["MA", "CT"], "VT": ["NH", "MA", "NY"]}

KV = re.compile(r"(\d{2,3})\s*-?\s*kV", re.I)
STA = r"(?i:substations?|switching stations?|switchyards?|stations?|s/s)"
W = r"[A-Z][\w.'’&]*"  # one capitalized word
NAME = rf"({W}(?:[ -]+(?:{W}|St\.?|of))*)"  # e.g. West Walpole, K-Street, Hartford Ave
NAME_ND = rf"({W}(?: (?:{W}|St\.?))*)"  # same without hyphens, for dash-joined line names
OWNER_POSS = re.compile(r"\b(?:[A-Z]{2,5}|NEP|RIE|CMP|ES|VELCO)['’]s\s+")  # "NEP’s Millbury" -> "Millbury"
CODE = re.compile(r"\b(?:[A-Z]{1,3}-?\d+[A-Z]*|\d+[A-Z]+)\b")  # line and station codes like E183W, T-172N, 48C
DASHED = re.compile(rf"((?:{NAME_ND} ?[-–] ?){{1,3}}{NAME_ND})(?: \d+ ?kV)? (?i:line|corridor|rebuild|reconductor|circuit|structure)")
PAIRS = [
    re.compile(r"\(([^()]+?) [-–] ([^()]+?)\)"),  # "the K43 (New Haven - Williston) 115 kV line"
    re.compile(rf"between (?:the )?{NAME}(?: \d+ ?kV)?(?: {STA})? and (?:the )?{NAME}(?: \d+ ?kV)? {STA}"),
    re.compile(rf"{NAME}(?: \d+ ?kV)? {STA} (?:to|-|–) {NAME}(?: \d+ ?kV)? {STA}"),
    re.compile(rf"from (?:the )?{NAME}(?: \d+ ?kV)?(?: {STA})? to (?:the )?{NAME}(?: \d+ ?kV)?(?: {STA}|\b)"),
    re.compile(rf"{NAME_ND} to {NAME_ND} (?i:rebuild|reconductor|line)"),
]
SINGLES = [
    re.compile(rf"\b(?:at|to|in|of) (?:the )?(?:existing |new )?(?:\d+ ?kV )?{NAME}(?: #?\d+[A-Z]?)?(?: \d+ ?kV)? (?:{STA}|(?i:bus|ring))"),
    re.compile(rf"{NAME}(?: #?\d+[A-Z]?)?(?: \d+ ?kV)? {STA}"),
    re.compile(rf"{STA} \(([^)]+)\)"),  # "substations (Stoughton, West Walpole and Holbrook)"
]
NEW_IN = re.compile(rf"(?i:new|construct|install)[^.]*?{STA}[^.]*?\bin ({W}(?: {W})?)")  # a new station named after its town
STOP = {"the", "existing", "substation", "substations", "station", "stations", "switching", "switchyard", "line", "lines", "asset", "condition", "replacement", "refurbishment", "project", "install", "installation",
        "addition", "add", "upgrade", "upgrades", "relay", "protection", "systems", "structure", "structures", "nerc", "cip", "round", "site",
        "breaker", "breakers", "bay", "ring", "bus", "transformer", "capacitor", "reactor", "shunt", "static", "series", "a", "an", "and",
        "one", "two", "three", "four", "rebuild", "rebuilds", "separation", "cable", "shielding", "control", "house", "tie", "physical",
        "security", "section", "tap", "kv", "v", "program", "underground", "modernization", "segment", "jct", "junction", "corridor", "partial",
        "hq", "near", "uprate", "reconductor", "es", "velco", "cmp", "full", "bps"}


def tidy(name):
    """Station name without owners, kV, codes and filler words, or None."""
    name = OWNER_POSS.sub("", name or "")
    name = re.sub(r"\b\d+\s*-?\s*kV\b|#\s*\d+\w*", " ", name, flags=re.I)
    name = re.sub(r"\b\d+\b", " ", CODE.sub(" ", name))
    words = [w for w in re.split(r"\s+", name.strip(" ,.;:-–")) if w.strip("-–")]
    while words and words[0].lower().strip("-–") in STOP:
        words.pop(0)
    while words and words[-1].lower().strip("-–") in STOP:
        words.pop()
    out = " ".join(words).strip(" ,.;:-–")
    return out if re.search(r"[A-Za-z]{3}", out) and out.lower() not in STOP else None


def stations(text):
    """Up to two station names named in a description, best evidence first."""
    text = re.sub(r"\s+", " ", str(text or ""))
    for rx in PAIRS:
        m = rx.search(text)
        if m:
            ends = [e for e in dict.fromkeys(tidy(g) for g in m.groups()[:2]) if e]
            if ends:
                return ends[:2]
    m = DASHED.search(CODE.sub(" ", text).replace("  ", " "))
    if m:
        parts = [tidy(x) for x in re.split(r" ?[-–] ?", m.group(1))]
        parts = [x for x in parts if x]
        if len(parts) >= 2:
            return list(dict.fromkeys([parts[0], parts[-1]]))
    found = []
    for rx in SINGLES:
        for m in rx.finditer(text):
            parts = re.split(r",\s*|\s+and\s+", m.group(1)) if rx.pattern.startswith(STA) else [m.group(1)]
            found += [tidy(x) for x in parts]
    found = [f for f in dict.fromkeys(found) if f]
    if not found:
        m = NEW_IN.search(text)
        if m:
            found = [tidy(m.group(1))]
    return [f for f in found if f][:2]


def kv(text):
    vals = [int(v) for v in KV.findall(str(text or "")) if 34 <= int(v) <= 765]
    return max(vals) if vals else None


def frame(name, file, sheet):
    df = pd.read_excel(ROOT / DIR / file, sheet)
    df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]
    df["owner"] = df["Primary Equipment Owner"].astype(str).str.strip()
    return df


def rows(frames, state):
    for kind, df, id_col, text_col in frames:
        mine = df[(df["State"] == state) & df["owner"].isin(OWNERS[state]) & df["Jun-26 Status"].isin(LIVE)]
        for _, r in mine.iterrows():
            isd = to_date(r["Projected In-Service Month/Year"])
            if isd and isd.year < 2024:
                continue
            text = clean(r[text_col]) or ""
            group = clean(r.get("Major Project") if kind == "RSP" else r.get("Asset Condition Grouping"))
            ident = f"{int(r[id_col])}" if pd.notna(r[id_col]) else str(r.name)
            part = re.sub(r"\W", "", str(r["Part#"])).lower() if kind == "RSP" and pd.notna(r.get("Part#")) else "0"  # parts like "2a"
            cost = r.get("Jun-26 Estimated PTF Costs")
            yield {
                "id": f"isone-{kind.lower()}-{ident}-{part}",
                "name": text[:120] if len(text) <= 120 else text[:117] + "...", "description": " / ".join(x for x in (group, text) if x) or None,
                "voltage_kv": kv(text), "in_service": isd, "start": None, "status": LIVE[r["Jun-26 Status"]],
                "need": clean(r.get("Primary Driver")), "length_mi": None,
                "cost_usd": float(cost) * 1e6 if pd.notna(cost) and isinstance(cost, (int, float)) else None,  # listed in $M
                "ends": stations(text), "states": [state, *NEIGHBORS[state]], "counties": None,
                "source_project_id": f"ISO-NE {kind} {ident}", "planner": "ISO-NE", "state": state,
                "raw": {"list": kind, **{k: clean(v) for k, v in r.items() if not re.match(r"(Mar|Jun|Oct)-\d\d (Status|Estimated)", k) or k.startswith("Jun-26")}},
            }


def load(conn, manifest="data/raw/national/manifest_east.json", states=None):
    frames = [(kind, frame(kind, f, s), id_col, text_col) for kind, f, s, id_col, text_col in LISTS]
    out = {}
    for m in json.loads((ROOT / manifest).read_text()):
        if m["state"] not in OWNERS or (states and m["state"] not in states):
            continue
        org = m["slug"]
        register_org(conn, org, m["utility"], m["utility"].split(" (")[0], m["state"], "ISO-NE", m["slug"])
        clear(conn, org)
        doc = register_source(conn, org, "ISO-NE RSP Project List and Asset Condition List", m["url"], f"{DIR}/{LISTS[0][1]}", "ISO-NE", "June 2026")
        counts = {"placed": 0, "review": 0}
        for p in rows(frames, m["state"]):
            home = [find_station(e, [m["state"]]) for e in p["ends"]]
            if p["ends"] and all(home):
                p["states"] = [m["state"]]  # home state first, so a same-named station next door can't make it ambiguous
            counts[save(conn, {**p, "org_id": org}, doc)] += 1
        out[m["state"]] = {"org": org, **counts}
        print(m["state"], org, counts, flush=True)
    return out
