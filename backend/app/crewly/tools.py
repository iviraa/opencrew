from rapidfuzz import fuzz, process

from app.config import MILE_M
from app.engine.cost import savings
from app.queries import JOB_SQL, OPP_SQL, shareable

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


HORIZON = {"type": "string", "enum": ["long", "near"], "description": "long = multi-year plans, near = derived monthly phases"}
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
    "focus_map": (focus_map, "Fly the map to an opportunity or a named region.", {
        "opportunity_id": {"type": "integer"}, "region": {"type": "string"}}, []),
}
