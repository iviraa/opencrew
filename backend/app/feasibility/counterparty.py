"""Counterparty: how the two companies have dealt with each other so far, and our own standing notes that touch this pair."""
import os
import re
import statistics
from datetime import datetime

import httpx

from app.companies import name, short
from app.feasibility.common import factor


def _rest(path, params):
    """Supabase REST with the backend key: request history is read by crewly for its own company's assessment."""
    r = httpx.get(f"{os.environ['SUPABASE_URL'].rstrip('/')}/rest/v1/{path}", params=params, timeout=10,
                  headers={"apikey": os.environ["SUPABASE_SECRET_KEY"]})
    r.raise_for_status()
    return r.json()


def fetch_requests(company, partner):
    try:
        return _rest("collab_request", {"select": "id,opportunity_id,from_company,to_company,status,feedback,created_at,responded_at",
                                        "or": f"(and(from_company.eq.{company},to_company.eq.{partner}),and(from_company.eq.{partner},to_company.eq.{company}))",
                                        "order": "created_at.desc", "limit": "50"})
    except Exception:
        return None


def fetch_memories(company):
    try:
        return _rest("crewly_memory", {"select": "id,text", "company_id": f"eq.{company}", "order": "created_at.asc", "limit": "20"})
    except Exception:
        return []


def _hours(r):
    try:
        a, b = datetime.fromisoformat(r["created_at"]), datetime.fromisoformat(r["responded_at"])
        return (b - a).total_seconds() / 3600
    except (KeyError, TypeError, ValueError):
        return None


def assess(ctx):
    company, partner = ctx["company"], ctx["partner"]
    reqs = ctx.get("requests")
    who = name(partner)
    sources = ["collaboration requests between the two companies", "our saved notes (crewly memory)"]
    evidence, conditions = [], []
    if reqs is None:
        score = None
        evidence.append("request history not available")
    elif not reqs:
        score = 0.55
        evidence.append(f"no requests yet between us and {who}")
    else:
        approved = [r for r in reqs if r["status"] == "approved"]
        declined = [r for r in reqs if r["status"] == "declined"]
        pending = [r for r in reqs if r["status"] == "pending"]
        evidence.append(f"{len(reqs)} request{'s' if len(reqs) != 1 else ''} with {who}: {len(approved)} approved, {len(declined)} declined, {len(pending)} pending")
        hours = [h for h in (_hours(r) for r in reqs if r.get("responded_at")) if h is not None]
        if hours:
            med = statistics.median(hours)
            evidence.append(f"they answer in about {med:.0f} hours" if med >= 1 else "they answer within the hour")
        last = next((r for r in reqs if r.get("feedback")), None)
        if last:
            evidence.append(f"latest feedback: \"{last['feedback'][:120]}\"")
        mine = [r for r in reqs if r["opportunity_id"] == ctx["op"]["id"]]
        if any(r["status"] == "approved" for r in mine):
            evidence.append("this overlap already has an approved request")
        score = 0.55 + 0.15 * min(len(approved), 3) - 0.2 * min(len(declined), 3)
        if declined and not approved:
            conditions.append(f"{short(partner)} declined before: address their feedback in the note")
    words = {w for w in re.findall(r"[a-z]+", f"{who} {short(partner)} {partner}".lower()) if len(w) > 3}
    hazard_words = {"hurricane", "storm", "winter", "ice", "summer", "season", "crew", "yard", "share", "outage"}
    for m in ctx.get("memories") or []:
        text = m.get("text", "")
        low = text.lower()
        if words & set(re.findall(r"[a-z]+", low)) or hazard_words & set(re.findall(r"[a-z]+", low)):
            conditions.append(f"our note: \"{text[:120]}\"")
    return factor("counterparty", "Counterparty", score, evidence, conditions, sources)
