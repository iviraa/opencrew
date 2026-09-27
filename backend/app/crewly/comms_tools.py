"""Crewly abilities that write for people: an email draft to edit and send, a call agenda, a cost-sharing memo."""
from app.comms import email
from app.crewly import reports


def _bind(ctx, fn):
    return lambda conn, **kw: fn(ctx, conn, **kw)


def draft_email(ctx, conn, to, about, tone="short", attach=None):
    d = email.create(ctx, email.compose(conn, ctx, to, about, tone or "short", attach))
    summary = {"draft_id": d["id"], "to": d["recipient"].get("name"), "email": d["recipient"].get("email"), "subject": d["subject"],
               "attachments": [a["name"] for a in d["attachments"]],
               "next_step": "the draft card in the chat can be edited, copied, or sent after the user taps Confirm; nothing has been sent"}
    return summary, [{"type": "draft", "draft": d}]


def _report(ctx, conn, kind, about, options=None):
    ref = str(about or "").strip()
    r = reports.build(conn, ctx["company"], kind, ref if ref.lstrip("#").isdigit() else (ref.replace("plan", "").strip() or "quarter"), None, options)
    card = {k: r[k] for k in ("id", "kind", "ref_id", "title", "sections", "all_sections", "created_at")}
    return {**card, "next_step": "the report card in the chat opens it; the page has a Print / Save as PDF button"}, [{"type": "report", "report": card}]


def draft_agenda(ctx, conn, about, when=None):
    return _report(ctx, conn, "agenda", about, {"when": when})


def draft_memo(ctx, conn, about, audience="internal"):
    return _report(ctx, conn, "memo", about, {"audience": audience if audience in ("regulator", "internal") else "internal"})


def comms_tools(ctx):
    return {
        "draft_email": (_bind(ctx, draft_email), "Write an email draft to a partner utility (or an address) about one of our overlaps (#id), the latest "
                        "plan, or a request (request:<id>). The user edits it in a card and copies or sends it; nothing is sent by this tool.", {
            "to": {"type": "string", "description": "a utility name like Duke Energy, or an email address"},
            "about": {"type": "string", "description": "overlap #18, 'plan' (optionally 'plan year'), or 'request 12'"},
            "tone": {"type": "string", "enum": ["short", "formal"]},
            "attach": {"type": "string", "description": "'brief' for the coordination brief, or 'report:<id>' for a report already written"}}, ["to", "about"]),
        "draft_agenda": (_bind(ctx, draft_agenda), "A coordination-call agenda for an overlap (#id) or the latest plan: context numbers, decisions to make, "
                         "data each side brings, open questions. Opens as a printable report.", {
            "about": {"type": "string", "description": "overlap #18 or 'plan'"}, "when": {"type": "string", "description": "the call date or slot, if known"}}, ["about"]),
        "draft_memo": (_bind(ctx, draft_memo), "A cost-sharing memo for an overlap (#id) or the latest plan: purpose, projects, savings with sources, weather "
                       "and timing, the split to agree, risks, next steps. audience regulator or internal. Opens as a printable report.", {
            "about": {"type": "string", "description": "overlap #18 or 'plan'"}, "audience": {"type": "string", "enum": ["regulator", "internal"]}}, ["about"]),
    }


PROMPT = """
- For "draft an email", "write to Duke", "email them about #18" or "follow up on my request" call draft_email; say the draft is in the chat to
  edit, copy or send, and never say it was sent. For "agenda for the call" call draft_agenda; for "memo", "cost-sharing memo" or "write-up
  for the commission" call draft_memo with audience regulator. One sentence in reply; the card or report carries the text."""
