from datetime import date


from app.config import ASSUMPTIONS, MAX_DRIVE_MIN, MILE_M
from app.llm import generate, provider, unsourced
from app.engine.cost import savings
from app.queries import JOB_SQL, OPP_SQL, shareable

QUALITY = {"straight_line": "approximate route (straight line between endpoints)", "partial_point": "one endpoint located",
           "matched_point": "substation located", "existing_path": "follows existing line"}
BASIS = {"filed": "start date from filing", "spend_years": "start from budget years", "default_duration": "start derived from typical duration",
         "derived": "derived phase"}
FLAGS = {"over_45_min_drive": "More than a 45 minute drive apart by road, so crews and yards cannot be shared",
         "hurricane_season_high_risk": "Shared work falls in hurricane season in a high-risk area: plan joint storm staging",
         "tie_line": "Involves an interstate tie line, which both utilities operate",
         "shared_endpoint": "Both projects touch the same substation",
         "shared_wetland": "Both projects touch the same mapped wetland (USFWS NWI): coordinate permits and environmental review"}
AGENDA = ["Confirm scope and current schedule of both projects", "Walk the shared area on the map: access roads, crossings, laydown sites",
          "Check whether outage windows or construction phases can line up", "Agree what to share first (crews, yard, right-of-way, permits)",
          "Name one contact per utility and set a follow-up date"]


def ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def usd(n):
    return f"${int(n):,}"


def facts(conn, opp_id):
    o = conn.execute(OPP_SQL + " WHERE op.id = %s", (opp_id,)).fetchone()
    if not o:
        return None
    jobs = {j["id"]: j for j in conn.execute(JOB_SQL + " WHERE j.id IN (%s, %s)", (o["job_a"], o["job_b"])).fetchall()}
    return o, jobs[o["job_a"]], jobs[o["job_b"]], savings(o["tier"], o["overlap_m"], drive_min=o["drive_min"])


def template_summary(o, a, b):
    return (f"{a['org_name']} and {b['org_name']} plan work close together: {a['name']} and {b['name']}. "
            f"They fall in the {o['tier']} tier, so the utilities could share {', '.join(shareable(o['tier'], o['a_phase'], o['b_phase'], o['drive_min'])[:3])}.")


def llm_summary(o, a, b):
    if not provider():
        return None
    prompt = (f"Write two plain sentences for utility planners explaining why these two projects should coordinate. "
              f"Do not include any numbers, dates or dollar amounts.\nProject A: {a['name']} ({a['org_name']}): {a['description']}\n"
              f"Project B: {b['name']} ({b['org_name']}): {b['description']}\nShareable: {', '.join(shareable(o['tier'], o['a_phase'], o['b_phase'], o['drive_min']))}")
    try:
        text = generate(prompt)
    except Exception:
        return None
    return None if unsourced(text, "") else text  # any number means the model broke the rule


def job_row(j):
    window = f"{j['start_at']:%b %Y} to {j['end_at']:%b %Y}"
    return (f"| {j['org_name']} | {j['name']}{' (' + j['phase'] + ')' if j['phase'] else ''} | {j['job_type'].replace('_', ' ')}"
            f"{', ' + str(j['voltage_kv']) + ' kV' if j['voltage_kv'] else ''} | {window} ({BASIS.get(j['window_basis'], j['window_basis'])}) "
            f"| {j['in_service']:%b %d, %Y} | {QUALITY.get(j['geom_quality'], j['geom_quality'])}, {round(j['confidence'] * 100)}% "
            f"| {j['source_title']}, p.{j['source_page']} |")


def build(conn, opp_id):
    f = facts(conn, opp_id)
    if not f:
        return None
    o, a, b, s = f
    summary = llm_summary(o, a, b)
    lines = [
        f"# Coordination brief: {a['name']} / {b['name']}",
        f"Opportunity #{o['id']} · prepared {date.today():%b %d, %Y} by OpenCrew · public data only", "",
        "## Summary", summary or template_summary(o, a, b), "",
        "## The two projects",
        "| Utility | Project | Type | Work window | In service | Location | Source |", "|---|---|---|---|---|---|---|",
        job_row(a), job_row(b), "",
        "## Why coordinate",
        f"- Closest distance: {o['distance_m'] / MILE_M:.1f} mi ({o['tier']} tier); center to center: {o['center_distance_m'] / MILE_M:.1f} mi",
        f"- Build windows overlap: {round(o['time_overlap'] * 100)}% of the shorter window",
        f"- In-service dates are {o['time_gap_days']} days apart" if o["time_gap_days"] is not None else "- In-service gap: unknown",
    ]
    if o["drive_min"] is not None:
        lines.append(f"- By road: {o['drive_min']:.0f} min ({o['drive_km']:.0f} km) between the closest points; crews and yards "
                     f"count only within {MAX_DRIVE_MIN} min" + (" (this pair is too far)" if o["drive_min"] > MAX_DRIVE_MIN else ""))
    lines.append(f"- Area context: hurricane risk {round(o['risk'] * 100)}/100 (FEMA NRI), social vulnerability "
                 f"{ordinal(round(o['vulnerability'] * 100))} percentile (CDC SVI), at the midpoint between the projects")
    lines += [f"- {FLAGS.get(f, f)}" for f in o["flags"]]
    if o["overlap_m"] > 0:
        lines.append(f"- Parallel corridor within 1 mile: {o['overlap_m'] / MILE_M:.1f} mi")
    lines += ["", "## What could be shared", *[f"- {r}" for r in shareable(o["tier"], o["a_phase"], o["b_phase"], o["drive_min"])], "",
              "## Savings estimate", f"**{usd(s['low'])} to {usd(s['high'])}**, assuming the work is scheduled together.", "",
              "| Item | Low | High |", "|---|---|---|", *[f"| {k} | {usd(v['low'])} | {usd(v['high'])} |" for k, v in s["items"].items()], "",
              "## Cost assumptions and sources",
              *[f"- {v['label']}: {v['low']:,} to {v['high']:,} {v['unit']}{'' if v['verified'] else ' (estimate)'}. "
                f"Source: [{v['source']}]({v['url']}), p.{v['page']}." if v["url"] else f"- {v['label']}: {v['source']}"
                for v in ASSUMPTIONS.values() if v.get("scope") != "storm"], "",
              "## Proposed agenda for a first call", *[f"{i}. {t}" for i, t in enumerate(AGENDA, 1)], "",
              "## Data notes",
              "- Distances, overlaps and dollar ranges are computed by deterministic code, not AI.",
              "- Straight-line routes and derived windows are approximations; confirm with each utility's engineering team."]
    return {"markdown": "\n".join(lines), "summary_source": "gemini" if summary else "template"}
