import re
from datetime import date

from app.config import DEFAULT_DURATION_MONTHS
from app.ingest.classify import endpoints, job_type, parse_date, shift_months, voltage

PAGE = re.compile(
    r"5 Year Budget\s*\n(?P<name>.+?)\nProject ID\s*\n(?P<ref>.+?)\nProject Description\s*\n(?P<desc>.+?)\n"
    r"Project Need\s*\n(?P<need>.+?)\nProject Status\s*\n(?P<status>.+?)\nPlanned In-Service Date\s*\n(?P<isd>.+?)\n"
    r"Estimated Project Cost\s*\n(?P<hdr>.+?)\n(?P<vals>.+?)\n", re.S)


def spend_window(costs, isd, kind):
    years = sorted(int(k) for k, v in costs.items() if k.isdigit() and v > 0)
    fallback = shift_months(isd, -DEFAULT_DURATION_MONTHS[kind])
    if not years:
        return fallback, "default_duration"
    start = date(years[0], 1, 1)
    if costs.get("Previous", 0) > 0 or start >= isd:  # work began before the budget table
        start = min(start, fallback) if start < isd else fallback
    return start, "spend_years"


def parse(pages):
    rows, bad = [], []
    for i, text in enumerate(pages, start=1):
        m = PAGE.search(text)
        if not m:
            bad.append({"page": i, "reason": "layout not recognised", "text": text[:500]})
            continue
        g = {k: " ".join(v.split()) for k, v in m.groupdict().items()}
        hdr = g["hdr"].replace("Total*", "Total").split()
        vals = [float(v.replace("$", "").replace(",", "") or 0) for v in g["vals"].split()]
        costs = dict(zip(hdr, vals))
        isd = parse_date(g["isd"])
        kind = job_type(g["name"])
        start, basis = spend_window(costs, isd, kind)
        rows.append({
            "id": f"desc-{g['ref'].lower().replace(' ', '').replace(',', '-')}", "org_id": "desc", "name": g["name"], "ref": g["ref"],
            "description": g["desc"], "status": g["status"], "job_type": kind, "voltage_kv": voltage(g["name"]),
            "endpoints": endpoints(g["name"]), "start": start, "in_service": isd, "window_basis": basis,
            "cost_usd": costs.get("Total"), "source_page": i,
        })
    return rows, bad
