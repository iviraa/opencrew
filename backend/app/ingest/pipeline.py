import json
from collections import Counter

from dateutil.relativedelta import relativedelta

from app.ingest import pdf

UPSERT_JOB = """
INSERT INTO job (id, org_id, name, ref, description, horizon, job_type, voltage_kv, endpoints, geom, geom_quality,
                 work_window, window_basis, in_service, cost_usd, source_doc_id, source_page, extraction, confidence, resources)
VALUES (%(id)s, %(org_id)s, %(name)s, %(ref)s, %(description)s, 'long', %(job_type)s, %(voltage_kv)s, %(endpoints)s,
        ST_GeogFromText(%(wkt)s), %(quality)s, tstzrange(%(start)s, %(in_service)s), %(window_basis)s, %(in_service)s,
        %(cost_usd)s, %(doc)s, %(source_page)s, %(extraction)s, %(conf)s, ARRAY['crews', 'row', 'staging'])
ON CONFLICT (id) DO UPDATE SET work_window = EXCLUDED.work_window, window_basis = EXCLUDED.window_basis, in_service = EXCLUDED.in_service,
  description = EXCLUDED.description, source_doc_id = EXCLUDED.source_doc_id, source_page = EXCLUDED.source_page
"""  # a newer filing updates the plan; job_version keeps the history


def geometry(job, picks, router=None):
    found = [p for p in picks if p]
    if not found:
        return None
    pts = [f"{p['lon']} {p['lat']}" for p in found]
    conf = min(p["conf"] for p in found)
    if job["job_type"] == "substation" or len(found) == 1:
        partial = job["job_type"] != "substation" and len(picks) > 1
        return f"POINT({pts[0]})", "partial_point" if partial else "matched_point", round(conf * (0.8 if partial else 1), 3)
    path = router.route((found[0]["lon"], found[0]["lat"]), (found[1]["lon"], found[1]["lat"])) if router else None
    if path:
        return "LINESTRING(" + ", ".join(f"{x} {y}" for x, y in path) + ")", "existing_path", conf  # follows a mapped line
    return f"LINESTRING({pts[0]}, {pts[1]})", "straight_line", conf


def review(conn, org, raw, reason, doc_id, page):
    conn.execute("INSERT INTO job_review (org_id, raw, reason, source_doc_id, source_page) VALUES (%s, %s, %s, %s, %s)",
                 (org, json.dumps(raw, default=str), reason, doc_id, page))


def store(conn, loc, org, doc_id, pages, rows, bad, observed, extraction="parser", router=None):
    stats = Counter()
    conn.execute("DELETE FROM job_review WHERE org_id = %s AND raw->>'id' = ANY(%s)", (org, [j["id"] for j in rows]))  # re-ingest replaces old entries
    for b in bad:
        review(conn, org, b, b["reason"], doc_id, b.get("page"))
        stats["invalid"] += 1
    for job in rows:
        if not pdf.page_allowed(pages[job["source_page"] - 1]):
            stats["ceii_page"] += 1
            continue
        picks = loc.place(org, job["endpoints"] or [job["name"]], job["name"])
        geo = geometry(job, picks, router)
        if not geo:
            review(conn, org, job, "no location match", doc_id, job["source_page"])
            stats["unplaced"] += 1
            continue
        wkt, quality, conf = geo
        conn.execute(UPSERT_JOB, {**job, "wkt": wkt, "quality": quality, "conf": conf, "doc": doc_id, "extraction": extraction})
        conn.execute("INSERT INTO job_version (job_id, observed_at, work_window, source_doc_id) VALUES (%s, %s, tstzrange(%s, %s), %s)",
                     (job["id"], observed, job["start"], job["in_service"], doc_id))
        for h in job.get("history", []):  # earlier plans stated in the filing, e.g. "delayed from 2025 to 2026"
            shift = relativedelta(years=h["year_shift"])
            conn.execute("INSERT INTO job_version (job_id, observed_at, work_window, source_doc_id) VALUES (%s, %s, tstzrange(%s, %s), %s)",
                         (job["id"], h["observed"], job["start"] + shift, job["in_service"] + shift, doc_id))
        stats["placed"] += 1
    return stats


def add_doc(conn, org, title, pages, local_path=None, url=None):
    blocked = pdf.ceii_blocked(pages)
    doc_id = conn.execute("INSERT INTO source_doc (org_id, title, local_path, url, kind, ceii_flag) VALUES (%s, %s, %s, %s, 'filing', %s) RETURNING id",
                          (org, title, local_path, url, blocked)).fetchone()["id"]
    return doc_id, blocked
