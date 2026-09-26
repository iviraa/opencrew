"""Puget Sound Energy plan (OATT Attachment K): numbered planned projects per region with need and operation dates."""
import hashlib
import re

from app.ingest.national.west_common import counties_in, kv_of, manifest, pdf_text, pick_ends, run, start_org, year_end

TITLE = re.compile(r"^\s{0,8}(\d{1,2})\.\s+(\S.*)$")
PAGE = re.compile(r"^Updated \d+/\d+/\d+\s+\d+ \| Page|^\s*Figure \d")


def blocks(text):
    """Planned projects: (region, number, title, need date, operation year, description)."""
    out, region, live, cur = [], None, False, None
    for line in text.splitlines():
        if PAGE.match(line):
            continue
        s = line.strip()
        if "Identified Needs and Planned Projects" in s:
            live, region, cur = True, s.split("–")[-1].replace("Region", "").strip(), None
            continue
        if "Recently Completed Projects" in s:
            live, cur = False, None
            continue
        if not live:
            continue
        m = TITLE.match(line)
        if m and not s.endswith("."):
            cur = {"region": region, "n": int(m.group(1)), "title": m.group(2).strip(), "need": None, "year": None, "text": []}
            out.append(cur)
        elif cur and s.startswith("Need Date:"):
            cur["need"] = s.split(":", 1)[1].strip()
        elif cur and s.startswith("Estimated Date of Operation:"):
            y = re.search(r"20\d\d", s)
            cur["year"] = int(y.group()) if y else None
        elif cur and s:
            cur["text"].append(s)
    return out


def rows(text):
    for b in blocks(text):
        if not b["year"]:
            continue
        desc = " ".join(b["text"])[:4000]
        yield {
            "id": "pse-" + hashlib.md5(f"{b['region']}|{b['title']}".lower().encode()).hexdigest()[:10], "name": b["title"], "description": desc,
            "voltage_kv": kv_of(b["title"]) or kv_of(desc), "in_service": year_end(b["year"]), "start": None, "status": "planned",
            "need": f"need date {b['need']}" if b["need"] else None, "length_mi": None, "cost_usd": None,
            "ends": pick_ends(b["title"], desc, ["WA"]), "states": ["WA"], "counties": counties_in(desc, "WA") or None,
            "source_project_id": f"{b['region']} #{b['n']}", "planner": "PSE Attachment K", "state": "WA",
            "raw": {"region": b["region"], "number": b["n"], "title": b["title"], "need_date": b["need"], "estimated_date_of_operation": b["year"],
                    "description": desc},
        }


def load(conn, only=None):
    if only and "WA" not in only:
        return {}
    text = pdf_text(manifest("WA")["file"])
    org, doc = start_org(conn, "WA", "PSE Attachment K", "2025 PSE Plan, OATT Attachment K", "updated 12/16/2025")
    out = {"WA": {"org": org, **run(conn, org, doc, rows(text))}}
    print("WA", out["WA"], flush=True)
    return out
