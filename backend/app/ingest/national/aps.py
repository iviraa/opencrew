"""APS ten-year plan (Arizona Corporation Commission filing): one page per dated project with origin and termination."""
import hashlib
import re

from app.ingest.national.west_common import kv_of, manifest, pdf_text, pick_ends, run, start_org, year_end

HEADER = "Ten-year Transmission System Plan"
FIELD = re.compile(r"^\s*(Voltage Class|Facility Rating|Point of Origin|Intermediate Points of Interconnection|Point of Termination|Length)\s{2,}(.*)$")


def pages(text):
    chunk = []
    for line in text.splitlines():
        if HEADER in line and chunk:
            yield chunk
            chunk = []
        chunk.append(line)
    yield chunk


def wordy(s):
    """Real text, not scan noise like 'Q£h.¢'L.E@.Lt!§'."""
    ok = sum(c.isascii() and (c.isalnum() or c in " -&/#().,'") for c in s)
    return sum(c.isalpha() for c in s) >= 4 and ok / len(s) >= 0.95


def station(v):
    """'Outer Circle substation (in-service 2027)' -> 'Outer Circle'; lines and ownership points are not stations."""
    v = re.sub(r"\(.*?\)|_", " ", v or "")
    v = re.sub(r"^\W*[Il]\s+(?=[A-Z])|^[^A-Za-z]+", "", v.strip())  # scan leftovers: "_I Ocotillo", "_l Parkway"
    v = re.sub(r"\b\d+\s*kV\b", "", v.replace("Comers", "Corners")).strip()
    if not v or re.search(r"change of ownership|\bline\b|none|tbd", v, re.I):
        return None
    return re.sub(r"\s+(substation|switchyard|switching station|station)\b.*$", "", v, flags=re.I).strip() or None


def project(chunk):
    if not any("Point of Origin" in l for l in chunk):
        return None
    head = [l.strip() for l in chunk[1:12]]
    stop = next((i for i, l in enumerate(head) if l.startswith(("Project Sponsor", "Arizona Public Service Company"))), len(head))
    title = " ".join(l for l in head[:stop] if wordy(l) and "aps" not in l.lower()[-6:])
    at = next(i for i, l in enumerate(chunk) if "Construction Start" in l)
    years, tbd = [], False
    for l in chunk[at + 1:at + 9]:
        if FIELD.match(l) or "Voltage Class" in l:
            break
        years += re.findall(r"\b(20\d\d)\b", l)
        tbd = tbd or "TBD" in l
    fields = {m.group(1): m.group(2).strip() for m in map(FIELD.match, chunk) if m}
    body = "\n".join(chunk)
    purpose = re.search(r"Purpose/Driv\w+ Factor\s*(.*?)(?:Permitt\w+ and Sit\w+ Status|$)", body, re.S)
    routing = re.search(r"Rout\w+\s*(.*?)Purpose/Driv", body, re.S)
    return {"title": title, "start": years[0] if years else None, "isd": years[1] if len(years) > 1 else None, "tbd": tbd, **fields,
            "purpose": " ".join(purpose.group(1).split()) if purpose else None, "routing": " ".join(routing.group(1).split()) if routing else None}


def rows(text):
    for p in filter(None, map(project, pages(text))):
        if not p["isd"] or not p["title"]:
            continue
        ends = [e for e in (station(p.get("Point of Origin")), station(p.get("Point of Termination"))) if e]
        miles = re.search(r"(\d+(?:\.\d+)?)\s*miles?", p.get("Length") or "")
        yield {
            "id": "aps-" + hashlib.md5(p["title"].lower().encode()).hexdigest()[:10], "name": p["title"], "description": p["purpose"],
            "voltage_kv": kv_of(p.get("Voltage Class")), "in_service": year_end(p["isd"]), "start": year_end(p["start"]).replace(month=1) if p["start"] else None,
            "status": "planned", "need": p["purpose"][:200] if p["purpose"] else None, "length_mi": float(miles.group(1)) if miles else None,
            "cost_usd": None, "ends": ends or pick_ends(p["title"], p["routing"], ["AZ"]), "states": ["AZ"], "counties": None,
            "source_project_id": None, "planner": "ACC ten-year plan", "state": "AZ", "raw": p,
        }


def load(conn, only=None):
    if only and "AZ" not in only:
        return {}
    text = pdf_text(manifest("AZ")["file"])
    org, doc = start_org(conn, "AZ", "ACC ten-year plan", "APS 2026-2035 Ten-Year Transmission System Plan", "2026")
    out = {"AZ": {"org": org, **run(conn, org, doc, rows(text))}}
    print("AZ", out["AZ"], flush=True)
    return out
