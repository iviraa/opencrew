"""Portland General Electric local transmission plan: project table with completion dates, plus each project's write-up."""
import hashlib
import re

from rapidfuzz import fuzz

from app.ingest.national.west_common import MONTHS, kv_of, manifest, pdf_text, pick_ends, run, start_org
from datetime import date

ROW = re.compile(r"^\s*(\S.*?)\s{3,}(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d\d)\s*$")


def table(text):
    """(name, date, group) rows from both 'Project Name / Project Completion Date' tables; wrapped names are joined."""
    out, group, live = [], None, False
    for line in text.splitlines():
        if "Project Completion Date" in line:
            live = True
            continue
        if not live:
            continue
        m = ROW.match(line)
        if m:
            out.append([m.group(1).strip(), date(int(m.group(3)), MONTHS[m.group(2).lower()], 1), group])
        elif line.strip() and out and len(line.strip()) < 60 and not line.strip().endswith(".") and line.startswith("    "):
            out[-1][0] += " " + line.strip()  # second line of a wrapped name
        elif line.strip():
            live = False  # prose ends the table
    return out


def writeups(text):
    """Heading -> 'Justification: ... Scope: ...' paragraphs that follow the tables."""
    lines, out = text.splitlines(), {}
    for i, line in enumerate(lines):
        if line.startswith("Justification:") and i > 0:
            head = next((lines[j].strip() for j in range(i - 1, max(i - 4, -1), -1) if lines[j].strip()), "")
            body = []
            for nxt in lines[i:]:
                if nxt.strip() and not nxt.startswith((" ", "Justification", "Scope")) and body and body[-1] == "":
                    break
                body.append(nxt.strip())
            out[head] = " ".join(b for b in body if b)[:3000]
    return out


def rows(text):
    notes = writeups(text)
    for name, isd, _ in table(text):
        name = " ".join(name.split())
        head = max(notes, key=lambda h: fuzz.token_set_ratio(h, name), default=None)
        desc = notes[head] if head and fuzz.token_set_ratio(head, name) >= 80 else None
        yield {
            "id": "pgeor-" + hashlib.md5(name.lower().encode()).hexdigest()[:10], "name": name, "description": desc, "voltage_kv": kv_of(name) or kv_of(desc),
            "in_service": isd, "start": None, "status": "planned", "need": "reliability" if desc and "TPL" in desc else None,
            "length_mi": None, "cost_usd": None, "ends": pick_ends(name, desc, ["OR", "WA"]), "states": ["OR", "WA"], "counties": None,
            "source_project_id": None, "planner": "PGE local transmission plan", "state": "OR",
            "raw": {"project_name": name, "completion": isd.isoformat(), "writeup_heading": head if desc else None, "writeup": desc},
        }


def load(conn, only=None):
    if only and "OR" not in only:
        return {}
    text = pdf_text(manifest("OR")["file"])
    org, doc = start_org(conn, "OR", "PGE local plan", "PGE 2024-2025 Local Transmission Plan v1.1", "2024-25 v1.1")
    out = {"OR": {"org": org, **run(conn, org, doc, rows(text))}}
    print("OR", out["OR"], flush=True)
    return out
