"""PacifiCorp local transmission plan, Appendix 2 (PacifiCorp East): Rocky Mountain Power's Utah projects."""
import hashlib
import re

from app.ingest.national.west_common import kv_of, manifest, month_year, pdf_text, pick_ends, run, start_org, title_ends

HEAD = re.compile(r"^[A-Z0-9][A-Z0-9 &#/().,'–-]{7,}$")
STATES = ["UT", "ID", "WY"]


def blocks(text):
    """(title, lettered fields) for each project between Appendix 2 and Appendix 3."""
    lines = text.splitlines()
    start = max(i for i, l in enumerate(lines) if l.strip().startswith("APPENDIX 2"))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("APPENDIX 3")), len(lines))
    out = []
    for i in range(start + 1, end):
        s = lines[i].strip()
        nxt = next((x.strip() for x in lines[i + 1:i + 3] if x.strip()), "")
        if HEAD.match(s) and any(c.isalpha() for c in s) and (nxt.startswith(("Project Description", "A.")) or "Participants" in nxt):
            out.append({"title": s, "lines": []})
        elif out and s and not s.startswith("Project Description") and not re.match(r"^\d+$|^PacifiCorp|^Local Transmission", s):
            out[-1]["lines"].append(s)
    for b in out:
        body = " ".join(b["lines"])
        b["fields"] = {k.lower(): v for k, v in re.findall(r"\b[A-E]\.\s+(Participants|Status|Facilities|Studies|Impact on other systems):\s*(.*?)(?=\s+[A-E]\.\s+(?:Participants|Status|Facilities|Studies|Impact on other systems):|$)", body)}
        b["body"] = body
    return out


def rows(text):
    for b in blocks(text):
        status = b["fields"].get("status", "")
        dates = month_year(status)
        if not dates:
            continue  # "beyond 10 year plan" has no date to plan against
        title = b["title"].title().replace("Kv", "kV")
        facilities = b["fields"].get("facilities", "")
        yield {
            "id": "pacw-ut-" + hashlib.md5(b["title"].lower().encode()).hexdigest()[:10], "name": title, "description": facilities or None,
            "voltage_kv": kv_of(b["title"]) or kv_of(facilities), "in_service": max(dates), "start": None,
            "status": status.split(".")[0].strip().lower() or None, "need": (b["fields"].get("studies") or "")[:300] or None,
            "length_mi": float(m.group(1)) if (m := re.search(r"(\d+(?:\.\d+)?)[- ]mile", facilities)) else None, "cost_usd": None,
            "ends": pick_ends(title, facilities, STATES), "states": STATES, "counties": None,
            "source_project_id": None, "planner": "PacifiCorp local transmission plan", "state": "UT",
            "raw": {"title": b["title"], **b["fields"], "title_stations": title_ends(title)},
        }


def load(conn, only=None):
    if only and "UT" not in only:
        return {}
    text = pdf_text(manifest("UT")["file"])
    org, doc = start_org(conn, "UT", "PacifiCorp local plan", "PacifiCorp 2024-2025 Local Transmission System Plan, Q4 draft", "Dec 2024")
    out = {"UT": {"org": org, **run(conn, org, doc, rows(text))}}
    print("UT", out["UT"], flush=True)
    return out
