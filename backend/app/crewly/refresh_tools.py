"""Crewly abilities over the planner refreshes: what is current, what a new edition changes, and applying one after a tap."""
from app.refresh import api as refresh_api, stage
from app.refresh.sources import SOURCES


def _bind(ctx, fn):
    return lambda conn, **kw: fn(ctx, conn, **kw)


def _key(source):
    s = str(source or "").strip().lower().replace(" ", "")
    for k, src in SOURCES.items():
        if s in (k, src.planner.lower()):
            return k
    return None


def _brief(c):
    return {k: c[k] for k in ("id", "source", "planner", "status", "edition", "checked_at", "summary", "needs_review", "error", "running")}


def check_for_updates(ctx, conn, source=None, run=False):
    keys = [_key(source)] if source else list(SOURCES)
    if source and not keys[0]:
        return {"error": f"I only refresh {', '.join(s.planner for s in SOURCES.values())}"}, []
    if run:
        started = {k: refresh_api.start(k) for k in keys}
        rows = [c for c in refresh_api.status(conn) if c["source"] in keys]
        return {"started": started, "sources": [_brief(c) for c in rows],
                "next_step": "the check runs in the background (a minute or two per planner); ask 'what changed' afterwards"}, [{"type": "refresh", "refresh": rows}]
    rows = [c for c in refresh_api.status(conn) if c["source"] in keys]
    return {"sources": [_brief(c) for c in rows], "note": "statuses: unchanged = same file as loaded, staged = a new edition waits, "
            "promoted = applied, rejected = the file's shape drifted so it was refused"}, [{"type": "refresh", "refresh": rows}]


def what_changed(ctx, conn, source):
    k = _key(source)
    if not k:
        return {"error": f"I only refresh {', '.join(s.planner for s in SOURCES.values())}"}, []
    rows = stage.latest(conn, k, ["staged", "promoted"])
    if not rows:
        last = stage.latest(conn, k)
        return {"source": k, "note": "no new edition has been staged or promoted for this planner", "last_check": last and refresh_api.card(last[0])}, []
    c = refresh_api.card(rows[0])
    d = rows[0]["diff"]
    return {**_brief(c), "counts": c["diff"], "samples": d.get("samples"), "review_rows": d.get("review"),
            "next_step": "promote_update applies a staged edition after the user taps Apply on the card"}, [{"type": "refresh", "refresh": [c]}]


def promote_update(ctx, conn, source):
    k = _key(source)
    if not k:
        return {"error": f"I only refresh {', '.join(s.planner for s in SOURCES.values())}"}, []
    rows = stage.latest(conn, k, ["staged"])
    if not rows:
        return {"source": k, "note": "nothing is staged for this planner; run check_for_updates first"}, []
    c = refresh_api.card(rows[0])
    return {**_brief(c), "counts": c["diff"], "next_step": "nothing is applied until the user taps Apply update on the card"}, [{"type": "refresh", "refresh": [c], "ask": True}]


def refresh_tools(ctx):
    planners = ", ".join(s.planner for s in SOURCES.values())
    return {
        "check_for_updates": (_bind(ctx, check_for_updates), f"Whether the planner project lists we load ({planners}) have a newer edition than what is on "
                              "the map: the last check per source, its status and a summary. run=true starts a fresh check in the background.", {
            "source": {"type": "string", "description": "one planner, e.g. PJM; omit for all"},
            "run": {"type": "boolean", "description": "true to fetch the planners' sites now instead of reading the last check"}}, []),
        "what_changed": (_bind(ctx, what_changed), "The diff of the latest staged or promoted edition for one planner: projects added, changed "
                         "(which fields), removed, and how many rows need review. Shows a refresh card.", {
            "source": {"type": "string", "description": "one planner, e.g. MISO"}}, ["source"]),
        "promote_update": (_bind(ctx, promote_update), "Offer to apply a staged edition: shows the card with an Apply update button. Nothing changes "
                           "until the user taps it.", {"source": {"type": "string"}}, ["source"]),
    }


PROMPT = """
- For "is there a newer PJM list", "any updates from the planners", "refresh the sources" call check_for_updates (run=true when they ask
  to check now). For "what changed", "what's new in the MISO update" call what_changed. For "apply it", "promote the update", "use the new
  edition" call promote_update and say the Apply button on the card does it; never say an update was applied unless the tool result says
  promoted. A rejected edition means the planner changed the file's layout; say the old data stays live and a person needs to look."""
