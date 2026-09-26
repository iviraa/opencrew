"""BPA 2025 transmission plan, section 8.7.2 Northwest Montana: proposed plans of service with costs and energization."""
import hashlib
import re

from app.ingest.national.west_common import kv_of, manifest, pdf_text, pick_ends, run, start_org, year_end

SECTION = ("8.7.2", "8.7.3")  # Northwest Montana area, up to the next area
BULLET = re.compile(r"^\s*•\s*(Description|Purpose|Estimated Costs|Expected Energization):\s*(.*)$")


def plans(text):
    lines = text.splitlines()
    start = max(i for i, l in enumerate(lines) if l.strip().startswith(SECTION[0]) and "Montana" in l)
    end = next(i for i in range(start + 1, len(lines)) if lines[i].strip().startswith(SECTION[1]))
    out, live, key = [], False, None
    for l in lines[start:end]:
        s = l.strip()
        if s.startswith("Proposed Plans of Service"):
            live = True
            continue
        if s.startswith("Recently Completed"):
            break
        if not live or not s or "Page" in s and "|" in s or s.startswith("B O N N E V I L L E"):
            continue
        m = BULLET.match(l)
        if m:
            key = m.group(1)
            out[-1][key] = m.group(2).strip()
        elif not s.startswith("•") and key is None or (key and not l.startswith(" " * 14)):
            out.append({"title": s})
            key = None
        elif out and key:
            out[-1][key] += " " + s  # wrapped bullet text
    return out


def rows(text):
    for p in plans(text):
        when = re.search(r"20\d\d", p.get("Expected Energization", ""))
        cost = re.sub(r"[^\d.]", "", p.get("Estimated Costs", ""))
        desc = p.get("Description")
        yield {
            "id": "bpa-mt-" + hashlib.md5(p["title"].lower().encode()).hexdigest()[:10], "name": p["title"], "description": desc,
            "voltage_kv": kv_of(p["title"]) or kv_of(desc), "in_service": year_end(when.group()) if when else None, "start": None,
            "status": "proposed", "need": p.get("Purpose"), "length_mi": None, "cost_usd": float(cost) if cost else None,
            "ends": pick_ends(p["title"], desc, ["MT", "ID"]), "states": ["MT", "ID"], "counties": None,
            "source_project_id": None, "planner": "BPA transmission plan", "state": "MT", "raw": p,
        }


def load(conn, only=None):
    if only and "MT" not in only:
        return {}
    text = pdf_text(manifest("MT")["file"])
    org, doc = start_org(conn, "MT", "BPA transmission plan", "BPA 2025 Transmission Plan, section 8.7.2 Northwest Montana", "2025")
    out = {"MT": {"org": org, **run(conn, org, doc, rows(text))}}
    print("MT", out["MT"], flush=True)
    return out
