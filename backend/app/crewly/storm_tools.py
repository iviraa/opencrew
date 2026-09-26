from datetime import datetime, timedelta, timezone

from app.storm import briefing, response
from app.storm.helene import LANDFALL


def when(time, hours_from_landfall, default_h):
    if hours_from_landfall is not None:
        return LANDFALL + timedelta(hours=float(hours_from_landfall))
    if time:
        t = datetime.fromisoformat(time.replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    return LANDFALL + timedelta(hours=default_h)


def storm_briefing(conn, time=None, hours_from_landfall=None, safety_margin_h=None, crews_per_substation=None):
    t = when(time, hours_from_landfall, -36)
    opts = {k: v for k, v in {"safety_margin_h": safety_margin_h, "crews_per_substation": crews_per_substation}.items() if v is not None}
    b = briefing.build(conn, t, "helene", opts)
    if not b.get("storm"):
        return {"storm": None, "reason": b.get("reason")}, []
    out = {"time_utc": t.isoformat(), "advisory": b["storm"]["advisory"], "headline": b["headline"],
           "hours_to_first_winds": b["storm"]["hours_to_first_winds"],
           "likely_hit": [{k: h[k] for k in ("name", "damaging_winds", "hurricane_winds", "tropical_storm_winds", "sentence")} | {"top_counties": h["counties"][:3]}
                          for h in b["likely_hit"]],
           "pause_work_sites": [{k: p[k] for k in ("project", "phase", "status", "hours_left", "sentence")} for p in b["pause"][:8]],
           "pause_total": len(b["pause"]),
           "staging": [{"county": s["county"], "shared": s["shared"], "sentence": s["sentence"]} for s in b["staging"]],
           "crews": [c["sentence"] for c in b["crews"]], "assumptions": b["assumptions"]}
    return out, [{"type": "storm", "at": t.isoformat()}]


def restoration_plan(conn, time=None, hours_from_landfall=None, mutual_aid=True, crews_gpc=None, crews_desc=None):
    t = when(time, hours_from_landfall, 24)
    opts = {k: v for k, v in {"crews_gpc": crews_gpc, "crews_desc": crews_desc}.items() if v is not None}
    r = response.build(conn, t, "helene", bool(mutual_aid), opts)
    if not r.get("jobs"):
        return {"jobs": 0, "headline": r["headline"]}, [{"type": "storm", "at": t.isoformat()}]
    out = {"time_utc": t.isoformat(), "headline": r["headline"], "repair_jobs": r["jobs"], "crews": r["crews"], "summary": r["summary"],
           "cross_utility_moves": [x["sentence"] for x in r["explanations"] if x["cross_utility"]][:6],
           "routes": [{"crew": rt["crew"], "yard": rt["yard"]["county"], "jobs": [j["name"] for j in rt["jobs"]]} for rt in r["routes"]][:12],
           "assumptions": r["assumptions"]}
    return out, [{"type": "storm", "at": t.isoformat()}]


def explain_assignment(conn, crew=None, job=None, time=None, hours_from_landfall=None):
    t = when(time, hours_from_landfall, 24)
    r = response.build(conn, t, "helene", True)
    rows = r.get("explanations") or []
    needle = (crew or job or "").lower()
    hits = [x for x in rows if needle and (needle in x["crew"].lower() or needle in x["job_id"].lower()
                                           or any(needle in j["name"].lower() for rt in r["routes"] for j in rt["jobs"] if j["job_id"] == x["job_id"]))]
    if not hits:
        return {"error": f"no assignment matches '{crew or job}'", "crews": sorted({x["crew"] for x in rows})}, []
    return {"time_utc": t.isoformat(), "assignments": [x["sentence"] for x in hits[:6]]}, []


STORM_TOOLS = {
    "storm_briefing": (storm_briefing, "Pre-storm briefing from the NHC forecast for the Hurricane Helene scenario: substations likely hit per utility, "
                       "work sites to pause and by when, suggested staging yards (shared when both utilities are in reach), crews to ready. "
                       "Default time is 36 hours before landfall.", {
                           "time": {"type": "string", "description": "ISO time in UTC"}, "hours_from_landfall": {"type": "number", "description": "e.g. -36"},
                           "safety_margin_h": {"type": "number"}, "crews_per_substation": {"type": "number"}}, []),
    "restoration_plan": (restoration_plan, "Restoration crew plan after Helene's damage: crews of each utility assigned to repair jobs, alone vs with "
                         "mutual aid, with how much sooner repairs finish. Default time is 24 hours after landfall.", {
                             "time": {"type": "string"}, "hours_from_landfall": {"type": "number"}, "mutual_aid": {"type": "boolean"},
                             "crews_gpc": {"type": "integer"}, "crews_desc": {"type": "integer"}}, []),
    "explain_assignment": (explain_assignment, "Why a restoration crew was sent to a job, by crew name (e.g. 'Dominion Energy SC crew 1') or job/place name.", {
        "crew": {"type": "string"}, "job": {"type": "string"}, "time": {"type": "string"}, "hours_from_landfall": {"type": "number"}}, []),
}
