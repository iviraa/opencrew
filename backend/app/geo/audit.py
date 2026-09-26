from rapidfuzz import fuzz

from app.geo.geolocate import km, norm
from app.geo.names import clean, counties, stated_full_miles

MILE_KM = 1.609
NAME_OK = 85  # fuzzy score below this between the filed name and the matched OSM name is worth a look
SPAN_KM = 80  # an unexplained line longer than this is suspicious in these filings
COUNTY_KM = 50


def line_km(coords):
    return sum(km((a[1], a[0]), (b[1], b[0])) for a, b in zip(coords, coords[1:]))


def assess(job, picks, coords, zone=None, in_home=None, county_at=None):
    """ok / suspect / wrong for one placement, with plain reasons. coords are [lon, lat] pairs of the drawn geometry."""
    reasons, status = [], "ok"
    rank = {"ok": 0, "suspect": 1, "wrong": 2}

    def flag(level, why):
        nonlocal status
        reasons.append(why)
        status = max(status, level, key=rank.get)

    for p in picks:
        if not p:
            continue
        via, filed = str(p.get("via", "")), p.get("query") or job["name"]
        if via.startswith(("node/", "way/", "relation/", "description:")):
            score = fuzz.token_set_ratio(norm(clean(filed)), norm(p.get("name")))
            if score < NAME_OK:
                flag("suspect", f"'{filed}' matched '{p.get('name')}' (name score {score:.0f})")
        if in_home and not in_home(p["lat"], p["lon"]):
            flag("suspect", f"{p.get('name')} is outside the utility's home state")
        if p.get("approx"):
            flag("suspect", f"only the town of {p.get('name')} is known, not the station")

    if len(coords) >= 2:
        length = line_km(coords)
        stated = stated_full_miles(job.get("description"))
        if stated:
            if length > 3 * stated * MILE_KM and length - stated * MILE_KM > 8 * MILE_KM:
                flag("wrong", f"drawn line is {length / MILE_KM:.0f} mi but the filing says {stated:g} mi")
            elif length > 1.8 * stated * MILE_KM and length - stated * MILE_KM > 4 * MILE_KM:
                flag("suspect", f"drawn line is {length / MILE_KM:.0f} mi, filing says {stated:g} mi")
        elif km((coords[0][1], coords[0][0]), (coords[-1][1], coords[-1][0])) > SPAN_KM:
            flag("suspect", f"endpoints are {km((coords[0][1], coords[0][0]), (coords[-1][1], coords[-1][0])) / MILE_KM:.0f} mi apart with no stated length")

    if coords and zone:
        c, reach = zone
        mid = coords[len(coords) // 2]
        d = km(c, (mid[1], mid[0]))
        exact = all(p.get("conf", 0) >= 0.95 for p in picks if p)
        if d > (2 * reach if exact else reach):  # big zones make exact name matches look far
            flag("suspect", f"{d:.0f} km from the rest of planning zone {job.get('zone')}")

    if coords and county_at:
        mid = coords[len(coords) // 2]
        for county in counties(job.get("description")):
            spot = county_at(county)
            if spot and km(spot, (mid[1], mid[0])) > COUNTY_KM:
                flag("suspect", f"description names {county} County, {km(spot, (mid[1], mid[0])):.0f} km away")
    return status, reasons
