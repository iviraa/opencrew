"""Idaho Power local transmission plan, Table B-1 (1-5 year horizon): title and scope cells that wrap across lines."""
import hashlib
import re
from datetime import date

from app.ingest.national.west_common import kv_of, manifest, pdf_text, pick_ends, run, start_org

HORIZON_END = date(2028, 12, 31)  # plan dated Dec 2025; 1-5 years is 2026-2030, so the middle year 2028 stands in for in-service
STATES = ["ID", "OR", "WY"]


def table_b1(text):
    """Rows of Table B-1 as {region, frame, title, scope}; wrapped lines go to the nearest row line."""
    lines = text.splitlines()
    start = max(i for i, l in enumerate(lines) if l.strip() == "Table B-1")  # the last one is the table, earlier ones are the contents
    end = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == "Table B-2")
    cols, cells = None, []  # (line index, region, frame, title, scope)
    for i in range(start, end):
        l = lines[i]
        if "Project Title" in l and "Project Scope" in l:
            cols = (l.index("Time Frame"), l.index("Project Title"), l.index("Project Scope"))
            continue
        if not cols or not l.strip() or re.search(r"Local Transmission Plan|Idaho Power Company|Appendix B", l):
            continue
        tf, ti, sc = cols
        cells.append((i, l[:tf].strip(), l[tf:ti].strip(), l[ti:sc].strip(), l[sc:].strip()))
    anchors = [c for c in cells if c[1] and c[2]]
    rows = [{"region": a[1], "frame": a[2], "title": [], "scope": [], "at": a[0]} for a in anchors]
    for c in cells:  # in line order
        dist = [(abs(c[0] - r["at"]), k) for k, r in enumerate(rows)]
        best = min(d for d, _ in dist)
        near = [k for d, k in dist if d == best]
        k = near[-1] if len(near) > 1 and (c[3] or c[4])[:1].isupper() else near[0]  # a tie starting with a capital opens the next row
        prev = rows[k - 1] if k > 0 and rows[k]["at"] > c[0] > rows[k - 1]["at"] else None
        if c[4] and prev and prev["scope"] and not prev["scope"][-1][1].endswith("."):
            prev["scope"].append((c[0], c[4]))  # the previous row's sentence is not finished yet
        elif c[4]:
            rows[k]["scope"].append((c[0], c[4]))
        if c[3]:
            rows[k]["title"].append((c[0], c[3]))
    return [{"region": r["region"], "frame": r["frame"], "title": " ".join(t for _, t in sorted(r["title"])),
             "scope": " ".join(s for _, s in sorted(r["scope"]))} for r in rows]


def rows(text):
    for n, r in enumerate(table_b1(text), 1):
        if not r["title"]:
            continue
        yield {
            "id": "ipco-" + hashlib.md5(r["title"].lower().encode()).hexdigest()[:10], "name": r["title"], "description": r["scope"] or None,
            "voltage_kv": kv_of(r["title"]) or kv_of(r["scope"]), "in_service": HORIZON_END, "start": None, "status": "planned (1-5 year horizon)",
            "need": None, "length_mi": None, "cost_usd": None, "ends": pick_ends(r["title"], r["scope"], STATES), "states": STATES, "counties": None,
            "source_project_id": f"Table B-1 row {n}", "planner": "Idaho Power local transmission plan", "state": "ID",
            "raw": {**r, "row": n, "in_service_note": "source gives only the 1-5 year horizon; in-service set to the end of 2028, the middle year"},
        }


def load(conn, only=None):
    if only and "ID" not in only:
        return {}
    text = pdf_text(manifest("ID")["file"])
    org, doc = start_org(conn, "ID", "Idaho Power local plan", "Idaho Power 2024-2025 Final Local Transmission Plan, Appendix B", "Dec 2025")
    out = {"ID": {"org": org, **run(conn, org, doc, rows(text))}}
    print("ID", out["ID"], flush=True)
    return out
