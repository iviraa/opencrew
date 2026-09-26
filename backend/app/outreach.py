import os
from datetime import datetime, timezone

import httpx

from app.config import MILE_M
from app.llm import generate, provider, unsourced
from app.queries import OPP_SQL, shareable

RESEND = "https://api.resend.com/emails"


def seed_contacts(conn):
    inbox = os.environ.get("DEMO_INBOX_UTILITY") or None
    for org in ("desc", "gpc"):
        conn.execute("INSERT INTO contact (org_id, role, email, is_demo) VALUES (%s, 'Transmission planning (demo inbox)', %s, TRUE)", (org, inbox))


def contacts(conn, opp_id):
    return conn.execute("""SELECT c.*, o.name AS org_name FROM contact c JOIN org o ON o.id = c.org_id
                           WHERE c.org_id IN (SELECT ja.org_id FROM opportunity op JOIN job ja ON ja.id = op.job_a WHERE op.id = %(id)s
                                              UNION SELECT jb.org_id FROM opportunity op JOIN job jb ON jb.id = op.job_b WHERE op.id = %(id)s)
                           ORDER BY c.org_id""", {"id": opp_id}).fetchall()


def opener(o):
    fallback = "Our planning teams have nearby transmission work, and we think there may be room to coordinate."
    if not provider():
        return fallback
    prompt = (f"Write one friendly, professional sentence opening an email from one utility planner to another about coordinating nearby "
              f"projects '{o['a_name']}' and '{o['b_name']}'. No numbers, dates or dollar amounts.")
    try:
        text = generate(prompt)
    except Exception:
        return fallback
    return fallback if unsourced(text, "") else text


def draft(conn, opp_id, contact_id, kind="utility_intro"):
    o = conn.execute(OPP_SQL + " WHERE op.id = %s", (opp_id,)).fetchone()
    c = conn.execute("SELECT c.*, o.name AS org_name FROM contact c JOIN org o ON o.id = c.org_id WHERE c.id = %s", (contact_id,)).fetchone()
    if not o or not c:
        return None
    subject = f"Coordinating {o['a_name']} and {o['b_name']}"
    body = "\n".join([
        f"Hello {c['org_name']} transmission planning team,", "", opener(o), "",
        f"- {o['a_name']} ({o['a_org'].upper()}) and {o['b_name']} ({o['b_org'].upper()})",
        f"- Closest distance {o['distance_m'] / MILE_M:.1f} mi; build windows overlap {round(o['time_overlap'] * 100)}%",
        f"- Could share: {', '.join(shareable(o['tier']))}",
        f"- Rough savings if scheduled together: ${int(o['savings_low']):,} to ${int(o['savings_high']):,}", "",
        "Would you be open to a 30 minute call to compare schedules and scope?", "",
        "Thanks,", "Sent via OpenCrew (numbers computed from public filings)"])
    row = conn.execute("INSERT INTO outreach (opportunity_id, contact_id, kind, subject, body) VALUES (%s, %s, %s, %s, %s) RETURNING *",
                       (opp_id, contact_id, kind, subject, body)).fetchone()
    conn.execute("UPDATE opportunity SET status = 'drafted' WHERE id = %s AND status = 'not_contacted'", (opp_id,))
    return row


def edit(conn, outreach_id, subject, body):
    return conn.execute("UPDATE outreach SET subject = %s, body = %s WHERE id = %s AND state = 'draft' RETURNING *",
                        (subject, body, outreach_id)).fetchone()


def approve(conn, outreach_id, approved_by):
    return conn.execute("UPDATE outreach SET state = 'approved', approved_by = %s WHERE id = %s AND state = 'draft' RETURNING *",
                        (approved_by, outreach_id)).fetchone()


def send(conn, outreach_id):
    r = conn.execute("""SELECT r.*, c.email, c.is_demo FROM outreach r JOIN contact c ON c.id = r.contact_id WHERE r.id = %s""", (outreach_id,)).fetchone()
    if not r:
        return None, "not found"
    if r["state"] != "approved":
        return None, "outreach must be approved by a person before sending"
    if not r["is_demo"] or not r["email"]:
        return None, "only demo inboxes can receive email in this build"
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        return None, "email is not configured (RESEND_API_KEY)"
    res = httpx.post(RESEND, headers={"Authorization": f"Bearer {key}"}, timeout=30, json={
        "from": os.environ.get("RESEND_FROM", "OpenCrew <onboarding@resend.dev>"), "to": [r["email"]], "subject": r["subject"], "text": r["body"]})
    if res.status_code >= 300:
        return None, f"email provider error: {res.text[:200]}"
    row = conn.execute("UPDATE outreach SET state = 'sent', sent_at = %s WHERE id = %s RETURNING *", (datetime.now(timezone.utc), outreach_id)).fetchone()
    conn.execute("UPDATE opportunity SET status = 'sent' WHERE id = %s AND status IN ('not_contacted', 'drafted')", (r["opportunity_id"],))
    return row, None


def mark_replied(conn, outreach_id, summary):
    row = conn.execute("UPDATE outreach SET state = 'replied', reply_summary = %s WHERE id = %s AND state = 'sent' RETURNING *",
                       (summary, outreach_id)).fetchone()
    if row:
        conn.execute("UPDATE opportunity SET status = 'replied' WHERE id = %s AND status IN ('drafted', 'sent')", (row["opportunity_id"],))
    return row


def listing(conn, opp_id):
    return conn.execute("""SELECT r.*, c.email, c.role, o.name AS org_name FROM outreach r JOIN contact c ON c.id = r.contact_id
                           JOIN org o ON o.id = c.org_id WHERE r.opportunity_id = %s ORDER BY r.id""", (opp_id,)).fetchall()
