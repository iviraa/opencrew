"""Location: how close the two works are, by road and by land, and what sits between them."""
from app.config import MAX_DRIVE_MIN, MILE_M
from app.feasibility.common import factor

TIER_SCORE = {"crossing": 0.95, "land": 0.85, "site": 0.7, "crew": 0.55}
DETOUR = 2.5  # road km more than this many times the straight line means poor access between the sites


def assess(ctx):
    op, ours, theirs = ctx["op"], ctx["ours"], ctx["theirs"]
    miles = op["distance_m"] / MILE_M
    score = TIER_SCORE.get(op["tier"], 0.5)
    evidence = [f"{op['tier']} tier: closest points {miles:.1f} mi apart"]
    conditions, sources = [], ["opportunity distance and drive time (OSRM)", "NWI wetlands and FEMA floodplain checks"]
    if op.get("drive_min") is not None:
        evidence.append(f"{op['drive_min']:.0f} min drive ({op.get('drive_km') or 0:.0f} km by road)")
        if op["drive_min"] > MAX_DRIVE_MIN:
            score -= 0.3
            conditions.append(f"crews and yards only serve both sites within {MAX_DRIVE_MIN} min; this pair is {op['drive_min']:.0f} min apart, so share land, permits or timing instead")
        straight_km = op["distance_m"] / 1000
        if straight_km > 1 and op.get("drive_km") and op["drive_km"] / straight_km > DETOUR:
            score -= 0.1
            evidence.append(f"road route is {op['drive_km'] / straight_km:.1f}x the straight line: access between the sites is roundabout")
    else:
        evidence.append("no road route found between the sites")
        score -= 0.1
    flags = set(op.get("flags") or [])
    if "shared_endpoint" in flags:
        evidence.append("both projects name the same substation or endpoint")
        score += 0.05
    if "shared_wetland" in flags:
        evidence.append("both works touch the same wetland")
        conditions.append("one wetland permit and access plan could cover both works")
    if "tie_line" in flags:
        evidence.append("one of the lines is a tie line between the two systems")
    wet = [j["name"] for j in (ours, theirs) if (j.get("hazard") or {}).get("in_floodplain")]
    if wet:
        evidence.append(f"in a FEMA floodplain: {', '.join(wet)}")
        conditions.append("laydown yards and access roads need to sit outside the floodplain")
        score -= 0.05
    if ours.get("state") and theirs.get("state") and ours["state"] != theirs["state"]:
        evidence.append(f"the works sit in two states ({ours['state']} and {theirs['state']})")
        conditions.append("permits and commission approvals come from two states")
        score -= 0.05
    if op["tier"] in ("crossing", "land") and op.get("overlap_m"):
        evidence.append(f"{op['overlap_m'] / MILE_M:.1f} mi of shared corridor")
    return factor("location", "Location", score, evidence, conditions, sources)
