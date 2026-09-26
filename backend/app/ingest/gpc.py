import re
from datetime import date

from app.config import DEFAULT_DURATION_MONTHS
from app.ingest.classify import endpoints, job_type, parse_date, shift_months, voltage

ROW = re.compile(r"(?m)^(?P<zone>\d{3}) (?P<year>20\d\d) (?P<ref>\d{4,6}) (?P<name>.+?)\n?(?P<need>\d{1,2}/\d{1,2}/\d{4}) (?P<sponsor>GPC|GTC|MEAG|SAV|DU)\b", re.S)
DETAIL = re.compile(r"Teams # (?P<ref>\d+)\s*\nNeed Date (?P<need>\d\d/\d\d/\d{4})\s+Start Date (?P<start>\d\d/\d\d/\d{4})")
DESC = re.compile(r"parity forecast purposes only\s*\n(?P<desc>.+?)\n(?:REDACTED|No Change|PUBLIC DISCLOSURE)", re.S)
CHANGES = re.compile(r"parity forecast purposes only\s*\n.+?\nREDACTED\n(?P<ten>.+?)\n(?P<irp>.+?)\n", re.S)
MOVE = re.compile(r"(?:delayed|advanced) from (\d{4}) to (\d{4})", re.I)
PRIOR = {"ten": date(2023, 12, 31), "irp": date(2022, 1, 31)}  # previous ten year plan and previous IRP
ORG = {"GPC": "gpc", "SAV": "gpc"}  # SAV = Georgia Power Savannah zone


def project_list(pages):
    start = next(i for i, p in enumerate(pages) if "Table 2 Georgia ITS 10 Year Plan Project List" in p)
    end = next(i for i in range(start, len(pages)) if "Cancelled Projects List" in pages[i])
    out = {}
    for i in range(start, end + 1):
        text = pages[i].split("Cancelled Projects List")[0]
        for m in ROW.finditer(text):
            out[m["ref"]] = {**m.groupdict(), "name": " ".join(m["name"].split()), "page": i + 1}
    return out


def details(pages):
    out = {}
    for i, text in enumerate(pages):
        for m in DETAIL.finditer(text):
            d = DESC.search(text, m.end())
            c = CHANGES.search(text, m.end())
            history = []
            for key in ("ten", "irp"):
                move = MOVE.search(c[key]) if c else None
                if move:
                    history.append({"observed": PRIOR[key], "year_shift": int(move[1]) - int(move[2]), "note": c[key].strip()})
            out.setdefault(m["ref"], {**m.groupdict(), "page": i + 1, "desc": " ".join(d["desc"].split()) if d else None, "history": history})
    return out


def parse(pages):
    rows, bad = [], []
    listed, detail = project_list(pages), details(pages)
    for ref, r in listed.items():
        org = ORG.get(r["sponsor"])
        if not org:
            continue  # GTC / MEAG / DU are other ITS members
        d = detail.get(ref)
        isd = parse_date(d["need"] if d else r["need"])
        kind = job_type(r["name"])
        start = parse_date(d["start"]) if d else shift_months(isd, -DEFAULT_DURATION_MONTHS[kind])
        if start >= isd:
            start, basis = shift_months(isd, -DEFAULT_DURATION_MONTHS[kind]), "default_duration"
        else:
            basis = "filed" if d else "default_duration"
        rows.append({
            "id": f"gpc-{ref}", "org_id": org, "name": r["name"], "ref": ref, "description": d["desc"] if d else None,
            "status": None, "job_type": kind, "voltage_kv": voltage(r["name"]), "endpoints": endpoints(r["name"]),
            "start": start, "in_service": isd, "window_basis": basis, "cost_usd": None,
            "source_page": d["page"] if d else r["page"], "zone": r["zone"], "history": d["history"] if d else [],
        })
    return rows, bad
