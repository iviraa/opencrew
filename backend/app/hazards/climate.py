"""History by month: NOAA Storm Events event-days per county, month and hazard, plus FEMA's county risk scores as a backup."""
import csv
import gzip
import io
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta

import httpx

from app.hazards.config import CLIMATE_YEARS, EVENT_TYPES, HEADERS, NRI_FIELDS, NRI_QUERY, RAW_EVENTS
from app.hazards.layers import FIPS_STATE, zone_counties

MAX_EVENT_DAYS = 10  # a flood that lasts weeks still counts as a short stop for building purposes
DAMAGE = {"K": 1e3, "M": 1e6, "B": 1e9}


def damage_usd(s):
    m = re.fullmatch(r"\s*([\d.]+)\s*([KMB])?\s*", str(s or ""), re.I)
    return float(m.group(1)) * DAMAGE.get((m.group(2) or "").upper(), 1) if m else 0.0


def event_counties(r, zones):
    """County FIPS an event row touches: its county, or every county of its NWS zone."""
    st = str(r["STATE_FIPS"]).zfill(2)
    cz = str(r["CZ_FIPS"]).zfill(3)
    if r["CZ_TYPE"] == "C":
        return [st + cz]
    abbr = FIPS_STATE.get(st)
    return zones.get(f"{abbr}Z{cz}", []) if abbr else []


def event_days(r):
    """Calendar days the event spans, capped."""
    fmt = "%d-%b-%y %H:%M:%S"
    try:
        start = datetime.strptime(r["BEGIN_DATE_TIME"], fmt).date()
        end = datetime.strptime(r["END_DATE_TIME"], fmt).date()
    except (ValueError, KeyError):
        return []
    n = min(max((end - start).days, 0), MAX_EVENT_DAYS - 1)
    return [start + timedelta(days=i) for i in range(n + 1)]


def tally(rows, zones):
    """(county, month, hazard) -> {days: set of dates, damage: usd} for one year's rows."""
    out = defaultdict(lambda: {"days": set(), "damage": 0.0})
    for r in rows:
        hazard = EVENT_TYPES.get(r.get("EVENT_TYPE"))
        if not hazard:
            continue
        days = event_days(r)
        fips = event_counties(r, zones)
        dmg = damage_usd(r.get("DAMAGE_PROPERTY")) / max(len(fips), 1)
        for f in fips:
            for d in days:
                out[(f, d.month, hazard)]["days"].add(d)
            if days:
                out[(f, days[0].month, hazard)]["damage"] += dmg
    return out


def read_year(year):
    path = next(iter(sorted(RAW_EVENTS.glob(f"StormEvents_details-ftp_v1.0_d{year}_c*.csv.gz"))), None)
    if not path:
        return None
    with gzip.open(path, "rt", encoding="utf-8", errors="ignore") as f:
        yield from csv.DictReader(f)


def build(conn, years=CLIMATE_YEARS, zones=None):
    """Stream each year once, sum distinct event-days per county-month-hazard, and store the table."""
    zones = zones if zones is not None else zone_counties()
    total, damage, seen = defaultdict(int), defaultdict(float), []
    for y in years:
        rows = read_year(y)
        if rows is None:
            continue
        seen.append(y)
        for key, v in tally(rows, zones).items():
            total[key] += len(v["days"])
            damage[key] += v["damage"]
    conn.execute("DELETE FROM hazard_climate")
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO hazard_climate (county_fips, state, month, hazard, event_days, years, damage_usd) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        [(f, FIPS_STATE.get(f[:2]), m, h, n, len(seen), round(damage[(f, m, h)])) for (f, m, h), n in total.items()])
    return {"years": seen, "rows": len(total)}


def fetch_nri():
    """FEMA National Risk Index county scores for our hazards, without geometry (we have the counties)."""
    fields = ["STCOFIPS", "STATEABBRV", "COUNTY", "RISK_SCORE", *NRI_FIELDS]
    out, offset = [], 0
    while True:
        r = httpx.get(NRI_QUERY, headers=HEADERS, timeout=90, params={"where": "1=1", "outFields": ",".join(fields), "returnGeometry": "false",
                                                                     "f": "json", "resultOffset": offset, "resultRecordCount": 2000})
        r.raise_for_status()
        feats = r.json().get("features", [])
        out += [f["attributes"] for f in feats]
        if len(feats) < 2000:
            return out
        offset += 2000


def scores(r):
    """Worst FEMA score per hazard when several fields map to one (winter: winter weather, ice storm, cold wave)."""
    out = {}
    for k, h in NRI_FIELDS.items():
        out[h] = max(out.get(h, 0.0), float(r.get(k) or 0))
    return out


def store_nri(conn, rows):
    conn.execute("DELETE FROM hazard_nri")
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO hazard_nri (county_fips, state, county, risk_score, scores) VALUES (%s, %s, %s, %s, %s)",
                        [(r["STCOFIPS"], r.get("STATEABBRV"), r.get("COUNTY"), r.get("RISK_SCORE"),
                          json.dumps(scores(r)))
                         for r in rows if r.get("STCOFIPS")])
    return len(rows)
