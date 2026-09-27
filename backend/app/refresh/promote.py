"""Make a staged edition live: reload it for real, keep history for what moved, drop what vanished, rebuild only the touched overlaps."""
import json
import os
import shutil
from datetime import datetime, timezone

import httpx

from app.companies import companies
from app.db import ROOT, connect
from app.engine.overlap import recompute
from app.refresh import stage
from app.refresh.sources import SOURCES, src_file

AUTO_MAX_SHARE = 0.4  # more than this much of a load changing or vanishing waits for a person


def _rest(path, method="GET", **kw):
    key = os.environ.get("SUPABASE_SECRET_KEY")
    url = os.environ.get("SUPABASE_URL")
    if not key or not url:
        return None  # local runs without supabase still promote; they just do not ring anyone's bell
    r = httpx.request(method, f"{url.rstrip('/')}/rest/v1/{path}", headers={"apikey": key, **kw.pop("headers", {})}, timeout=15, **kw)
    if r.status_code == 409:
        return None  # dedup_key already there
    r.raise_for_status()
    return r.json() if r.content else None


def notify(rows, rest=_rest):
    """One bell entry per company, deduplicated by key; a failed insert never fails the promote."""
    out = []
    for row in rows:
        try:
            rest("notification", "POST", json=row, headers={"Prefer": "return=representation"})
            out.append(row["dedup_key"])
        except Exception as e:
            print("refresh notify failed:", e)
    return out


def affected_companies(conn, touched):
    """Companies whose own projects changed, or whose overlaps touch one that did."""
    if not touched:
        return set()
    ids = list(touched)
    own = {r["org_id"] for r in conn.execute("SELECT DISTINCT org_id FROM job WHERE id = ANY(%s)", (ids,)).fetchall()}
    near = {r["org_id"] for r in conn.execute("""SELECT DISTINCT j.org_id FROM opportunity o JOIN job j ON j.id IN (o.job_a, o.job_b)
                                                   WHERE o.job_a = ANY(%s) OR o.job_b = ANY(%s)""", (ids, ids)).fetchall()}
    return {c for c in own | near if c in companies()}


def promote(refresh_id, rest=_rest, loader=None):
    """Apply a staged source_refresh row; returns the row with the counts of what it did."""
    with connect() as c:
        stage.ensure(c)
        row = c.execute("SELECT * FROM source_refresh WHERE id = %s", (refresh_id,)).fetchone()
    if not row:
        raise ValueError(f"no refresh #{refresh_id}")
    if row["status"] != "staged":
        raise ValueError(f"refresh #{refresh_id} is {row['status']}, only a staged edition can be promoted")
    src = SOURCES[row["source"]]
    rel = row["staged_path"]
    if not (ROOT / rel).exists():
        raise ValueError(f"the staged file {rel} is gone; run the check again")
    conn = connect()
    try:
        orgs = stage.orgs_for(conn, src)
        old = stage.snapshot(conn, orgs)
        counts, docs = (loader or stage.load_staged)(conn, src, rel)
        new = stage.snapshot(conn, stage.orgs_for(conn, src))
        touched = {i for i, r in new.items() if r["source_doc_id"] in docs}
        d = stage.diff(old, new, touched)
        removed, changed = d["removed"], [x["id"] for x in d["changed"]]
        observed = datetime.now(timezone.utc)
        for i in changed:  # the window the earlier edition carried, kept as history
            o = old[i]
            conn.execute("INSERT INTO job_version (job_id, observed_at, work_window, source_doc_id) VALUES (%s, %s, %s, %s)",
                         (i, observed, o["work_window"], o["source_doc_id"]))
        if removed:
            conn.execute("DELETE FROM job WHERE id = ANY(%s)", (removed,))  # versions and overlaps go with them
        redo = sorted(set(d["added"]) | set(changed))
        overlaps = recompute(conn, "long", only_jobs=redo) if redo else None
        conn.execute("UPDATE source_doc SET fetched_at = now(), url = %s, edition = %s WHERE id = ANY(%s)", (row["url"], row["edition"], docs))
        who = affected_companies(conn, set(redo) | set(removed))
        conn.commit()
    except Exception:
        conn.rollback()
        with connect() as c:
            c.execute("UPDATE source_refresh SET status = 'failed', error = %s WHERE id = %s", ("promote failed; see server log", refresh_id))
        raise
    finally:
        conn.close()
    target = ROOT / src_file(src)
    if target.exists():
        shutil.copy2(target, target.with_suffix(target.suffix + ".prev"))
    shutil.copy2(ROOT / rel, target)  # the loader's file is now this edition, so a reboot reloads the same thing
    d["overlaps"] = overlaps
    with connect() as c:
        c.execute("UPDATE source_refresh SET status = 'promoted', promoted_at = now(), diff = %s WHERE id = %s", (json.dumps(d), refresh_id))
    d["notified"] = notify([bell(row, src, d, company) for company in sorted(who)], rest)
    return {**row, "status": "promoted", "diff": d}


def bell(row, src, d, company):
    return {"company_id": company, "kind": "suggestion", "dedup_key": f"refresh:{row['source']}:{row['sha256'][:10]}",
            "title": f"{src.planner} published a new project list"[:80],
            "body": f"Edition {row['edition']}: {stage.summary(d)}. Overlaps were rebuilt for the projects that moved.",
            "action": {"type": "chat", "prompt": f"What changed in the {src.planner} refresh?"}}


def waiting_bell(row, src, company):
    return {"company_id": company, "kind": "suggestion", "dedup_key": f"refresh-review:{row['source']}:{row['sha256'][:10]}",
            "title": f"{src.planner} update needs a look"[:80],
            "body": f"Edition {row['edition']}: {stage.summary(row['diff'])}. That is a big move, so nothing was applied.",
            "action": {"type": "chat", "prompt": f"Show me what changed in the {src.planner} update"}}


def refresh_once(keys=None, rest=_rest, check=None, apply=None):
    """The loop body: check every source, promote the small updates, ring the bell for the big ones; one source's failure never stops the rest."""
    out = {}
    for key in keys or list(SOURCES):
        try:
            row = (check or stage.check)(key)
            out[key] = {"status": row["status"], "edition": row.get("edition"), "error": row.get("error")}
            if row["status"] != "staged":
                continue
            share = stage.review_share(row["diff"])
            if share <= AUTO_MAX_SHARE:
                done = (apply or promote)(row["id"], rest)
                out[key].update(status="promoted", summary=stage.summary(done["diff"]))
            else:
                with connect() as c:
                    who = {o for o in stage.orgs_for(c, SOURCES[key]) if o in companies()}
                out[key].update(status="staged", summary=stage.summary(row["diff"]), waiting=True,
                                notified=notify([waiting_bell(row, SOURCES[key], c_) for c_ in sorted(who)], rest))
        except Exception as e:  # keep going with the next planner
            out[key] = {"status": "failed", "error": f"{type(e).__name__}: {str(e)[:200]}"}
            print(f"refresh {key} failed:", e)
    return out
