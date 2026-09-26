"""Everything the factors look at, gathered once per assessment into plain rows so the factors stay pure and testable."""
from datetime import date

from app.companies import partner as partner_of
from app.crewly.app_tools import mine_sql
from app.queries import JOB_SQL

JOB_EXTRA = """
SELECT j.id, j.org_id, j.name, j.status, j.need, j.cost_usd, j.length_mi, j.voltage_kv, j.endpoints, j.in_service, j.state, j.planner, j.job_type,
       lower(j.work_window) AS start_at, upper(j.work_window) AS end_at,
       h.in_floodplain, h.flood_zones, h.hurricanes_50mi, h.storms_50mi,
       (SELECT json_agg(json_build_object('observed_at', v.observed_at, 'start', lower(v.work_window), 'end', upper(v.work_window)) ORDER BY v.observed_at)
        FROM job_version v WHERE v.job_id = j.id AND v.work_window <> j.work_window) AS history
FROM job j LEFT JOIN job_hazard h ON h.job_id = j.id WHERE j.id = %(id)s
"""
NEIGHBOURS_SQL = "SELECT id, name, endpoints, in_service, org_id FROM job WHERE horizon = 'long' AND org_id = ANY(%(orgs)s) AND endpoints IS NOT NULL"
PLAN_SQL = "SELECT job_ids FROM joint_plan ORDER BY id DESC LIMIT 1"


def job_row(conn, job_id):
    r = conn.execute(JOB_EXTRA, {"id": job_id}).fetchone()
    if not r:
        return None
    hist = [{"observed_at": v.get("observed_at"), "start": _ts(v.get("start")), "end": _ts(v.get("end"))} for v in (r["history"] or [])]
    return {"id": r["id"], "org_id": r["org_id"], "name": r["name"], "status": r["status"], "need": r["need"], "cost_usd": r["cost_usd"],
            "length_mi": r["length_mi"], "voltage_kv": r["voltage_kv"], "endpoints": r["endpoints"] or [], "in_service": r["in_service"],
            "state": r["state"], "planner": r["planner"], "job_type": r["job_type"], "start": r["start_at"], "end": r["end_at"], "history": hist,
            "hazard": None if r["in_floodplain"] is None and not r["flood_zones"] else
            {"in_floodplain": r["in_floodplain"], "flood_zones": r["flood_zones"], "hurricanes_50mi": r["hurricanes_50mi"], "storms_50mi": r["storms_50mi"]}}


def _ts(s):
    from datetime import datetime
    if not s or isinstance(s, datetime):
        return s
    try:
        return datetime.fromisoformat(str(s))
    except ValueError:
        return None


def overlap_row(conn, opportunity_id, company_id):
    return conn.execute(mine_sql(company_id) + " AND op.id = %s", (int(opportunity_id),)).fetchone()


def gather(conn, op, company_id, quick=False, today=None):
    """The assessment context for one overlap seen from company_id. quick=True skips the hazard models (used when ranking many)."""
    from app.engine.cost import savings_for
    from app.feasibility import counterparty, news
    partner = partner_of(op, company_id)
    a, b = job_row(conn, op["job_a"]), job_row(conn, op["job_b"])
    ours, theirs = (a, b) if a["org_id"] == company_id else (b, a)
    ctx = {"company": company_id, "partner": partner, "op": dict(op), "ours": ours, "theirs": theirs, "today": today or date.today()}
    try:
        ctx["savings"] = savings_for(conn, op)
    except Exception:
        ctx["savings"] = None
    rows = conn.execute(NEIGHBOURS_SQL, {"orgs": [ours["org_id"], theirs["org_id"]]}).fetchall()
    ctx["neighbours"] = {}
    for r in rows:
        ctx["neighbours"].setdefault(r["org_id"], []).append(dict(r))
    try:
        plan = conn.execute(PLAN_SQL).fetchone()
        ids = set(plan["job_ids"]) if plan else set()
        ctx["plan"] = {"has_plan": bool(plan), "covers_pair": {ours["id"], theirs["id"]} <= ids}
    except Exception:
        conn.rollback()
        ctx["plan"] = {"has_plan": False, "covers_pair": False}
    ctx["requests"] = counterparty.fetch_requests(company_id, partner)
    ctx["memories"] = counterparty.fetch_memories(company_id)
    ctx["news"] = news.fetch(conn, op["id"])
    ctx["hazards"], ctx["coordination"], ctx["month_cost"] = {}, None, None
    if not quick:
        from app.hazards import cost as hazard_cost, exposure
        for period in ("now7", "season"):
            try:
                ctx["hazards"][period] = exposure.assess(conn, "zone", op["id"], period, today=ctx["today"])
            except Exception:
                conn.rollback()
        try:
            got = hazard_cost.for_zone(conn, op["id"], "month", today=ctx["today"])
            if got:
                ctx["coordination"] = got[1]
                ctx["month_cost"] = {m["month"]: m["cost_per_30d"] for m in got[1].get("all_months", [])}
        except Exception:
            conn.rollback()
    return ctx
