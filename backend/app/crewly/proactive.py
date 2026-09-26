"""Proactive Crewly: rules and templates (no model) that turn events into suggestions in a company's bell."""
import hashlib
import os
from datetime import datetime, timedelta, timezone

import httpx

from app.crewly.app_tools import NAMES, mine_sql
from app.weather_api import weather

FOLLOW_UP_AFTER = timedelta(days=2)
MAX_DRIVE_MIN = 45
COLD_TOP = 3
OTHER = {"desc": "gpc", "gpc": "desc"}


def _rest(path, method="GET", **kw):
    """Supabase REST with the backend's secret key: suggestions are written by crewly, not by a person."""
    key = os.environ["SUPABASE_SECRET_KEY"]
    r = httpx.request(method, f"{os.environ['SUPABASE_URL'].rstrip('/')}/rest/v1/{path}", headers={"apikey": key, **kw.pop("headers", {})},
                      timeout=15, **kw)
    r.raise_for_status()
    return r.json() if r.content else None


def _usd(n):
    n = float(n)
    return f"${n / 1e6:.1f}M" if n >= 1e6 else f"${round(n / 1e3)}k" if n >= 1e3 else f"${round(n)}"


def _save(o):
    return f"save {_usd(o['savings_low'])} to {_usd(o['savings_high'])}" if o["savings_high"] > 0 else "no shared savings yet"


def _ours(company, o):
    a = o["a_org"] == company
    return (o["a_name"], o["b_name"]) if a else (o["b_name"], o["a_name"])


def request_takes(conn, company, requests):
    """A second opinion on every request waiting for us."""
    out, other = [], NAMES[OTHER[company]]
    for r in requests:
        if r["to_company"] != company or r["status"] != "pending":
            continue
        o = conn.execute(mine_sql(company) + " AND op.id = %s", (r["opportunity_id"],)).fetchone()
        if not o:
            continue
        drive = o["drive_min"]
        facts = [f"Overlap #{o['id']}: {_save(o)}"]
        if drive is not None:
            facts.append(f"{round(drive)} min drive")
        facts.append(f"build windows overlap {round(o['time_overlap'] * 100)}%" if o["time_overlap"] > 0 else "built in different years")
        if o["savings_high"] > 0 and (drive is None or drive <= MAX_DRIVE_MIN):
            lean = "Crewly leans approve: the sites are close and the work runs at the same time."
        elif o["savings_high"] <= 0:
            lean = "Worth a look: savings only show up if one side shifts its schedule."
        else:
            lean = f"Worth a look: the drive is over {MAX_DRIVE_MIN} min, so crews and yards are hard to share."
        out.append({"dedup_key": f"req-take:{r['id']}", "title": f"Crewly's take on {other}'s request for #{o['id']}"[:80],
                    "body": f"{', '.join(facts)}. {lean}", "action": {"type": "open_request", "id": r["id"]}})
    return out


def weather_risks(conn, company, days=3, scenario="none"):
    """One suggestion per hazard: our projects under construction inside it over the next few days."""
    wx, out = weather(scenario=scenario, org=company, conn=conn), []
    opps = conn.execute(mine_sql(company) + " AND op.savings_high > 0 ORDER BY op.score DESC").fetchall()
    hazards = {}  # kind -> {"days": [label...], "first": date, "jobs": {id: name}}
    for day in wx["days"][:days]:
        for a in day["areas"]["features"]:
            p = a["properties"]
            active = {j["id"]: j["name"] for j in p["projects"] if j["building"]}
            if not active:
                continue
            h = hazards.setdefault(p["kind"], {"days": [], "first": day["date"], "jobs": {}})
            label = "today" if day["label"] == "Today" else day["label"]
            if label not in h["days"]:
                h["days"].append(label)
            h["jobs"].update(active)
    for kind, h in hazards.items():
        jobs, n = h["jobs"], len(h["jobs"])
        when = h["days"][0] if len(h["days"]) == 1 else f"{h['days'][0]} through {h['days'][-1]}"
        best = next((o for o in opps if o["job_a"] in jobs or o["job_b"] in jobs), None)
        first = next(iter(jobs.values()))
        body = f"{first}{f' and {n - 1} more' if n > 1 else ''} {'is' if n == 1 else 'are'} under construction inside the {kind.lower()} outlook."
        if best:
            body += f" Ask {NAMES[OTHER[company]]} about sharing a staging yard near #{best['id']}?"
        out.append({"dedup_key": f"wx:{kind}:{h['first']}", "title": f"{kind} risk {when} at {n} active site{'s' if n != 1 else ''}"[:80],
                    "body": body, "action": {"type": "open_overlap", "id": best["id"]} if best else {"type": "weather"}})
    return out


def cold_overlaps(conn, company, requests):
    """Strong overlaps nobody has reached out about yet."""
    asked = {r["opportunity_id"] for r in requests}
    rows = [o for o in conn.execute(mine_sql(company) + " AND op.savings_high > 0 ORDER BY op.score DESC, op.distance_m").fetchall()
            if o["id"] not in asked]
    if not rows:
        return []
    top = rows[:COLD_TOP]
    ours, theirs = _ours(company, top[0])
    key = hashlib.sha1(",".join(str(o["id"]) for o in sorted(top, key=lambda o: o["id"])).encode()).hexdigest()[:10]
    n = len(rows)
    return [{"dedup_key": f"cold-overlaps:{key}", "title": f"{n} strong overlap{'s' if n != 1 else ''} nobody has contacted yet",
             "body": f"Top one is #{top[0]['id']}, {ours} with {theirs} ({_save(top[0])}).",
             "action": {"type": "chat", "prompt": f"Line up collaboration on our top {len(top)} overlaps"}}]


def follow_ups(company, requests, tasks, now=None):
    """Goal steps whose request has waited too long for an answer."""
    now, out = now or datetime.now(timezone.utc), []
    by_id = {r["id"]: r for r in requests}
    other = NAMES[OTHER[company]]
    for t in tasks:
        for s in t.get("steps") or []:
            r = by_id.get(s.get("request_id"))
            if not r or r["status"] != "pending" or r["from_company"] != company:
                continue
            sent = datetime.fromisoformat(r["created_at"])
            if now - sent < FOLLOW_UP_AFTER:
                continue
            out.append({"dedup_key": f"followup:{r['id']}", "title": f"Follow up with {other} on #{r['opportunity_id']}?"[:80],
                        "body": f"Our request from {sent:%b %d} for \"{t['goal'][:60]}\" is still waiting for an answer.",
                        "action": {"type": "open_request", "id": r["id"]}})
    return out


def suggestions(conn, company, requests, tasks, now=None):
    return (request_takes(conn, company, requests) + follow_ups(company, requests, tasks, now)
            + weather_risks(conn, company) + cold_overlaps(conn, company, requests))


def scan(conn, company):
    """Work out suggestions for one company and add the new ones to its bell."""
    requests = _rest("collab_request", params={"select": "*", "or": f"(from_company.eq.{company},to_company.eq.{company})"})
    tasks = _rest("agent_task", params={"select": "id,goal,steps", "company_id": f"eq.{company}", "status": "eq.active"})
    found = suggestions(conn, company, requests, tasks)
    seen = {n["dedup_key"] for n in _rest("notification", params={"select": "dedup_key", "company_id": f"eq.{company}",
                                                                   "dedup_key": "not.is.null"})}
    new = [{"company_id": company, "kind": "suggestion", **s} for s in found if s["dedup_key"] not in seen]
    created = []
    for row in new:  # one at a time so a race with another scan only loses the duplicate
        try:
            created += _rest("notification", "POST", json=row, headers={"Prefer": "return=representation"})
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 409:
                raise
    keep = ",".join(f'"{s["dedup_key"]}"' for s in found)
    stale = {"company_id": f"eq.{company}", "kind": "eq.suggestion", "dismissed_at": "is.null", **({"dedup_key": f"not.in.({keep})"} if keep else {})}
    _rest("notification", "PATCH", params=stale, json={"dismissed_at": datetime.now(timezone.utc).isoformat()})  # answered, passed or recounted: retire it
    return {"company": company, "found": len(found), "created": len(created), "suggestions": created}
