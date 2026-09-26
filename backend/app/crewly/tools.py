from rapidfuzz import fuzz, process

from datetime import datetime

from app import outreach, vendors
from app.config import MILE_M
from app.ingest import filing
from app.engine.cost import savings
from app.queries import JOB_SQL, OPP_SQL, shareable
from app.storm import replay
from app.storm.helene import LANDFALL

REGIONS = {  # lon/lat boxes for place filters
    "savannah": (-81.6, 31.8, -80.6, 32.6), "augusta": (-82.4, 33.2, -81.6, 33.8), "charleston": (-80.3, 32.6, -79.7, 33.1),
    "columbia": (-81.3, 33.8, -80.8, 34.2), "savannah river": (-82.6, 31.9, -80.8, 34.1), "hilton head": (-81.0, 32.1, -80.6, 32.4),
}


def _mi(m):
    return round(m / MILE_M, 1)


def _opp_row(o):
    return {
        "id": o["id"], "a": f"{o['a_name']}{' (' + o['a_phase'] + ')' if o['a_phase'] else ''} [{o['a_org']}]",
        "b": f"{o['b_name']}{' (' + o['b_phase'] + ')' if o['b_phase'] else ''} [{o['b_org']}]",
        "tier": o["tier"], "closest_mi": _mi(o["distance_m"]), "center_to_center_mi": _mi(o["center_distance_m"]),
        "build_window_overlap_pct": round(o["time_overlap"] * 100), "in_service_gap_days": o["time_gap_days"],
        "flags": o["flags"], "hurricane_risk_pct": round(o["risk"] * 100), "social_vulnerability_pct": round(o["vulnerability"] * 100),
        "savings_usd": f"${int(o['savings_low']):,} to ${int(o['savings_high']):,}", "score": round(o["score"], 2), "status": o["status"],
    }


def find_overlaps(conn, horizon="long", org=None, tier=None, region=None, min_time_overlap_pct=None, limit=10):
    sql = OPP_SQL + " WHERE op.horizon = %(h)s AND (%(t)s::text IS NULL OR op.tier = %(t)s)"
    sql += " AND (%(o)s::text IS NULL OR ja.org_id = %(o)s OR jb.org_id = %(o)s) AND op.time_overlap * 100 >= %(m)s"
    box = REGIONS.get((region or "").lower())
    if box:
        sql += " AND ST_Intersects(ST_Centroid(op.link::geometry), ST_MakeEnvelope(%(x0)s, %(y0)s, %(x1)s, %(y1)s, 4326))"
    rows = conn.execute(sql + " ORDER BY op.score DESC, op.distance_m LIMIT %(l)s",
                        {"h": horizon, "t": tier, "o": org, "m": min_time_overlap_pct or 0, "l": min(limit, 25),
                         **dict(zip(("x0", "y0", "x1", "y1"), box or (0, 0, 0, 0)))}).fetchall()
    result = {"count": len(rows), "region_known": bool(box) if region else None, "opportunities": [_opp_row(r) for r in rows]}
    return result, [{"type": "filter", "horizon": horizon, "tier": tier, "opportunity_ids": [r["id"] for r in rows]}]


def get_opportunity(conn, opportunity_id):
    o = conn.execute(OPP_SQL + " WHERE op.id = %s", (opportunity_id,)).fetchone()
    if not o:
        return {"error": f"no opportunity {opportunity_id}"}, []
    jobs = {j["id"]: j for j in conn.execute(JOB_SQL + " WHERE j.id IN (%s, %s)", (o["job_a"], o["job_b"])).fetchall()}

    def job(j):
        return {"name": j["name"], "phase": j["phase"], "utility": j["org_name"], "type": j["job_type"], "voltage_kv": j["voltage_kv"],
                "work_window": f"{j['start_at']:%b %Y} to {j['end_at']:%b %Y}", "window_basis": j["window_basis"],
                "in_service": f"{j['in_service']:%b %d, %Y}", "location_quality": j["geom_quality"],
                "location_confidence_pct": round(j["confidence"] * 100), "source": f"{j['source_title']}, page {j['source_page']}",
                "description": j["description"]}

    s = savings(o["tier"], o["overlap_m"])
    return ({**_opp_row(o), "job_a": job(jobs[o["job_a"]]), "job_b": job(jobs[o["job_b"]]), "shareable": shareable(o["tier"]),
             "savings_breakdown": {k: f"${int(v['low']):,} to ${int(v['high']):,}" for k, v in s["items"].items()}},
            [{"type": "select", "horizon": o["horizon"], "opportunity_id": o["id"]}])


def estimate_savings(conn, opportunity_id, assumptions=None):
    o = conn.execute("SELECT id, tier, overlap_m, horizon FROM opportunity WHERE id = %s", (opportunity_id,)).fetchone()
    if not o:
        return {"error": f"no opportunity {opportunity_id}"}, []
    s = savings(o["tier"], o["overlap_m"], assumptions)
    return ({"opportunity_id": o["id"], "savings_usd": f"${int(s['low']):,} to ${int(s['high']):,}",
             "breakdown": {k: f"${int(v['low']):,} to ${int(v['high']):,}" for k, v in s["items"].items()},
             "assumption_overrides": assumptions or {}},
            [{"type": "select", "horizon": o["horizon"], "opportunity_id": o["id"]}])


def search_projects(conn, query, org=None):
    rows = conn.execute("SELECT j.id, j.name, j.org_id, j.in_service, j.geom_quality FROM job j WHERE j.horizon = 'long' AND (%s::text IS NULL OR j.org_id = %s)",
                        (org, org)).fetchall()
    hits = process.extract(query, {r["id"]: r["name"] for r in rows}, scorer=fuzz.WRatio, limit=5)
    by_id = {r["id"]: r for r in rows}
    out = []
    for _, sc, jid in hits:
        if sc < 60:
            continue
        r = by_id[jid]
        n = conn.execute("SELECT count(*) AS n FROM opportunity WHERE horizon = 'long' AND (job_a = %s OR job_b = %s)", (jid, jid)).fetchone()["n"]
        out.append({"job_id": jid, "name": r["name"], "utility": r["org_id"], "in_service": f"{r['in_service']:%b %Y}",
                    "location_quality": r["geom_quality"], "opportunities": n})
    return {"matches": out}, []


def focus_map(conn, opportunity_id=None, region=None):
    if opportunity_id:
        o = conn.execute("SELECT id, horizon FROM opportunity WHERE id = %s", (opportunity_id,)).fetchone()
        if o:
            return {"focused": f"opportunity {o['id']}"}, [{"type": "select", "horizon": o["horizon"], "opportunity_id": o["id"]}]
    box = REGIONS.get((region or "").lower())
    if box:
        return {"focused": region}, [{"type": "fly", "bbox": box}]
    return {"error": "unknown place; known regions: " + ", ".join(REGIONS)}, []


def storm_status(conn, time=None, hours_from_landfall=None):
    t = datetime.fromisoformat(time.replace("Z", "+00:00")) if time else LANDFALL
    if hours_from_landfall is not None:
        from datetime import timedelta
        t = LANDFALL + timedelta(hours=float(hours_from_landfall))
    f = replay.frame(conn, t)
    reports = f["reports"]["features"]
    cone = f["cone"]["features"][0]["properties"]["payload"] if f["cone"]["features"] else None
    return ({"time_utc": t.isoformat(), "landfall_utc": LANDFALL.isoformat(), "forecast_advisory": cone and cone["advisory"],
             "substations_in_forecast_cone": f["exposure"], "damage_reports_so_far": len(reports),
             "reports_mentioning_power": sum(1 for r in reports if r["properties"]["payload"].get("power")),
             "active_warnings": len(f["warnings"]["features"]),
             "shared_staging_points": [{"desc_sites": s["properties"]["desc_n"], "gpc_sites": s["properties"]["gpc_n"],
                                        "lon": s["geometry"]["coordinates"][0], "lat": s["geometry"]["coordinates"][1]} for s in f["staging"]["features"]]},
            [{"type": "storm", "at": t.isoformat()}])


def find_contacts(conn, opportunity_id):
    return {"contacts": [{"contact_id": c["id"], "utility": c["org_name"], "role": c["role"], "email": c["email"], "demo_inbox": c["is_demo"]}
                         for c in outreach.contacts(conn, opportunity_id)]}, [{"type": "select", "horizon": None, "opportunity_id": opportunity_id}]


def draft_outreach(conn, opportunity_id, contact_id):
    row = outreach.draft(conn, opportunity_id, contact_id)
    if not row:
        return {"error": "opportunity or contact not found"}, []
    return ({"outreach_id": row["id"], "state": row["state"], "subject": row["subject"],
             "note": "Draft saved. A person must approve it in the detail panel before anything is sent."},
            [{"type": "select", "horizon": None, "opportunity_id": opportunity_id}])


def find_vendors(conn, opportunity_id, service="crane rental"):
    mid = vendors.midpoint(conn, opportunity_id)
    if not mid:
        return {"error": f"no opportunity {opportunity_id}"}, []
    try:
        found = vendors.search(mid["lat"], mid["lon"], service)
    except Exception as e:
        return {"error": str(e)[:200]}, []
    return {"service": service, "near_opportunity": opportunity_id, "vendors": found[:6]}, [{"type": "select", "horizon": None, "opportunity_id": opportunity_id}]


def ingest_filing(conn, url, utility_id=None, utility_name=None, state="SC"):
    try:
        out = filing.ingest(conn, filing.download(url), utility_id, utility_name, state, url=url)
    except Exception as e:  # bad link, not a pdf, or no gemini key
        conn.rollback()
        return {"error": str(e)[:300]}, []
    return out, ([] if "error" in out else [{"type": "reload"}])


HORIZON = {"type": "string", "enum": ["long", "near", "emergency"], "description": "long = multi-year plans, near = derived monthly phases, emergency = Helene storm restoration"}
TOOLS = {
    "find_overlaps": (find_overlaps, "List ranked cross-utility coordination opportunities. Filters the map and list in the UI.", {
        "horizon": HORIZON, "org": {"type": "string", "enum": ["desc", "gpc"]},
        "tier": {"type": "string", "enum": ["crossing", "land", "site", "crew"]},
        "region": {"type": "string", "description": "one of: " + ", ".join(REGIONS)},
        "min_time_overlap_pct": {"type": "number"}, "limit": {"type": "integer"}}, []),
    "get_opportunity": (get_opportunity, "Full details for one opportunity: both projects, windows, sources, shareable resources, savings. Selects it on the map.", {
        "opportunity_id": {"type": "integer"}}, ["opportunity_id"]),
    "estimate_savings": (estimate_savings, "Recompute the savings range for an opportunity, optionally with assumption overrides "
                         "(keys: row_width_m, land_usd_per_acre, yard_usd, mobilization_usd, outage_usd; each {low, high}).", {
        "opportunity_id": {"type": "integer"}, "assumptions": {"type": "object"}}, ["opportunity_id"]),
    "search_projects": (search_projects, "Find projects by name and how many opportunities each has.", {
        "query": {"type": "string"}, "org": {"type": "string", "enum": ["desc", "gpc"]}}, ["query"]),
    "storm_status": (storm_status, "Hurricane Helene replay status at a time: forecast cone, substations exposed, damage reports, shared staging points. "
                     "Moves the storm replay to that time.", {
        "time": {"type": "string", "description": "ISO time in UTC"}, "hours_from_landfall": {"type": "number", "description": "e.g. -24 or 6"}}, []),
    "find_contacts": (find_contacts, "Contacts at both utilities for an opportunity.", {"opportunity_id": {"type": "integer"}}, ["opportunity_id"]),
    "draft_outreach": (draft_outreach, "Draft (never send) an intro email to a contact about an opportunity.", {
        "opportunity_id": {"type": "integer"}, "contact_id": {"type": "integer"}}, ["opportunity_id", "contact_id"]),
    "find_vendors": (find_vendors, "Find vendors (crane rental, equipment rental, utility contractor) within 40 km of an opportunity.", {
        "opportunity_id": {"type": "integer"}, "service": {"type": "string"}}, ["opportunity_id"]),
    "ingest_filing": (ingest_filing, "Ingest a public utility filing PDF from a link: CEII check, parse, place projects, recompute overlaps.", {
        "url": {"type": "string"}, "utility_id": {"type": "string", "description": "short id for a new utility, e.g. santee"},
        "utility_name": {"type": "string"}, "state": {"type": "string", "description": "two-letter home state"}}, ["url"]),
    "focus_map": (focus_map, "Fly the map to an opportunity or a named region.", {
        "opportunity_id": {"type": "integer"}, "region": {"type": "string"}}, []),
}
