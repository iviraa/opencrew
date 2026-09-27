"""Fetch a planner's current edition, validate it, load it into a transaction we roll back, and keep only the diff and the file."""
import hashlib
import importlib
import json
import traceback
from datetime import datetime, timezone

from app.db import ROOT, connect
from app.ingest.national import common
from app.refresh import drift
from app.refresh.sources import SOURCES, discover, fetch, staged_path

DDL = """
CREATE TABLE IF NOT EXISTS source_refresh (
  id            SERIAL PRIMARY KEY,
  source        TEXT NOT NULL,
  url           TEXT,
  edition       TEXT,
  sha256        TEXT,
  found_via     TEXT,
  status        TEXT NOT NULL,              -- unchanged | rejected | staged | promoted | failed
  checked_at    TIMESTAMPTZ DEFAULT now(),
  validation    JSONB,
  diff          JSONB,
  staged_path   TEXT,
  promoted_at   TIMESTAMPTZ,
  error         TEXT
);
CREATE INDEX IF NOT EXISTS source_refresh_source_idx ON source_refresh (source, checked_at DESC);
"""
FIELDS = ["name", "status", "voltage_kv", "cost_usd", "in_service", "start", "end"]  # what a changed project is compared on
SNAPSHOT_SQL = """SELECT id, org_id, name, status, voltage_kv, cost_usd, in_service::text, lower(work_window)::date::text AS start,
                         upper(work_window)::date::text AS "end", source_doc_id, work_window
                  FROM job WHERE org_id = ANY(%s)"""


def ensure(conn):
    conn.execute(DDL)


def orgs_for(conn, src):
    return [r["id"] for r in conn.execute("SELECT id FROM org WHERE planner = %s ORDER BY id", (src.planner,)).fetchall()]


def canonical_sha(src):
    from app.refresh.sources import src_file
    p = ROOT / src_file(src)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def snapshot(conn, orgs):
    return {r["id"]: r for r in conn.execute(SNAPSHOT_SQL, (orgs,)).fetchall()}


def load_staged(conn, src, rel_path):
    """Run the source's loader against the staged file: same ids, so rows upsert in place; nothing of the old load is deleted.

    Returns the loader's counts and the ids of the source_doc rows it registered for this file.
    """
    mod = importlib.import_module(f"app.ingest.national.{src.module}")
    real_register, real_clear, real_file = common.register_source, common.clear, getattr(mod, "FILE", None)

    def register(conn_, org_id, title, url, path, planner, edition):
        return real_register(conn_, org_id, title, url, rel_path, planner, edition)  # the staged file, whatever the loader names

    def clear(conn_, org_id):
        conn_.execute("DELETE FROM job_review WHERE org_id = %s", (org_id,))  # jobs stay so their ids, versions and overlaps survive

    patched = [(common, "register_source", real_register), (common, "clear", real_clear)]
    for name_, fn in (("register_source", register), ("clear", clear)):
        setattr(common, name_, fn)
        if hasattr(mod, name_):
            patched.append((mod, name_, getattr(mod, name_)))
            setattr(mod, name_, fn)
    if real_file is not None:
        mod.FILE = rel_path
    try:
        counts = mod.load(conn)
    finally:
        for target, name_, fn in patched:
            setattr(target, name_, fn)
        if real_file is not None:
            mod.FILE = real_file
    sha = hashlib.sha256((ROOT / rel_path).read_bytes()).hexdigest()
    docs = [r["id"] for r in conn.execute("SELECT id FROM source_doc WHERE sha256 = %s", (sha,)).fetchall()]
    return counts, docs


def diff(old, new, touched):
    """Projects added, removed and changed between two snapshots; `touched` are the ids the new file carried."""
    added = sorted(i for i in touched if i not in old)
    removed = sorted(i for i in old if i not in touched)
    changed = []
    for i in sorted(touched):
        if i in old and i in new:
            deltas = {f: [old[i][f], new[i][f]] for f in FIELDS if _ne(old[i][f], new[i][f])}
            if deltas:
                changed.append({"id": i, "name": new[i]["name"], "org_id": new[i]["org_id"], "changes": deltas})
    return {"added": added, "removed": removed, "changed": changed, "old_count": len(old), "new_count": len(touched),
            "samples": {"added": [{"id": i, "name": new[i]["name"], "org_id": new[i]["org_id"]} for i in added[:8]],
                        "removed": [{"id": i, "name": old[i]["name"], "org_id": old[i]["org_id"]} for i in removed[:8]],
                        "changed": changed[:8]}}


def _ne(a, b):
    if a is None or b is None:
        return (a is None) != (b is None)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) > 1e-6
    return str(a) != str(b)


def summary(d):
    """One line a person can read: what a promote would do."""
    if not d:
        return "no diff yet"
    n = d["old_count"] or 1
    share = (len(d["changed"]) + len(d["removed"])) / n
    return (f"{len(d['added'])} new, {len(d['changed'])} changed, {len(d['removed'])} gone out of {d['old_count']} "
            f"({share:.0%} of the load moves)")


def review_share(d):
    return (len(d["changed"]) + len(d["removed"])) / (d["old_count"] or 1) if d else 1.0


def record(row):
    """Write the outcome on its own connection, after the trial load has been rolled back."""
    with connect() as c:
        ensure(c)
        r = c.execute("""INSERT INTO source_refresh (source, url, edition, sha256, found_via, status, validation, diff, staged_path, error)
                         VALUES (%(source)s, %(url)s, %(edition)s, %(sha256)s, %(found_via)s, %(status)s, %(validation)s, %(diff)s, %(staged_path)s, %(error)s)
                         RETURNING id""",
                      {**row, "validation": json.dumps(row.get("validation")), "diff": json.dumps(row.get("diff"))}).fetchone()
    return {**row, "id": r["id"]}


def latest(conn, source=None, statuses=None):
    ensure(conn)
    sql = "SELECT * FROM source_refresh WHERE TRUE"
    args = []
    if source:
        sql += " AND source = %s"
        args.append(source)
    if statuses:
        sql += " AND status = ANY(%s)"
        args.append(list(statuses))
    return conn.execute(sql + " ORDER BY checked_at DESC, id DESC", args).fetchall()


def check(key, get=None, post=None, force=False):
    """Discover, fetch, validate and trial-load one source; returns the source_refresh row it wrote (never raises past a failed row)."""
    src = SOURCES[key]
    row = {"source": key, "url": None, "edition": None, "sha256": None, "found_via": None, "status": "failed", "validation": None,
           "diff": None, "staged_path": None, "error": None}
    try:
        url, edition, how = discover(src, get)
        row.update(url=url, edition=edition, found_via=how)
        body = fetch(src, url, get, post)
        sha = hashlib.sha256(body).hexdigest()
        row["sha256"] = sha
        if sha == canonical_sha(src):
            row["status"] = "unchanged"
            return record(row)
        with connect() as c:
            seen = latest(c, key)
            same = next((s for s in seen if s["sha256"] == sha and s["status"] in ("rejected", "staged", "promoted")), None)
        if same and not force:
            return dict(same)  # this edition was already judged
        path, _ = staged_path(src, body)
        rel = str(path.relative_to(ROOT))
        row["staged_path"] = rel
        from app.refresh.sources import src_file
        baseline = drift.validate(ROOT / src_file(src), src)["row_count"] if (ROOT / src_file(src)).exists() else None
        v = drift.validate(path, src, baseline)
        row["validation"] = v
        if not v["ok"]:
            row["status"], row["error"] = "rejected", v["message"]
            return record(row)
        conn = connect()
        try:
            orgs = orgs_for(conn, src)
            old = snapshot(conn, orgs)
            counts, docs = load_staged(conn, src, rel)
            new = snapshot(conn, orgs_for(conn, src))
            touched = {i for i, r in new.items() if r["source_doc_id"] in docs}
            d = diff(old, new, touched)
            d["counts"] = {k: v_ for k, v_ in counts.items()} if isinstance(counts, dict) else None
            d["review"] = conn.execute("SELECT count(*) AS n FROM job_review WHERE source_doc_id = ANY(%s)", (docs,)).fetchone()["n"]
        finally:
            conn.rollback()  # the trial load never lands; promote() redoes it for real
            conn.close()
        row["diff"], row["status"] = d, "staged"
        return record(row)
    except Exception as e:  # any surprise is a failed row, never a half-written table
        row["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        traceback.print_exc()
        return record(row)


def now():
    return datetime.now(timezone.utc)
