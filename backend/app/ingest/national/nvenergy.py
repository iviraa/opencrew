"""NV Energy 2026 annual progress report to WECC: one prose entry per project, dates written in the text."""
import hashlib
import re
from datetime import date

from app.ingest.national.west_common import kv_of, manifest, month_year, pdf_text, pick_ends, run, start_org, year_end

GEN = re.compile(r"\b(MW|solar|geothermal|BESS|peaker|PV)\b", re.I)


def entries(text):
    """(area, heading, paragraph) for each project; a heading is a short line after a blank that doesn't end a sentence."""
    lines = [l for l in text.splitlines() if "<Public>" not in l]
    out, area, prev_blank = [], None, True
    for i, l in enumerate(lines):
        s = l.strip()
        if s in ("NV Energy North", "NV Energy South"):
            area, prev_blank = s.split()[-1], True
            continue
        nxt = next((x.strip() for x in lines[i + 1:i + 3] if x.strip()), "")
        if (area and prev_blank and s and len(s) < 90 and not s.endswith((".", ",", ":")) and ":" not in s and s[:1].isupper()
                and nxt and not s.startswith(("NV Energy", "To:", "March"))):
            out.append({"area": area, "title": s, "text": []})
        elif out and s:
            out[-1]["text"].append(s)
        prev_blank = not s
    return out


def isd(text):
    """Latest date in the entry: projects often finish in phases, the last one is when it is done."""
    found = [d for d in month_year(text) if d.year >= 2024]
    found += [year_end(y) for y in re.findall(r"\b(?:ISD|in service date|in-service date)\)?\s*(?:of|is|in|by|planned|for)?\s*(20\d\d)\b", text, re.I)]
    found += [year_end(y) for y in re.findall(r"\bin (20[2-4]\d)\b", text) if int(y) >= 2024]
    return max(found) if found else None


def rows(text):
    for e in entries(text):
        body = " ".join(e["text"])
        when = isd(body)
        if not when or when < date(2024, 1, 1):
            continue
        kind = "generator interconnection" if GEN.search(e["title"]) and "kV" not in e["title"] else "reliability and load service"
        yield {
            "id": "nve-" + hashlib.md5(e["title"].lower().encode()).hexdigest()[:10], "name": e["title"], "description": body[:4000],
            "voltage_kv": kv_of(e["title"]) or kv_of(body), "in_service": when, "start": None, "status": "planned", "need": kind,
            "length_mi": float(m.group(1)) if (m := re.search(r"(\d+(?:\.\d+)?)[- ]mile", body)) else None, "cost_usd": None,
            "ends": pick_ends(e["title"], body, ["NV"]), "states": ["NV"], "counties": None,
            "source_project_id": None, "planner": "WECC annual progress report", "state": "NV",
            "raw": {"area": e["area"], "heading": e["title"], "text": body, "in_service_rule": "latest date written in the entry"},
        }


def load(conn, only=None):
    if only and "NV" not in only:
        return {}
    text = pdf_text(manifest("NV")["file"])
    org, doc = start_org(conn, "NV", "WECC progress report", "NV Energy 2026 Annual Progress Report to WECC", "March 2026")
    out = {"NV": {"org": org, **run(conn, org, doc, rows(text))}}
    print("NV", out["NV"], flush=True)
    return out
