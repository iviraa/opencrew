"""Refresh endpoints for the chat card: status per source, one row's diff, start a check, apply a staged edition."""
import threading

from fastapi import APIRouter, Depends, HTTPException

from app.auth import current_user
from app.db import get_conn
from app.refresh import promote, stage
from app.refresh.sources import SOURCES

router = APIRouter(prefix="/api/app/refresh")
RUNNING = {}  # source -> thread, so two people cannot start the same check


def card(row, src=None):
    """What the chat and the card show for one source_refresh row (no file paths, no stack traces)."""
    src = src or SOURCES[row["source"]]
    d = row.get("diff") or None
    return {"id": row.get("id"), "source": row["source"], "planner": src.planner, "name": src.name, "status": row["status"],
            "edition": row.get("edition"), "url": row.get("url"), "found_via": row.get("found_via"),
            "checked_at": row["checked_at"].isoformat() if row.get("checked_at") else None,
            "promoted_at": row["promoted_at"].isoformat() if row.get("promoted_at") else None,
            "validation": (row.get("validation") or {}).get("message"), "error": row.get("error"),
            "summary": stage.summary(d) if d else None, "needs_review": bool(d) and stage.review_share(d) > promote.AUTO_MAX_SHARE,
            "diff": d and {"added": len(d["added"]), "changed": len(d["changed"]), "removed": len(d["removed"]), "old_count": d["old_count"],
                           "new_count": d["new_count"], "review": d.get("review"), "samples": d.get("samples"), "overlaps": d.get("overlaps")},
            "cadence_days": src.cadence_days, "running": row["source"] in RUNNING and RUNNING[row["source"]].is_alive()}


def status(conn):
    """The latest row per source, with the sources never checked shown as such."""
    rows = stage.latest(conn)
    seen = {}
    for r in rows:
        seen.setdefault(r["source"], r)
    return [card(seen[k]) if k in seen else card({"source": k, "status": "never", "checked_at": None}) for k in SOURCES]


def start(source):
    """Run a check in the background; the row lands in source_refresh when it is done."""
    if source not in SOURCES:
        raise HTTPException(404, f"unknown source {source}")
    t = RUNNING.get(source)
    if t and t.is_alive():
        return {"started": False, "running": True}
    t = threading.Thread(target=stage.check, args=(source,), daemon=True, name=f"refresh-{source}")
    RUNNING[source] = t
    t.start()
    return {"started": True, "running": True}


@router.get("")
def list_status(user=Depends(current_user), conn=Depends(get_conn)):
    return status(conn)


@router.get("/{refresh_id}")
def one(refresh_id: int, user=Depends(current_user), conn=Depends(get_conn)):
    row = conn.execute("SELECT * FROM source_refresh WHERE id = %s", (refresh_id,)).fetchone()
    if not row:
        raise HTTPException(404, "no such refresh")
    return card(row)


@router.post("/check/{source}")
def check(source: str, user=Depends(current_user)):
    return start(source)


@router.post("/{refresh_id}/promote")
def apply(refresh_id: int, user=Depends(current_user)):
    try:
        row = promote.promote(refresh_id)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return card(row)
