import json
from collections import Counter
from datetime import date

from app.db import ROOT, connect, init_schema
from app.outreach import seed_contacts
from app.engine.overlap import recompute
from app.engine.phases import build_phases
from app.geo.geolocate import Locator
from app.ingest import desc, gpc, pdf

ORGS = [("desc", "Dominion Energy South Carolina", "#2563eb"), ("gpc", "Georgia Power", "#dc2626")]
FILINGS = [
    ("desc", "DESC Planned Transmission Projects $2M+ (2024-2028)", "data/raw/desc_2024_2028_projects.pdf", desc, date(2024, 1, 1)),
    ("gpc", "Georgia Power 2025 IRP Vol. 3 Transmission Plan (public disclosure)", "data/raw/gpc_2025_irp_vol3.pdf", gpc, date(2024, 12, 31)),
]


def geometry(job, picks):
    found = [p for p in picks if p]
    if not found:
        return None
    pts = [f"{p['lon']} {p['lat']}" for p in found]
    conf = min(p["conf"] for p in found)
    if job["job_type"] == "substation" or len(found) == 1:
        partial = job["job_type"] != "substation" and len(picks) > 1
        return f"POINT({pts[0]})", "partial_point" if partial else "matched_point", round(conf * (0.8 if partial else 1), 3)
    return f"LINESTRING({pts[0]}, {pts[1]})", "straight_line", conf


def main():
    loc = Locator()
    with connect() as conn:
        init_schema(conn, reset=True)
        conn.cursor().executemany("INSERT INTO org (id, name, color) VALUES (%s, %s, %s)", ORGS)
        seed_contacts(conn)
        stats = Counter()
        for org, title, rel, parser, observed in FILINGS:
            pages = pdf.read_pages(ROOT / rel)
            blocked = pdf.ceii_blocked(pages)
            doc_id = conn.execute("INSERT INTO source_doc (org_id, title, local_path, kind, ceii_flag) VALUES (%s, %s, %s, 'filing', %s) RETURNING id",
                                  (org, title, rel, blocked)).fetchone()["id"]
            if blocked:
                print("CEII: skipped", title)
                continue
            rows, bad = parser.parse(pages)
            for b in bad:
                conn.execute("INSERT INTO job_review (org_id, raw, reason, source_doc_id, source_page) VALUES (%s, %s, %s, %s, %s)",
                             (org, json.dumps(b), b["reason"], doc_id, b["page"]))
            for job in rows:
                if not pdf.page_allowed(pages[job["source_page"] - 1]):
                    stats["ceii_page"] += 1
                    continue
                picks = loc.place(org, job["endpoints"] or [job["name"]], job["name"])
                geo = geometry(job, picks)
                if not geo:
                    raw = {**job, "start": str(job["start"]), "in_service": str(job["in_service"])}
                    conn.execute("INSERT INTO job_review (org_id, raw, reason, source_doc_id, source_page) VALUES (%s, %s, 'no location match', %s, %s)",
                                 (org, json.dumps(raw), doc_id, job["source_page"]))
                    stats[f"{org}_unplaced"] += 1
                    continue
                wkt, quality, conf = geo
                conn.execute("""
                    INSERT INTO job (id, org_id, name, ref, description, horizon, job_type, voltage_kv, endpoints, geom, geom_quality,
                                     work_window, window_basis, in_service, cost_usd, source_doc_id, source_page, extraction, confidence, resources)
                    VALUES (%(id)s, %(org_id)s, %(name)s, %(ref)s, %(description)s, 'long', %(job_type)s, %(voltage_kv)s, %(endpoints)s,
                            ST_GeogFromText(%(wkt)s), %(quality)s, tstzrange(%(start)s, %(in_service)s), %(window_basis)s, %(in_service)s,
                            %(cost_usd)s, %(doc)s, %(source_page)s, 'parser', %(conf)s, %(resources)s)""",
                             {**job, "wkt": wkt, "quality": quality, "conf": conf, "doc": doc_id, "resources": ["crews", "row", "staging"],
                              "matches": [p and p["via"] for p in picks]})
                conn.execute("INSERT INTO job_version (job_id, observed_at, work_window, source_doc_id) VALUES (%s, %s, tstzrange(%s, %s), %s)",
                             (job["id"], observed, job["start"], job["in_service"], doc_id))
                stats[f"{org}_placed"] += 1
        print(dict(stats))
        print(recompute(conn, "long"))
        print("phases", build_phases(conn), recompute(conn, "near"))


if __name__ == "__main__":
    main()
