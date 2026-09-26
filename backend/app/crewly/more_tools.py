import re

from rapidfuzz import fuzz, process, utils

from app.config import ASSUMPTIONS, MILE_M, STATUSES
from app.crewly import brief
from app.engine import equipment
from app.engine.cost import savings_for
from app.engine.scoring import tier_for, time_overlap

TABS = ["overlaps", "equipment", "plan", "review"]


def _usd(lo, hi):
    return f"${int(lo):,} to ${int(hi):,}"


def _bbox(conn, ids):
    b = conn.execute("""SELECT ST_XMin(e) AS x0, ST_YMin(e) AS y0, ST_XMax(e) AS x1, ST_YMax(e) AS y1
                        FROM (SELECT ST_Extent(geom::geometry) AS e FROM job WHERE id = ANY(%s)) t""", (ids,)).fetchone()
    if not b or b["x0"] is None:
        return None
    pad = 0.05  # about 5 km so single points are not a zero-size box
    return [b["x0"] - pad, b["y0"] - pad, b["x1"] + pad, b["y1"] + pad]


GENERIC = {"project", "line", "rebuild", "substation", "sub", "kv", "the", "and", "new", "upgrade", "area", "improvements", "primary", "tap"}


def _shares_word(q, name):
    words = utils.default_process(name).split()
    key = [t for t in q if len(t) >= 3 and t not in GENERIC and not t.isdigit()]
    return not key or any(fuzz.ratio(t, w) >= 85 for t in key for w in words)  # at least one meaningful word must match


def rank(query, choices, limit=3):
    q = utils.default_process(query).split()
    in_order = re.compile(r"\b" + r"\b.*\b".join(map(re.escape, q)) + r"\b") if q else None
    hits = [h for h in process.extract(query, choices, scorer=fuzz.WRatio, processor=utils.default_process, limit=10) if _shares_word(q, h[0])]
    hits.sort(key=lambda h: (round(h[1]), bool(in_order and in_order.search(utils.default_process(h[0])))), reverse=True)  # same words in order win ties
    return [(key, score) for _, score, key in hits[:limit]]


def _find_job(conn, query, org=None):
    rows = conn.execute("SELECT id, name, org_id FROM job WHERE horizon = 'long' AND (%s::text IS NULL OR org_id = %s)", (org, org)).fetchall()
    return [(jid, sc) for jid, sc in rank(query, {r["id"]: r["name"] for r in rows}) if sc >= 60]


def set_status(conn, opportunity_id, status):
    if status not in STATUSES:
        return {"error": f"status must be one of {STATUSES}"}, []
    row = conn.execute("SELECT id, status, horizon FROM opportunity WHERE id = %s", (opportunity_id,)).fetchone()
    if not row:
        return {"error": f"no opportunity {opportunity_id}"}, []
    conn.execute("UPDATE opportunity SET status = %s WHERE id = %s", (status, opportunity_id))
    return ({"opportunity_id": row["id"], "old_status": row["status"], "new_status": status},
            [{"type": "select", "horizon": row["horizon"], "opportunity_id": row["id"]},
             {"type": "status", "opportunity_id": row["id"], "status": status}])


def set_assumptions(conn, overrides, opportunity_id=None, top=5):
    clean = {}
    for key, val in (overrides or {}).items():
        if key not in ASSUMPTIONS:
            return {"error": f"unknown assumption {key}; use one of {list(ASSUMPTIONS)}"}, []
        lo, hi = float(val.get("low", ASSUMPTIONS[key]["low"])), float(val.get("high", ASSUMPTIONS[key]["high"]))
        if lo < 0 or hi < lo:
            return {"error": f"{key}: need 0 <= low <= high"}, []
        clean[key] = {"low": lo, "high": hi}
    where = "id = %(id)s" if opportunity_id else "horizon = 'long' ORDER BY score DESC LIMIT %(n)s"
    rows = conn.execute(f"SELECT id, job_a, job_b, tier, overlap_m, drive_min, time_overlap, savings_low, savings_high FROM opportunity WHERE {where}",
                        {"id": opportunity_id, "n": min(int(top), 20)}).fetchall()
    if not rows:
        return {"error": f"no opportunity {opportunity_id}"}, []
    out = []
    for r in rows:
        s = savings_for(conn, r, clean)
        out.append({"opportunity_id": r["id"], "tier": r["tier"], "default_savings_usd": _usd(r["savings_low"], r["savings_high"]),
                    "new_savings_usd": _usd(s["low"], s["high"])})
    values = {k: {"low": v["low"], "high": v["high"]} for k, v in ASSUMPTIONS.items()} | clean
    return ({"overrides": {k: _usd(v["low"], v["high"]) if "usd" in k else f"{v['low']:g} to {v['high']:g}" for k, v in clean.items()},
             "opportunities": out, "saved": False},
            [{"type": "assumptions", "values": values}])


def switch_view(conn, horizon=None, tier=None, tab=None):
    if horizon not in (None, "long", "near", "emergency") or tier not in (None, "crossing", "land", "site", "crew") or tab not in (None, *TABS):
        return {"error": "horizon: long|near|emergency, tier: crossing|land|site|crew, tab: " + "|".join(TABS)}, []
    return {"view": {"horizon": horizon, "tier": tier, "tab": tab}}, [{"type": "view", "horizon": horizon, "tier": tier, "tab": tab}]


def _find_pending(conn, query, org=None):
    rows = conn.execute("SELECT id, raw->>'name' AS name, org_id, raw->'endpoints' AS searched, raw->>'in_service' AS in_service, source_page "
                        "FROM job_review WHERE raw ? 'name' AND (%s::text IS NULL OR org_id = %s)", (org, org)).fetchall()
    hit = rank(query, {r["id"]: r["name"] for r in rows}, limit=1)
    return (next(r for r in rows if r["id"] == hit[0][0]), hit[0][1]) if hit else (None, 0)


def project_details(conn, query, org=None):
    hits = _find_job(conn, query, org)
    pending, pscore = _find_pending(conn, query, org)
    if pending and pscore >= 70 and pscore > (hits[0][1] if hits else 0):  # best match is still waiting for a location
        return ({"placed": False, "note": "parsed from the filing but not on the map yet (location review queue)",
                 "name": pending["name"], "utility": pending["org_id"], "in_service": pending["in_service"],
                 "substation_names_searched": pending["searched"], "source_page": pending["source_page"]},
                [{"type": "view", "horizon": None, "tier": None, "tab": "review"}])
    hits = [h for h in hits if h[1] >= 70]
    if not hits:
        return {"error": f"no project matching '{query}'"}, []
    jid = hits[0][0]
    j = conn.execute("""SELECT j.id, j.name, j.org_id, j.job_type, j.voltage_kv, j.description, lower(j.work_window) AS s, upper(j.work_window) AS e,
                               j.window_basis, j.in_service, j.geom_quality, j.confidence, j.source_page, d.title AS source,
                               ST_Length(j.geom) / %s AS length_mi
                        FROM job j LEFT JOIN source_doc d ON d.id = j.source_doc_id WHERE j.id = %s""", (MILE_M, jid)).fetchone()
    history = conn.execute("""SELECT observed_at::date AS observed, lower(work_window)::date AS s, upper(work_window)::date AS e
                              FROM job_version WHERE job_id = %s ORDER BY observed_at""", (jid,)).fetchall()
    opps = conn.execute("""SELECT op.id, op.tier, op.distance_m, op.time_overlap, op.score, CASE WHEN op.job_a = %(j)s THEN jb.name ELSE ja.name END AS partner
                           FROM opportunity op JOIN job ja ON ja.id = op.job_a JOIN job jb ON jb.id = op.job_b
                           WHERE op.horizon = 'long' AND %(j)s IN (op.job_a, op.job_b) ORDER BY op.score DESC LIMIT 10""", {"j": jid}).fetchall()
    return ({"job_id": j["id"], "name": j["name"], "utility": j["org_id"], "type": j["job_type"], "voltage_kv": j["voltage_kv"],
             "work_window": f"{j['s']:%b %Y} to {j['e']:%b %Y}", "window_basis": j["window_basis"], "in_service": f"{j['in_service']:%b %d, %Y}",
             "location_quality": j["geom_quality"], "location_confidence_pct": round(j["confidence"] * 100),
             "mapped_length_mi": round(j["length_mi"], 1) if j["length_mi"] else None, "source": f"{j['source']}, page {j['source_page']}",
             "description": j["description"],
             "plan_history": [{"plan_as_of": f"{h['observed']:%b %Y}", "window": f"{h['s']:%b %Y} to {h['e']:%b %Y}"} for h in history],
             "opportunities": [{"id": o["id"], "partner": o["partner"], "tier": o["tier"], "closest_mi": round(o["distance_m"] / MILE_M, 1),
                                "build_window_overlap_pct": round(o["time_overlap"] * 100)} for o in opps],
             "other_matches": [conn.execute("SELECT name FROM job WHERE id = %s", (h,)).fetchone()["name"] for h, _ in hits[1:]]},
            [{"type": "fly", "bbox": b} for b in [_bbox(conn, [jid])] if b])


def review_queue(conn, org=None, limit=8):
    counts = conn.execute("SELECT org_id, reason, count(*) AS n FROM job_review WHERE %s::text IS NULL OR org_id = %s GROUP BY 1, 2 ORDER BY 1, 2",
                          (org, org)).fetchall()
    sample = conn.execute("""SELECT raw->>'name' AS name, org_id, raw->>'in_service' AS in_service, raw->'endpoints' AS searched, source_page
                             FROM job_review WHERE %s::text IS NULL OR org_id = %s ORDER BY org_id, raw->>'in_service' LIMIT %s""",
                          (org, org, min(int(limit), 25))).fetchall()
    return ({"total": sum(c["n"] for c in counts), "by_utility_and_reason": [dict(c) for c in counts],
             "sample": [dict(s) for s in sample], "how_to_fix": "open the review queue and place a project with one map click"},
            [{"type": "view", "horizon": None, "tier": None, "tab": "review"}])


def equipment_matches(conn):
    groups = equipment.groups(conn)
    return ({"groups": [{"voltage_kv": g["voltage_kv"], "kind": g["kind"],
                         "desc_project": f"{g['desc']['name']} (in service {g['desc']['in_service']:%b %Y})",
                         "gpc_matches": [{"project": m["name"], "in_service": f"{m['in_service']:%b %Y}", "year_gap": m["year_gap"], "why": m["reason"]}
                                         for m in g["gpc"]]} for g in groups],
             "rule": "same equipment kind and voltage; in service within 1 year = joint procurement, a planned spare = shared spare pool"},
            [{"type": "view", "horizon": None, "tier": None, "tab": "equipment"}])


COMPARE_SQL = """
WITH p AS (
  SELECT id, name, org_id, geom, work_window, in_service,
         CASE WHEN ST_GeometryType(geom::geometry) = 'ST_LineString'
              THEN ST_Centroid(ST_MakeLine(ST_StartPoint(geom::geometry), ST_EndPoint(geom::geometry)))
              ELSE ST_Centroid(geom::geometry) END::geography AS center
  FROM job WHERE id IN (%(a)s, %(b)s)
)
SELECT a.name AS a_name, b.name AS b_name, a.org_id AS a_org, b.org_id AS b_org, ST_Distance(a.geom, b.geom) AS distance_m,
       ST_Intersects(a.geom, b.geom) AS touches, ST_Distance(a.center, b.center, false) AS center_m,
       lower(a.work_window) AS a_s, upper(a.work_window) AS a_e, lower(b.work_window) AS b_s, upper(b.work_window) AS b_e,
       abs(a.in_service - b.in_service) AS gap_days
FROM p a, p b WHERE a.id = %(a)s AND b.id = %(b)s
"""


def compare_projects(conn, a, b):
    ha, hb = _find_job(conn, a), _find_job(conn, b)
    if not ha or not hb:
        return {"error": f"could not find {'first' if not ha else 'second'} project"}, []
    ja, jb = ha[0][0], hb[0][0]
    if ja == jb:
        return {"error": "both names matched the same project"}, []
    r = conn.execute(COMPARE_SQL, {"a": ja, "b": jb}).fetchone()
    opp = conn.execute("SELECT id FROM opportunity WHERE horizon = 'long' AND job_a = %s AND job_b = %s", tuple(sorted((ja, jb)))).fetchone()
    tier = tier_for(r["distance_m"], r["touches"])
    return ({"a": f"{r['a_name']} [{r['a_org']}]", "b": f"{r['b_name']} [{r['b_org']}]",
             "closest_mi": round(r["distance_m"] / MILE_M, 2), "center_to_center_mi": round(r["center_m"] / MILE_M, 2),
             "within_25_mi": r["center_m"] < 25 * MILE_M, "tier": tier or "none (over 25 mi)",
             "build_window_overlap_pct": round(time_overlap(r["a_s"], r["a_e"], r["b_s"], r["b_e"]) * 100),
             "in_service_gap_days": r["gap_days"], "same_utility": r["a_org"] == r["b_org"], "opportunity_id": opp and opp["id"]},
            [{"type": "fly", "bbox": bb} for bb in [_bbox(conn, [ja, jb])] if bb])


def draft_brief(conn, opportunity_id):
    out = brief.build(conn, opportunity_id)
    if not out:
        return {"error": f"no opportunity {opportunity_id}"}, []
    md = out["markdown"]
    sections = [l[3:] for l in md.splitlines() if l.startswith("## ")]
    summary = md.split("## Summary", 1)[1].split("##", 1)[0].strip() if "## Summary" in md else ""
    return ({"opportunity_id": opportunity_id, "sections": sections, "summary": summary, "summary_written_by": out["summary_source"],
             "note": "brief opened in the UI; it can be downloaded as Markdown or printed to PDF"},
            [{"type": "brief", "opportunity_id": opportunity_id, "markdown": md, "source": out["summary_source"]}])


def timeline_filter(conn, years=None, orgs=None):
    known = [r["id"] for r in conn.execute("SELECT id FROM org ORDER BY id").fetchall()]
    if orgs and any(o not in known for o in orgs):
        return {"error": f"orgs must be among {known}"}, []
    span = None
    if years:
        ys = [int(y) for y in years]
        span = [min(ys), max(ys)]
    counts = conn.execute("""SELECT org_id, count(*) AS n FROM job WHERE horizon = 'long'
                             AND (%(o)s::text[] IS NULL OR org_id = ANY(%(o)s))
                             AND (%(y0)s::int IS NULL OR work_window && tstzrange(make_date(%(y0)s, 1, 1), make_date(%(y1)s + 1, 1, 1)))
                             GROUP BY org_id ORDER BY org_id""", {"o": orgs or None, "y0": span and span[0], "y1": span and span[1]}).fetchall()
    return ({"years": span, "orgs": orgs or known, "projects_in_view": {c["org_id"]: c["n"] for c in counts}},
            [{"type": "timeline", "years": span, "orgs": orgs or None}])


ID = {"type": "integer"}
MORE_TOOLS = {
    "set_status": (set_status, "Move an opportunity along the coordination pipeline. Changes the saved status; the UI updates.", {
        "opportunity_id": ID, "status": {"type": "string", "enum": STATUSES}}, ["opportunity_id", "status"]),
    "set_assumptions": (set_assumptions, "What-if on cost assumptions (not saved): recompute savings for one opportunity or the top N long-range ones "
                        "and move the UI sliders. Keys: " + ", ".join(ASSUMPTIONS) + "; each {low, high}.", {
        "overrides": {"type": "object"}, "opportunity_id": ID, "top": {"type": "integer"}}, ["overrides"]),
    "switch_view": (switch_view, "Change what the UI shows: horizon (long, near, emergency), tier filter, and list tab (overlaps, equipment, review).", {
        "horizon": {"type": "string", "enum": ["long", "near", "emergency"]}, "tier": {"type": "string", "enum": ["crossing", "land", "site", "crew"]},
        "tab": {"type": "string", "enum": TABS}}, []),
    "project_details": (project_details, "Everything about one project by name: window and where it came from, in-service date, location quality, "
                        "source page, earlier plans, and its opportunities. Also finds projects still waiting for location review.", {
        "query": {"type": "string"}, "org": {"type": "string", "enum": ["desc", "gpc"]}}, ["query"]),
    "review_queue": (review_queue, "Projects parsed from filings that are not on the map yet, with the substation names that were searched.", {
        "org": {"type": "string", "enum": ["desc", "gpc"]}, "limit": {"type": "integer"}}, []),
    "equipment_matches": (equipment_matches, "Substation equipment both utilities could buy together or share as a spare.", {}, []),
    "compare_projects": (compare_projects, "Distance, center distance, build-window overlap and in-service gap between any two placed projects, "
                         "even when they are not an opportunity.", {"a": {"type": "string"}, "b": {"type": "string"}}, ["a", "b"]),
    "draft_brief": (draft_brief, "Write the one-page coordination brief for an opportunity and open it in the UI.", {"opportunity_id": ID}, ["opportunity_id"]),
    "timeline_filter": (timeline_filter, "Limit the timeline to a year range and/or utilities.", {
        "years": {"type": "array", "items": {"type": "integer"}, "description": "[from, to]"},
        "orgs": {"type": "array", "items": {"type": "string"}}}, []),
}
