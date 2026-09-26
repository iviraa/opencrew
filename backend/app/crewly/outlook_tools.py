from datetime import datetime, timedelta, timezone

from app.storm import hazards, outlook
from app.storm.helene import REPLAY


def _time(at):
    if not at:
        return None
    t = datetime.fromisoformat(at.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _overlaps(bbox, box):
    return bbox and not (bbox[2] < box[0] or bbox[0] > box[2] or bbox[3] < box[1] or bbox[1] > box[3])


def outlook_heads_up(conn, at=None, region=None):
    """Official outlooks for the week after `at`: severe storms, flash flooding, tropical, watches, with exposed sites."""
    from app.crewly.tools import REGIONS
    t = _time(at)
    helene = t is not None and t < REPLAY[1] + timedelta(days=7) and t.year == REPLAY[0].year
    clock = REPLAY[1] if helene else datetime.now(timezone.utc)
    known = min(t or clock, clock)
    mode = "replay" if helene else "live"
    items = outlook.heads_up(conn, known, mode)
    box = REGIONS.get((region or "").lower())
    if box:
        items = [i for i in items if i["bbox"] is None or _overlaps(i["bbox"], box)]
    have = outlook.available(conn, mode)
    out = {"as_of_utc": known.isoformat(), "mode": mode, "region_known": bool(box) if region else None,
           "items": [{**{k: i[k] for k in ("day", "text", "product", "level")}, "sites": i["sites"][:5]} for i in items[:12]],
           "products_loaded": {k: v.get("n", 0) for k, v in have.items()},
           "note": "SPC, WPC and NHC official outlooks; nothing listed means nothing on those outlooks touches Georgia or South Carolina"}
    if mode == "replay" and not have.get("wpc_ero", {}).get("n"):
        out["missing"] = "WPC rainfall outlooks for Helene are not archived, so flood risk is not shown for the replay"
    actions = [{"type": "outlook", "at": known.isoformat(), "scenario": "helene" if helene else "none"}]
    if items and items[0]["bbox"]:
        actions.append({"type": "fly", "bbox": items[0]["bbox"]})
    return out, actions


def site_hazards(conn, project):
    """FEMA floodplain and hurricane history for a long-range project, found by name or id."""
    job = conn.execute("""SELECT id, name, ST_XMin(ST_Envelope(geom::geometry)) AS x0, ST_YMin(ST_Envelope(geom::geometry)) AS y0,
                                 ST_XMax(ST_Envelope(geom::geometry)) AS x1, ST_YMax(ST_Envelope(geom::geometry)) AS y1
                          FROM job WHERE horizon = 'long' AND (id = %(q)s OR name ILIKE %(like)s)
                          ORDER BY id = %(q)s DESC, length(name) LIMIT 1""", {"q": project, "like": f"%{project}%"}).fetchone()
    if not job:
        return {"error": f"no long-range project matches '{project}'"}, []
    h = hazards.one(conn, job["id"])
    if not h:
        return {"project": job["name"], "error": "hazards not computed yet; run scripts.fetch_outlooks --hazards"}, []
    pad = 0.1
    return ({"project": job["name"], "in_floodplain": h["in_floodplain"], "flood_zones": h["flood_zones"],
             "hurricane_exposure": h["hurricane_exposure"], "hurricanes_within_50mi": h["hurricanes_50mi"],
             "storms_within_50mi": h["storms_50mi"], "since_year": h["since_year"], "facts": h["lines"],
             "sources": "FEMA National Flood Hazard Layer; NOAA HURDAT2 best tracks"},
            [{"type": "fly", "bbox": [job["x0"] - pad, job["y0"] - pad, job["x1"] + pad, job["y1"] + pad]}])


OUTLOOK_TOOLS = {
    "outlook": (outlook_heads_up, "What official forecasts say is coming in the next 7 days for Georgia and South Carolina: SPC severe storm "
                "outlooks, WPC flash flood outlooks, NHC tropical outlooks and wind probabilities, NWS watches, with the active work sites "
                "and substations inside. Use for 'what should we worry about this week'. Shows the forecast on the map.", {
        "at": {"type": "string", "description": "ISO time; omit for now, or a Sept 2024 time for the Helene replay"},
        "region": {"type": "string", "description": "optional place filter, e.g. savannah, augusta"}}, []),
    "site_hazards": (site_hazards, "Long-range hazard check for a planned project: FEMA 100-year floodplain and how many hurricanes "
                     "passed within 50 miles since 1950.", {"project": {"type": "string", "description": "project name or id"}}, ["project"]),
}
