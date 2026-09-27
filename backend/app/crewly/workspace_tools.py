"""Crewly's workspace tools: notes, reminders, the request pipeline, company profiles, a weekly brief, overlap history, saved views, bulk edits.

Company data lives in Supabase and is read and written with the user's own login, so row security decides what each company sees.
"""
import json
import re
from datetime import date, datetime, timedelta, timezone

from app.companies import companies, name, partner, short
from app.config import STATUSES
from app.crewly.act_tools import rest

TARGETS = ("overlap", "project", "company", "plan_item")
REMINDER_TARGETS = ("overlap", "request", "plan", "company")
WORKSPACE_ACTIONS = ("note", "reminder", "pipeline", "profile", "brief", "history", "view", "save_view", "views")  # ui_action types the chat renders
BRIEF_DAYS = 7
MAX_ROWS = 50


def _mine(conn, ctx, opportunity_id):
    from app.crewly.app_tools import mine_sql
    return conn.execute(mine_sql(ctx["company"]) + " AND op.id = %s", (int(opportunity_id),)).fetchone()


def _find_company(q):
    from app.crewly.app_tools import find_company
    return find_company(q)


def _now():
    return datetime.now(timezone.utc)


def _iso(v):
    return v.isoformat() if isinstance(v, (datetime, date)) else v


def _usd(n):
    n = float(n or 0)
    return f"${n / 1e6:.1f}M" if n >= 1e6 else f"${round(n / 1e3)}k" if n >= 1e3 else f"${round(n)}"


def _target(kind, ident, allowed=TARGETS):
    kind = (kind or "").strip().lower()
    if kind not in allowed:
        raise ValueError(f"target_kind must be one of {', '.join(allowed)}")
    ident = str(ident or "").strip().lstrip("#")
    if not ident:
        raise ValueError("target_id is required")
    if kind == "company":
        who = _find_company(ident)
        if not who:
            raise ValueError(f"no utility called {ident!r}")
        ident = who
    return kind, ident


# ---------- notes ----------

def add_note(ctx, conn, target_kind, target_id, text):
    kind, ident = _target(target_kind, target_id)
    text = " ".join(str(text or "").split())[:2000]
    if not text:
        return {"error": "nothing to note"}, []
    row = rest(ctx, "POST", "note", json={"target_kind": kind, "target_id": ident, "text": text}, headers={"Prefer": "return=representation"})[0]
    if kind == "overlap":
        rest(ctx, "POST", "overlap_event", json={"opportunity_id": int(ident), "kind": "note", "detail": {"note_id": row["id"], "text": text[:200]}})
    return _notes(ctx, kind, ident), [{"type": "note", "note": _notes(ctx, kind, ident)}]


def _notes(ctx, kind=None, ident=None, limit=MAX_ROWS):
    q = {"select": "id,target_kind,target_id,text,created_at", "order": "created_at.desc", "limit": str(limit)}
    if kind:
        q["target_kind"] = f"eq.{kind}"
    if ident:
        q["target_id"] = f"eq.{ident}"
    rows = rest(ctx, "GET", "note", params=q)
    label = None
    if kind == "company" and ident:
        label = name(ident)
    elif kind == "overlap" and ident:
        label = f"overlap #{ident}"
    elif kind and ident:
        label = f"{kind} {ident}"
    return {"target": {"kind": kind, "id": ident, "label": label} if kind else None, "count": len(rows),
            "notes": [{"id": r["id"], "target_kind": r["target_kind"], "target_id": r["target_id"], "text": r["text"], "when": r["created_at"][:16].replace("T", " ")} for r in rows]}


def list_notes(ctx, conn, target_kind=None, target_id=None):
    kind, ident = _target(target_kind, target_id) if target_kind and target_id else (None, None)
    out = _notes(ctx, kind, ident)
    return out, [{"type": "note", "note": out}]


# ---------- reminders ----------

def _due(due_at, in_days):
    if due_at:
        s = str(due_at).strip()
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"due_at must look like 2027-03-01 or 2027-03-01T09:00, got {s!r}")
        return d if d.tzinfo else d.replace(hour=9 if len(s) <= 10 else d.hour, tzinfo=timezone.utc)
    days = int(in_days if in_days is not None else 7)
    if not 0 <= days <= 3650:
        raise ValueError("in_days must be between 0 and 3650")
    return (_now() + timedelta(days=days)).replace(minute=0, second=0, microsecond=0)


def _reminder_row(r):
    return {"id": r["id"], "text": r["text"], "due": r["due_at"][:16].replace("T", " "), "overdue": r["due_at"] < _now().isoformat(),
            "target_kind": r.get("target_kind"), "target_id": r.get("target_id"), "done": bool(r.get("done_at"))}


def _reminders(ctx, include_done=False):
    q = {"select": "id,text,due_at,target_kind,target_id,done_at", "order": "due_at.asc", "limit": str(MAX_ROWS)}
    if not include_done:
        q["done_at"] = "is.null"
    rows = rest(ctx, "GET", "reminder", params=q)
    return {"count": len(rows), "reminders": [_reminder_row(r) for r in rows]}


def set_reminder(ctx, conn, text, due_at=None, in_days=None, target_kind=None, target_id=None):
    text = " ".join(str(text or "").split())[:500]
    if not text:
        return {"error": "a reminder needs some text"}, []
    kind, ident = _target(target_kind, target_id, REMINDER_TARGETS) if target_kind and target_id else (None, None)
    due = _due(due_at, in_days)
    row = rest(ctx, "POST", "reminder", json={"text": text, "due_at": due.isoformat(), "target_kind": kind, "target_id": ident},
               headers={"Prefer": "return=representation"})[0]
    out = {"saved": True, "reminder": _reminder_row(row), "delivery": "it lands in the bell when due", **_reminders(ctx)}
    return out, [{"type": "reminder", "reminder": out}]


def list_reminders(ctx, conn, include_done=False):
    out = _reminders(ctx, bool(include_done))
    return out, [{"type": "reminder", "reminder": out}]


def done_reminder(ctx, conn, reminder_id):
    rows = rest(ctx, "PATCH", "reminder", params={"id": f"eq.{int(reminder_id)}"}, json={"done_at": _now().isoformat()}, headers={"Prefer": "return=representation"})
    if not rows:
        return {"error": f"no reminder {reminder_id}"}, []
    out = {"done": int(reminder_id), **_reminders(ctx)}
    return out, [{"type": "reminder", "reminder": out}]


def due_reminders(company, fetch):
    """Rows the bell should carry now: due, not done, not yet notified. `fetch` is a REST getter (the proactive scan's)."""
    rows = fetch("reminder", params={"select": "id,text,due_at,target_kind,target_id", "company_id": f"eq.{company}", "done_at": "is.null",
                                     "notified_at": "is.null", "due_at": f"lte.{_now().isoformat()}"})
    action = {"overlap": "open_overlap", "request": "open_request", "plan": "plan", "company": "chat"}
    out = []
    for r in rows:
        a = {"type": action.get(r.get("target_kind") or "", "chat")}
        if a["type"] in ("open_overlap", "open_request") and str(r.get("target_id") or "").isdigit():
            a["id"] = int(r["target_id"])
        elif a["type"] == "chat":
            a["prompt"] = f"About my reminder: {r['text']}"
        elif a["type"] == "plan":
            a["horizon"] = "quarter"
        out.append({"id": r["id"], "dedup_key": f"reminder:{r['id']}", "title": r["text"][:80], "body": f"Reminder set for {r['due_at'][:10]}.", "action": a})
    return out


# ---------- status and pipeline ----------

def set_status(ctx, conn, opportunity_id, status):
    if status not in STATUSES:
        return {"error": f"status must be one of {STATUSES}"}, []
    o = _mine(conn, ctx, opportunity_id)
    if not o:
        return {"error": f"#{opportunity_id} is not one of our overlaps"}, []
    conn.execute("UPDATE opportunity SET status = %s WHERE id = %s", (status, o["id"]))
    rest(ctx, "POST", "overlap_event", json={"opportunity_id": o["id"], "kind": "status", "detail": {"from": o["status"], "to": status}})
    out = {"opportunity_id": o["id"], "old_status": o["status"], "new_status": status, "partner": name(partner(o, ctx["company"]))}
    return out, [{"type": "status", "opportunity_id": o["id"], "status": status}, {"type": "pipeline", "pipeline": _pipeline(conn, ctx)}]


def _pipeline(conn, ctx, per_status=6):
    from app.crewly.app_tools import mine_sql
    rows = conn.execute(mine_sql(ctx["company"]) + " ORDER BY op.score DESC, op.distance_m").fetchall()
    cols = {s: [] for s in STATUSES}
    for o in rows:
        cols.setdefault(o["status"] or "not_contacted", []).append(o)
    return {"statuses": STATUSES, "counts": {s: len(cols.get(s, [])) for s in STATUSES},
            "columns": {s: [{"id": o["id"], "ours": o["a_name"] if o["a_org"] == ctx["company"] else o["b_name"], "partner": short(partner(o, ctx["company"])),
                             "savings": _usd(o["savings_high"])} for o in cols.get(s, [])[:per_status]] for s in STATUSES}}


def pipeline(ctx, conn):
    out = _pipeline(conn, ctx)
    return out, [{"type": "pipeline", "pipeline": out}]


# ---------- company profile ----------

def company_profile(ctx, conn, company):
    who = _find_company(company)
    if not who:
        return {"error": f"no utility called {company!r}", "utilities": sorted(c["name"] for c in companies().values())}, []
    from app.crewly.app_tools import mine_sql
    c = companies()[who]
    org = conn.execute("SELECT state, planner FROM org WHERE id = %s", (who,)).fetchone() or {}
    by_kv = conn.execute("SELECT voltage_kv, count(*) AS n FROM job WHERE org_id = %s AND horizon = 'long' GROUP BY 1 ORDER BY 2 DESC", (who,)).fetchall()
    by_type = conn.execute("SELECT job_type, count(*) AS n FROM job WHERE org_id = %s AND horizon = 'long' GROUP BY 1 ORDER BY 2 DESC", (who,)).fetchall()
    by_status = conn.execute("SELECT coalesce(status, 'unknown') AS s, count(*) AS n FROM job WHERE org_id = %s AND horizon = 'long' GROUP BY 1 ORDER BY 2 DESC", (who,)).fetchall()
    states = [r["state"] for r in conn.execute("SELECT DISTINCT state FROM job WHERE org_id = %s AND state IS NOT NULL ORDER BY 1", (who,)).fetchall()]
    total = sum(r["n"] for r in by_type)
    ours = [] if who == ctx["company"] else conn.execute(mine_sql(ctx["company"]) + " AND %s IN (ja.org_id, jb.org_id) ORDER BY op.savings_high DESC, op.score DESC", (who,)).fetchall()
    reqs = rest(ctx, "GET", "collab_request", params={"select": "id,opportunity_id,from_company,to_company,status,created_at,responded_at",
                                                      "or": f"(from_company.eq.{who},to_company.eq.{who})", "order": "created_at.desc", "limit": "100"})
    waits = [(datetime.fromisoformat(r["responded_at"]) - datetime.fromisoformat(r["created_at"])).total_seconds() / 3600 for r in reqs if r["responded_at"]]
    waits.sort()
    history = {"total": len(reqs), "approved": sum(r["status"] == "approved" for r in reqs), "declined": sum(r["status"] == "declined" for r in reqs),
               "pending": sum(r["status"] == "pending" for r in reqs), "median_response_hours": round(waits[len(waits) // 2], 1) if waits else None}
    news = []
    try:
        from app.news import feed
        news = [{"title": i["title"], "impact": i["impact"], "date": (i["published"] or "")[:10], "url": i["url"]} for i in feed.for_org(conn, who, 60)[:5]]
    except Exception:
        news = []
    notes = _notes(ctx, "company", who, 10)["notes"]
    out = {"company": {"id": who, "name": c["name"], "short": c["short"], "color": c["color"], "home_state": org.get("state"), "planner": org.get("planner"), "states": states},
           "projects": {"total": total, "by_kv": [{"kv": r["voltage_kv"], "n": r["n"]} for r in by_kv[:6]], "by_type": [{"type": r["job_type"], "n": r["n"]} for r in by_type],
                        "by_status": [{"status": r["s"], "n": r["n"]} for r in by_status[:6]]},
           "overlaps_with_us": {"count": len(ours), "savings_high_total": _usd(sum(float(o["savings_high"] or 0) for o in ours)),
                                "top": [{"id": o["id"], "ours": o["a_name"] if o["a_org"] == ctx["company"] else o["b_name"],
                                         "theirs": o["b_name"] if o["a_org"] == ctx["company"] else o["a_name"], "savings": _usd(o["savings_high"])} for o in ours[:3]]},
           "requests_with_us": history, "news": news, "notes": notes, "is_us": who == ctx["company"]}
    return out, [{"type": "profile", "profile": out}]


# ---------- weekly brief ----------

def brief_diff(current_ids, previous_ids):
    """What changed since the last snapshot: ids that appeared and ids that went away."""
    cur, prev = set(current_ids), set(previous_ids)
    return {"added": sorted(cur - prev), "dropped": sorted(prev - cur)}


def weekly_brief(ctx, conn):
    from app.crewly.app_tools import mine_sql
    me, since = ctx["company"], (_now() - timedelta(days=BRIEF_DAYS)).isoformat()
    overlaps = conn.execute(mine_sql(me) + " AND op.savings_high > 0 ORDER BY op.score DESC").fetchall()
    reqs = rest(ctx, "GET", "collab_request", params={"select": "id,opportunity_id,from_company,to_company,status,summary,created_at,responded_at",
                                                      "order": "created_at.desc", "limit": "200"})
    snaps = rest(ctx, "GET", "brief_snapshot", params={"select": "overlap_ids,request_ids,taken_at", "order": "taken_at.desc", "limit": "1"})
    prev = snaps[0] if snaps else None
    changed = brief_diff([o["id"] for o in overlaps], prev["overlap_ids"] if prev else [o["id"] for o in overlaps])
    new_reqs = [r for r in reqs if not prev or r["id"] not in prev["request_ids"]] if prev else []
    waiting_on_us = [r for r in reqs if r["to_company"] == me and r["status"] == "pending"]
    waiting_on_them = [r for r in reqs if r["from_company"] == me and r["status"] == "pending"]
    answered = [r for r in reqs if r["from_company"] == me and r["responded_at"] and r["responded_at"] >= since]
    plan = None
    try:
        from app.planner import store
        row = store.latest(conn, me, "quarter")
        if row:
            items = row["items"]
            plan = {"id": row["id"], "pairs": len(items), "proposed": sum(i.get("state", "proposed") == "proposed" for i in items),
                    "accepted": sum(i.get("state") == "accepted" for i in items), "savings": f"{_usd(row['totals']['savings']['low'])} to {_usd(row['totals']['savings']['high'])}"}
    except Exception:
        plan = None
    hazards = []
    try:
        from app.hazards.exposure import assess
        active = conn.execute("""SELECT id, name FROM job WHERE org_id = %s AND horizon = 'long' AND work_window @> now() ORDER BY cost_usd DESC NULLS LAST LIMIT 5""", (me,)).fetchall()
        for j in active:
            x = assess(conn, "site", j["id"], "now7")
            days = (x or {}).get("affected_days") or {}
            hit = [h["label"] for h in (x or {}).get("hazards", []) if h.get("live")]
            if hit:
                hazards.append({"project": j["name"], "hazards": hit[:3], "affected_days": days})
    except Exception:
        hazards = []
    news = []
    try:
        from app.news import feed
        news = [{"title": i["title"], "impact": i["impact"], "date": (i["published"] or "")[:10], "url": i["url"], "overlaps": i["opportunity_ids"][:3]}
                for i in feed.for_org(conn, me, BRIEF_DAYS) if i.get("affects_work")][:5]
    except Exception:
        news = []
    starred = conn.execute("SELECT id, title, kind FROM finding WHERE company_id = %s AND starred AND created_at >= %s ORDER BY created_at DESC LIMIT 5", (me, since)).fetchall() \
        if conn.execute("SELECT to_regclass('finding') IS NOT NULL AS ok").fetchone()["ok"] else []
    rest(ctx, "POST", "brief_snapshot", json={"overlap_ids": [o["id"] for o in overlaps], "request_ids": [r["id"] for r in reqs]})

    def req(r):
        other = r["to_company"] if r["from_company"] == me else r["from_company"]
        return {"id": r["id"], "overlap_id": r["opportunity_id"], "with": short(other), "projects": (r.get("summary") or {}).get("title"), "status": r["status"],
                "since": r["created_at"][:10]}

    out = {"week_of": _now().date().isoformat(), "since_last_brief": prev["taken_at"][:10] if prev else None,
           "overlaps": {"total": len(overlaps), "new": changed["added"][:10], "gone": changed["dropped"][:10]},
           "requests": {"waiting_on_us": [req(r) for r in waiting_on_us[:5]], "waiting_on_them": [req(r) for r in waiting_on_them[:5]],
                        "answered_this_week": [req(r) for r in answered[:5]], "new_since_last_brief": len(new_reqs)},
           "plan": plan, "hazards_this_week": hazards, "news": news,
           "findings_starred": [{"id": f["id"], "title": f["title"], "kind": f["kind"]} for f in starred],
           "wording": "assessment of the week; nothing here is a work order"}
    return out, [{"type": "brief", "brief": out}]


# ---------- overlap history ----------

def overlap_history(ctx, conn, opportunity_id):
    o = _mine(conn, ctx, opportunity_id)
    if not o:
        return {"error": f"#{opportunity_id} is not one of our overlaps"}, []
    me, oid = ctx["company"], o["id"]
    events = []
    for e in rest(ctx, "GET", "overlap_event", params={"select": "kind,detail,created_at", "opportunity_id": f"eq.{oid}", "order": "created_at.asc", "limit": "200"}):
        d = e["detail"] or {}
        text = {"status": f"status {d.get('from')} to {d.get('to')}", "request_sent": f"we sent a request to {short(d.get('to', ''))}",
                "request_received": f"{short(d.get('from', ''))} sent us a request", "approved": f"request approved by {short(d.get('by', ''))}",
                "declined": f"request declined by {short(d.get('by', ''))}", "note": f"note: {d.get('text', '')}"}.get(e["kind"], e["kind"])
        if d.get("feedback"):
            text += f' ("{d["feedback"]}")'
        events.append({"when": e["created_at"][:16].replace("T", " "), "kind": e["kind"], "text": text})
    for r in rest(ctx, "GET", "collab_request", params={"select": "id,from_company,to_company,status,note,feedback,created_at,responded_at", "opportunity_id": f"eq.{oid}", "order": "created_at.asc"}):
        events.append({"when": r["created_at"][:16].replace("T", " "), "kind": "request", "text": f"request {r['id']} {short(r['from_company'])} to {short(r['to_company'])}: {r['status']}"
                       + (f' with note "{r["note"][:80]}"' if r.get("note") else "")})
    if conn.execute("SELECT to_regclass('feasibility_assessment') IS NOT NULL AS ok").fetchone()["ok"]:
        for a in conn.execute("SELECT verdict, score, quick, created_at FROM feasibility_assessment WHERE opportunity_id = %s AND company_id = %s ORDER BY created_at", (oid, me)).fetchall():
            events.append({"when": _iso(a["created_at"])[:16].replace("T", " "), "kind": "assessment", "text": f"feasibility {a['verdict']} ({a['score']:.2f}){' quick' if a['quick'] else ''}"})
    findings = []
    if conn.execute("SELECT to_regclass('finding') IS NOT NULL AS ok").fetchone()["ok"]:
        findings = conn.execute("SELECT id, title, kind, created_at FROM finding WHERE company_id = %s AND (params::text LIKE %s OR params::text LIKE %s) ORDER BY created_at DESC LIMIT 10",
                                (me, f'%"opportunity_id": {oid}%', f'%"opportunity_id": "{oid}"%')).fetchall()
        for f in findings:
            events.append({"when": _iso(f["created_at"])[:16].replace("T", " "), "kind": "finding", "text": f"finding #{f['id']}: {f['title']}", "finding_id": f["id"]})
    events.sort(key=lambda e: e["when"])
    out = {"opportunity_id": oid, "ours": o["a_name"] if o["a_org"] == me else o["b_name"], "theirs": o["b_name"] if o["a_org"] == me else o["a_name"],
           "partner": name(partner(o, me)), "status": o["status"], "count": len(events), "events": events[-MAX_ROWS:]}
    return out, [{"type": "history", "history": out}]


# ---------- saved views ----------

def save_view(ctx, conn, name):  # noqa: A002  the tool argument is called name
    n = " ".join(str(name or "").split())[:80]
    if not n:
        return {"error": "a view needs a name"}, []
    return {"saving": n, "next_step": "the app stores what is on screen under this name"}, [{"type": "save_view", "name": n}]


def _views(ctx):
    rows = rest(ctx, "GET", "saved_view", params={"select": "id,name,state,created_at", "order": "created_at.desc", "limit": str(MAX_ROWS)})
    return [{"id": r["id"], "name": r["name"], "state": r["state"], "when": r["created_at"][:10]} for r in rows]


def open_view(ctx, conn, name):  # noqa: A002
    n = " ".join(str(name or "").split()).lower()
    views = _views(ctx)
    hit = next((v for v in views if v["name"].lower() == n), None) or next((v for v in views if n and n in v["name"].lower()), None)
    if not hit:
        return {"error": f"no saved view called {name!r}", "views": [v["name"] for v in views]}, []
    return {"opened": hit["name"], "state": hit["state"]}, [{"type": "view", "name": hit["name"], "state": hit["state"]}]


def list_views(ctx, conn):
    views = _views(ctx)
    return {"count": len(views), "views": [{"name": v["name"], "saved": v["when"]} for v in views]}, [{"type": "views", "views": views}]


# ---------- bulk ----------

def _matches(item, flt, company):
    ids = {str(i).lstrip("#") for i in (flt.get("ids") or [])}
    if ids and str(item.get("id", item.get("opportunity_id"))) not in ids:
        return False
    if flt.get("partner"):
        who = _find_company(flt["partner"])
        if who and item.get("partner") != who:
            return False
    if flt.get("verdict") and item.get("verdict") != flt["verdict"]:
        return False
    return True


def finding_matches(f, flt):
    """A finding row matches the bulk filter: ids, experiment kind, or an overlap id anywhere in its params."""
    ids = {int(str(i).lstrip("#")) for i in (flt.get("ids") or []) if str(i).lstrip("#").isdigit()}
    oid = str(flt.get("opportunity_id") or "").lstrip("#")
    if ids and f["id"] not in ids:
        return False
    if flt.get("kind") and f["kind"] != flt["kind"]:
        return False
    return not oid or bool(re.search(rf'"opportunity_id":\s*"?{re.escape(oid)}"?(?!\d)', json.dumps(f.get("params") or {})))


def plan_bulk(ctx, conn, action, filter=None, horizon="quarter"):
    if action not in ("accept", "skip"):
        return {"error": "action must be accept or skip"}, []
    from app.planner import build, store
    row = store.latest(conn, ctx["company"], horizon if horizon in build.HORIZONS else "quarter")
    if not row:
        return {"error": "no plan yet; call build_plan"}, []
    flt = filter or {}
    hits = [i for i in row["items"] if _matches(i, flt, ctx["company"])]
    state = "accepted" if action == "accept" else "skipped"
    for it in hits:
        row = store.update_item(conn, row, it["id"], {"state": state}) or row
    if hits:
        row["totals"] = build.totals_for(row["items"], row["totals"].get("considered", 0), row["totals"].get("skipped", {}),
                                         tuple(row["totals"]["period"]) if row["totals"].get("period") else None, row["totals"].get("note", ""))
        conn.execute("UPDATE coordination_plan SET totals = %s WHERE id = %s", (json.dumps(row["totals"], default=str), row["id"]))
    return ({"plan_id": row["id"], "action": action, "changed": len(hits), "items": [i["id"] for i in hits], "filter": flt},
            [{"type": "plan", "horizon": row["horizon"], "id": row["id"]}])


def findings_bulk(ctx, conn, action, filter=None):
    if action not in ("star", "unstar", "delete"):
        return {"error": "action must be star, unstar or delete"}, []
    from app.scenario import experiments
    flt = filter or {}
    conn.execute(experiments.TABLE_SQL)
    rows = conn.execute("SELECT id, kind, params FROM finding WHERE company_id = %s ORDER BY id DESC LIMIT 200", (ctx["company"],)).fetchall()
    hits = [f for f in rows if finding_matches(f, flt)]
    for f in hits:
        if action == "delete":
            experiments.delete(conn, f["id"], ctx["company"])
        else:
            experiments.star(conn, f["id"], ctx["company"], action == "star")
    return {"action": action, "changed": len(hits), "ids": [f["id"] for f in hits], "filter": flt}, [{"type": "notebook"}]


# ---------- registry ----------

def _bind(ctx, fn):
    return lambda conn, **kw: fn(ctx, conn, **kw)


def workspace_tools(ctx):
    tk = {"type": "string", "enum": list(TARGETS)}
    return {
        "add_note": (_bind(ctx, add_note), "Save a note for our company on an overlap (#id), a project (id), a utility (name) or a plan item. Shared with "
                     "everyone at our company, shown on the detail panel.", {"target_kind": tk, "target_id": {"type": "string"}, "text": {"type": "string"}},
                     ["target_kind", "target_id", "text"]),
        "list_notes": (_bind(ctx, list_notes), "Our notes, all of them or those on one target.", {"target_kind": tk, "target_id": {"type": "string"}}, []),
        "set_reminder": (_bind(ctx, set_reminder), "Remind us later: 'follow up with Duke in 7 days'. Lands in the bell when due. Give due_at (ISO date or "
                         "datetime) or in_days; optionally what it is about.", {
            "text": {"type": "string"}, "due_at": {"type": "string", "description": "YYYY-MM-DD or YYYY-MM-DDTHH:MM"}, "in_days": {"type": "integer"},
            "target_kind": {"type": "string", "enum": list(REMINDER_TARGETS)}, "target_id": {"type": "string", "description": "overlap id, request id, or utility name"}}, ["text"]),
        "list_reminders": (_bind(ctx, list_reminders), "Our open reminders, soonest first.", {"include_done": {"type": "boolean"}}, []),
        "done_reminder": (_bind(ctx, done_reminder), "Mark a reminder done.", {"reminder_id": {"type": "integer"}}, ["reminder_id"]),
        "set_status": (_bind(ctx, set_status), "Move one of our overlaps along the coordination pipeline: " + ", ".join(STATUSES) + ". Logged in its history.", {
            "opportunity_id": {"type": "integer"}, "status": {"type": "string", "enum": STATUSES}}, ["opportunity_id", "status"]),
        "pipeline": (_bind(ctx, pipeline), "Our overlaps by pipeline status, as a board: counts per status and the top overlaps in each.", {}, []),
        "company_profile": (_bind(ctx, company_profile), "Everything we know about a utility: states, projects by kV, type and status, overlaps with us, "
                            "request history with us, recent news and our notes about them.", {"company": {"type": "string", "description": "utility name or id"}}, ["company"]),
        "weekly_brief": (_bind(ctx, weekly_brief), "One card for the week: overlaps that appeared or went away since the last brief, requests waiting on "
                         "us and on them, plan items pending, hazards touching our active sites this week, news about us, findings starred this week. Assessment only.", {}, []),
        "overlap_history": (_bind(ctx, overlap_history), "Everything that happened on one of our overlaps: status changes, requests and answers with "
                            "feedback, feasibility assessments, findings, notes, in order.", {"opportunity_id": {"type": "integer"}}, ["opportunity_id"]),
        "save_view": (_bind(ctx, save_view), "Bookmark what is on screen (tab, neighbor filter, shown overlaps, map area) under a name.", {"name": {"type": "string"}}, ["name"]),
        "open_view": (_bind(ctx, open_view), "Bring back a saved view by name.", {"name": {"type": "string"}}, ["name"]),
        "list_views": (_bind(ctx, list_views), "Our saved views.", {}, []),
        "plan_bulk": (_bind(ctx, plan_bulk), "Accept or skip many plan items at once, filtered by partner utility, verdict or ids.", {
            "action": {"type": "string", "enum": ["accept", "skip"]}, "horizon": {"type": "string", "enum": ["quarter", "year", "window"]},
            "filter": {"type": "object", "properties": {"partner": {"type": "string"}, "verdict": {"type": "string"}, "ids": {"type": "array", "items": {"type": "string"}}}}}, ["action"]),
        "findings_bulk": (_bind(ctx, findings_bulk), "Star, unstar or delete many findings at once, filtered by overlap id, experiment kind or ids.", {
            "action": {"type": "string", "enum": ["star", "unstar", "delete"]},
            "filter": {"type": "object", "properties": {"opportunity_id": {"type": "string"}, "kind": {"type": "string"}, "ids": {"type": "array", "items": {"type": "integer"}}}}}, ["action"]),
    }


PROMPT = """
- Workspace: "note that ..." on an overlap, project, utility or plan item calls add_note; "remind me ..." calls set_reminder (in_days or due_at; it lands
  in the bell when due, never earlier); "mark #N as sent/agreed" calls set_status; "where are we with everyone" or "pipeline" calls pipeline;
  "tell me about <utility>" calls company_profile; "brief me" / "what happened this week" calls weekly_brief; "history of #N" calls
  overlap_history; "save this view as X" / "open my X view" call save_view / open_view; "accept every Duke pair" / "star all findings about #18"
  call plan_bulk / findings_bulk. All of these are records and assessments for our company; nothing reaches another utility, and sending or
  answering a request still goes through propose_request or propose_answer with a Confirm. Summarize each card in one or two sentences."""
