"""Future considerations: what else has to be true for the pair to work, beyond distance and dates."""
from rapidfuzz import fuzz

from app.feasibility.common import day, factor, ym
from app.geo.geolocate import norm

SAME = 90  # token match for two station names to count as one place


def dependencies(job, others):
    """Other projects in the same utility's list that touch one of this job's endpoints and finish later: this job may wait on them."""
    ends = [norm(e) for e in job.get("endpoints") or [] if e]
    out = []
    for o in others:
        if o["id"] == job["id"] or not o.get("in_service") or not job.get("in_service"):
            continue
        oends = [norm(e) for e in o.get("endpoints") or [] if e]
        if any(x and y and fuzz.token_set_ratio(x, y) >= SAME for x in ends for y in oends) and day(o["in_service"]) > day(job["in_service"]):
            out.append({"id": o["id"], "name": o["name"], "in_service": day(o["in_service"]).isoformat()})
    return out[:5]


def assess(ctx):
    op, ours, theirs = ctx["op"], ctx["ours"], ctx["theirs"]
    evidence, conditions, score = [], [], 0.8
    sources = ["planner project lists (endpoints, status, in-service dates)"]
    for who, j in (("our", ours), ("their", theirs)):
        deps = dependencies(j, ctx.get("neighbours", {}).get(j["org_id"], []))
        if deps:
            score -= 0.1
            evidence.append(f"{who} {j['name']} shares a station with later work: " + ", ".join(f"{d['name']} ({d['in_service'][:4]})" for d in deps[:2]))
            conditions.append(f"check that {who} later projects at the same station do not push this one back")
    if ours.get("state") and theirs.get("state") and ours["state"] != theirs["state"]:
        conditions.append("shared assets across a state line need both commissions to sign off")
        score -= 0.05
    if op["tier"] in ("crossing", "land"):
        evidence.append("the lines share a corridor or cross: structures and right-of-way can be joint")
        conditions.append("a joint-use or crossing agreement has to be in place before construction")
    if "shared_endpoint" in set(op.get("flags") or []) or op["tier"] == "crossing":
        conditions.append("outage windows at the shared station must be booked together")
    soft = [j["name"] for j in (ours, theirs) if any(w in (j.get("status") or "").lower() for w in ("conceptual", "proposed", "future", "concept"))]
    if soft:
        score -= 0.15
        evidence.append("not yet committed: " + ", ".join(soft))
    for j in (ours, theirs):
        if j.get("in_service"):
            evidence.append(f"{j['name']} in service {ym(j['in_service'])}")
    if not evidence:
        evidence.append("no dependencies or approvals found beyond the usual permits")
    return factor("future", "Future considerations", score, evidence, conditions, sources)
