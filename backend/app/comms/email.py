"""Email drafts crewly writes for a planner to send: numbers come from tools, the prose carries none, nothing leaves without a person."""
import base64
import os
import re
from datetime import datetime, timezone

import httpx

from app.companies import name, short
from app.config import MILE_M
from app.engine.cost import savings_for
from app.llm import generate, provider, unsourced
from app.queries import OPP_SQL, shareable

RESEND = "https://api.resend.com/emails"
MAX_BODY = 20000


def _rest(ctx, method="GET", params=None, json=None, path="draft"):
    """The user's own login talks to Supabase, so row security decides what they see."""
    r = httpx.request(method, f"{os.environ['SUPABASE_URL'].rstrip('/')}/rest/v1/{path}", params=params, json=json, timeout=15,
                      headers={"apikey": os.environ["SUPABASE_PUBLISHABLE_KEY"], "Authorization": f"Bearer {ctx['token']}",
                               "Prefer": "return=representation"})
    r.raise_for_status()
    return r.json() if r.content else []


def usd(n):
    return f"${int(float(n or 0)):,}"


# ---------- who and what ----------

def recipient(conn, to, company, hint=None):
    """An address as given, or a partner utility's contact on file (demo inboxes only, in this build); `hint` is the overlap's partner,
    used when the name is loose ("them", "Dominion") or missing."""
    from app.crewly.app_tools import find_company  # here, not at import: app_tools loads this module
    to = (to or "").strip()
    if "@" in to:
        return {"company_id": None, "name": to, "email": to, "is_demo": False}
    who = find_company(to)
    if hint and (not who or who == company) and (not to or to.lower() in ("them", "partner", "the partner", "the other utility")
                                                 or to.lower() in name(hint).lower() or to.lower() in short(hint).lower()):
        who = hint
    if not who or who == company:
        return None
    c = conn.execute("SELECT email, role, is_demo FROM contact WHERE org_id = %s ORDER BY is_demo DESC, id LIMIT 1", (who,)).fetchone() or {}
    return {"company_id": who, "name": name(who), "email": c.get("email"), "role": c.get("role"), "is_demo": bool(c.get("is_demo"))}


def overlap_facts(conn, company, opp_id):
    o = conn.execute(OPP_SQL + " WHERE op.id = %s AND %s IN (ja.org_id, jb.org_id)", (int(opp_id), company)).fetchone()
    if not o:
        return None
    mine_a = o["a_org"] == company
    s = savings_for(conn, o)
    return {"id": o["id"], "ours": o["a_name"] if mine_a else o["b_name"], "theirs": o["b_name"] if mine_a else o["a_name"],
            "partner": o["b_org"] if mine_a else o["a_org"], "miles": round(o["distance_m"] / MILE_M, 1), "overlap_pct": round(o["time_overlap"] * 100),
            "drive_min": None if o["drive_min"] is None else round(o["drive_min"]), "share": shareable(o["tier"], o["a_phase"], o["b_phase"], o["drive_min"])[:4],
            "savings_low": s["low"], "savings_high": s["high"], "tier": o["tier"]}


def plan_facts(conn, company, horizon="quarter"):
    from app.planner import build, store
    row = store.latest(conn, company, horizon if horizon in build.HORIZONS else "quarter")
    if not row:
        return None
    items = [i for i in row["items"] if i.get("state") != "skipped"][:6]
    return {"horizon": row["horizon"], "version": row["version"], "totals": row["totals"], "items": items}


def request_facts(ctx, request_id):
    rows = _rest(ctx, params={"select": "id,opportunity_id,from_company,to_company,summary,note,status,feedback,created_at", "id": f"eq.{int(request_id)}"},
                 path="collab_request")
    return rows[0] if rows else None


def opener(topic):
    """One friendly sentence from the model, with no numbers in it; a fixed line when the model is off or breaks the rule."""
    fallback = "Our planning teams have nearby transmission work, and we think there may be room to coordinate."
    if not provider():
        return fallback
    try:
        text = generate(f"Write one friendly, professional sentence opening an email from one utility planner to another about {topic}. "
                        "No numbers, dates, dollar amounts or percentages.").strip()
    except Exception:
        return fallback
    return fallback if unsourced(text, "") or len(text) > 300 or "[" in text else text  # numbers or placeholders like [Name]: use the fixed line


# ---------- the draft ----------

def compose(conn, ctx, to, about, tone="short", attach=None):
    company = ctx["company"]
    about = str(about or "").strip()
    m = re.fullmatch(r"#?(\d+)", about)
    if not m and not re.fullmatch(r"(request\s*#?\d+|plan(\s+(quarter|year|window))?)?", about.lower()):
        raise ValueError(f"I can write about an overlap (#18), a request (request 12) or the plan, not {about!r}")
    f = overlap_facts(conn, company, int(m.group(1))) if m else None
    if m and not f:
        raise ValueError(f"#{m.group(1)} is not one of our overlaps")
    who = recipient(conn, to, company, f["partner"] if f else None)
    if not who and not m and not about.lower().startswith("request"):  # a plan has several partners: ask for one by name
        p = plan_facts(conn, company, about.replace("plan", "").strip() or "quarter")
        partners = sorted({i["partner_name"] for i in (p or {}).get("items", [])})
        raise ValueError("say which utility the email is for" + (f": {', '.join(partners)}" if partners else ""))
    if not who:
        raise ValueError(f"I do not know who {to!r} is: give a utility name or an email address")
    me = name(company)
    attachments = []
    if m:
        if who["company_id"] and who["company_id"] != f["partner"]:
            raise ValueError(f"overlap #{f['id']} is with {name(f['partner'])}, not {who['name']}")
        subject = f"Coordinating {f['ours']} and {f['theirs']}"
        facts = [f"{f['ours']} ({me}) and {f['theirs']} ({name(f['partner'])}): {f['miles']} mi apart, build windows overlap {f['overlap_pct']}%"
                 + (f", {f['drive_min']} min by road" if f["drive_min"] is not None else ""),
                 f"Could share: {', '.join(f['share'])}" if f["share"] else "Could coordinate outage timing and access",
                 f"Rough savings if scheduled together: {usd(f['savings_low'])} to {usd(f['savings_high'])}"]
        topic = f"coordinating the nearby projects {f['ours']} and {f['theirs']}"
        ref = {"overlap_id": f["id"]}
        if attach == "brief":
            from app.crewly import brief
            b = brief.build(conn, f["id"])
            if b:
                attachments.append({"name": f"brief-overlap-{f['id']}.md", "content_type": "text/markdown", "content": b["markdown"]})
    elif about.lower().startswith("request"):
        r = request_facts(ctx, re.sub(r"\D", "", about) or 0)
        if not r:
            raise ValueError("I could not find that request")
        title = (r.get("summary") or {}).get("title") or f"overlap #{r['opportunity_id']}"
        subject = f"Following up on our request: {title}"
        facts = [f"Our request about {title} (overlap #{r['opportunity_id']}) is {r['status']}",
                 *( [f"Our note: {r['note']}"] if r.get("note") else []), *( [f"Your feedback: {r['feedback']}"] if r.get("feedback") else [])]
        topic = f"following up on a collaboration request about {title}"
        ref = {"request_id": r["id"], "overlap_id": r["opportunity_id"]}
    else:
        horizon = about.replace("plan", "").strip() or "quarter"
        p = plan_facts(conn, company, horizon)
        if not p:
            raise ValueError("there is no plan yet; ask me to build one first")
        mine = [i for i in p["items"] if not who["company_id"] or i.get("partner") == who["company_id"]]
        if not mine:
            raise ValueError(f"the plan has no pairs with {who['name']}")
        t = p["totals"]
        subject = f"Coordinating {len(mine)} project{'s' if len(mine) != 1 else ''} over the next {p['horizon']}"
        facts = [f"#{i['id']} {i['ours']} with {i['theirs']}: {i['target_start'][:7]} to {i['target_end'][:7]}, savings {usd(i['savings']['low'])} to {usd(i['savings']['high'])}" for i in mine]
        facts.append(f"Across the plan: {usd(t['savings']['low'])} to {usd(t['savings']['high'])} expected savings")
        topic = "lining up several nearby transmission projects over the coming months"
        ref = {"plan": p["horizon"], "version": p["version"]}
    if attach and str(attach).startswith("report:"):
        from app.crewly import reports
        rid = str(attach).split(":", 1)[1].strip().lstrip("#")
        if not rid.isdigit():
            raise ValueError(f"attach wants a report id like report:12, got {attach!r}")
        row = reports.get(conn, int(rid), company)
        if row:
            attachments.append({"name": f"report-{row['id']}.html", "content_type": "text/html", "content": row["html"]})
    greeting = f"Hello {who['name']} transmission planning team," if who["company_id"] else f"Hello {who['name']},"
    if tone == "formal":
        body = "\n".join([greeting, "", opener(topic), "", "For reference:", *[f"- {x}" for x in facts], "",
                          "We would welcome a short call to compare schedules and scope, and to agree what could be shared first.",
                          "", "Kind regards,", f"{me} transmission planning", "Sent via crewly (numbers computed from public filings)"])
    else:
        body = "\n".join([greeting, "", opener(topic), "", *[f"- {x}" for x in facts], "",
                          "Would a 30 minute call work to compare schedules?", "", "Thanks,", f"{me} transmission planning",
                          "Sent via crewly (numbers computed from public filings)"])
    return {"kind": "email", "recipient": who, "subject": subject[:300], "body": body[:MAX_BODY], "attachments": attachments, "about": ref}


def create(ctx, draft):
    row = _rest(ctx, "POST", json={k: draft[k] for k in ("kind", "recipient", "subject", "body", "attachments", "about")})[0]
    return card(row)


def card(row):
    """What the chat card needs: attachment contents stay on the server."""
    return {k: row[k] for k in ("id", "kind", "recipient", "subject", "body", "about", "status", "sent_at", "created_at") if k in row} | {
        "attachments": [{"name": a["name"], "content_type": a["content_type"], "size": len(a.get("content") or "")} for a in row.get("attachments") or []]}


def update(ctx, draft_id, fields):
    allowed = {k: v for k, v in fields.items() if k in ("subject", "body", "recipient", "status") and v is not None}
    if "status" in allowed and allowed["status"] not in ("draft", "copied"):
        allowed.pop("status")  # sent is only set by send()
    if "body" in allowed:
        allowed["body"] = str(allowed["body"])[:MAX_BODY]
    allowed["updated_at"] = datetime.now(timezone.utc).isoformat()
    rows = _rest(ctx, "PATCH", params={"id": f"eq.{int(draft_id)}"}, json=allowed)
    return card(rows[0]) if rows else None


# ---------- sending ----------

def allowed_domains():
    return {d.strip().lower().lstrip("@") for d in os.environ.get("COMMS_ALLOWED_DOMAINS", "").split(",") if d.strip()}


def may_send(conn, who):
    """Only a demo inbox on file or an address on the allowlist receives mail from this build."""
    email = (who or {}).get("email") or ""
    if "@" not in email:
        return False, "no email address on the draft: add one, or copy the text and send it yourself"
    domain = email.rsplit("@", 1)[1].lower()
    if domain in allowed_domains():
        return True, None
    demo = conn.execute("SELECT 1 FROM contact WHERE is_demo AND lower(email) = lower(%s)", (email,)).fetchone()
    if demo:
        return True, None
    return False, f"{email} is not a demo inbox or an allowed domain, so this build will not send it: copy the text and send it yourself"


def send(conn, ctx, draft_id, post=httpx.post):
    rows = _rest(ctx, params={"select": "*", "id": f"eq.{int(draft_id)}"})
    if not rows:
        return {"sent": False, "note": "draft not found"}
    d = rows[0]
    if d["status"] == "sent":
        return {"sent": True, "note": "already sent", "draft": card(d)}
    ok, why = may_send(conn, d["recipient"])
    if not ok:
        return {"sent": False, "note": why, "draft": card(d)}
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        return {"sent": False, "note": "email is not configured on this server (RESEND_API_KEY): copy the text and send it yourself", "draft": card(d)}
    payload = {"from": os.environ.get("RESEND_FROM", "crewly <onboarding@resend.dev>"), "to": [d["recipient"]["email"]], "subject": d["subject"], "text": d["body"],
               "attachments": [{"filename": a["name"], "content": base64.b64encode((a.get("content") or "").encode()).decode()} for a in d.get("attachments") or []]}
    if not payload["attachments"]:
        payload.pop("attachments")
    res = post(RESEND, headers={"Authorization": f"Bearer {key}"}, timeout=30, json=payload)
    if res.status_code >= 300:
        return {"sent": False, "note": f"email provider error: {res.text[:160]}", "draft": card(d)}
    rows = _rest(ctx, "PATCH", params={"id": f"eq.{int(draft_id)}"}, json={"status": "sent", "sent_at": datetime.now(timezone.utc).isoformat()})
    return {"sent": True, "note": f"sent to {d['recipient']['email']}", "draft": card(rows[0]) if rows else card(d)}
