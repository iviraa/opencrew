"""What an experiment measures, read from the engines on whatever data is under the transaction: base first, then the overlay."""
import time

from app.companies import name, partner, short
from app.engine.cost import savings_for
from app.hazards import cost as hcost
from app.hazards import exposure
from app.planner import build as planner
from app.queries import OPP_SQL
from app.scenario import engine

USD, DAYS, PCT, MONTHS, COUNT = "USD", "days", "%", "months", "count"


def m(value, unit=None, label=None, **extra):
    return {"value": value, "unit": unit, "label": label, **extra}


def scope_of(*parts):
    """Union of what several changes want measured."""
    out = {"opportunity_id": None, "job_ids": [], "plan_horizon": None, "event": False, "new_project": False}
    for p in parts:
        if not p:
            continue
        out["opportunity_id"] = p.get("opportunity_id") or out["opportunity_id"]
        out["job_ids"] = sorted(set(out["job_ids"]) | set(p.get("job_ids") or []))
        out["plan_horizon"] = p.get("plan_horizon") or out["plan_horizon"]
        out["event"] = out["event"] or bool(p.get("event"))
        out["new_project"] = out["new_project"] or bool(p.get("new_project"))
    return out


def overlap_row(conn, company, opp_id):
    from app.crewly.app_tools import mine_sql
    return conn.execute(mine_sql(company) + " AND op.id = %s", (int(opp_id),)).fetchone()


def overlap_metrics(conn, company, opp_id, scenario, evidence, notes):
    from app.feasibility.assess import assess
    op = overlap_row(conn, company, opp_id)
    out = {}
    if not op:
        out["pairs"] = m(0, COUNT, "overlap still exists")
        notes.append(f"overlap #{opp_id} no longer exists under this scenario")
        return out
    out["pairs"] = m(1, COUNT, "overlap still exists")
    out["overlap_pct"] = m(round(float(op["time_overlap"]) * 100), PCT, "shared build window")
    out["drive_min"] = m(round(float(op["drive_min"]), 1) if op["drive_min"] is not None else None, "min", "drive time between sites")
    sav = savings_for(conn, op, engine.assumption_overrides(scenario) or None)
    out["savings_low"], out["savings_high"] = m(round(sav["low"]), USD, "savings from coordinating (low)"), m(round(sav["high"]), USD, "savings from coordinating (high)")
    def feas():
        f = assess(conn, op["id"], company, refresh=True, quick=True)
        if f:
            out["feasibility_score"] = m(round(float(f["score"]), 2), None, "feasibility score")
            out["verdict"] = m(f["verdict"], None, "feasibility verdict")
            worst = [x for x in f["factors"] if x.get("verdict") == "unlikely"]
            if worst:
                evidence.append("unlikely factors: " + ", ".join(x["factor"] for x in worst))
    engine.guarded(conn, feas, notes, "feasibility")

    def weather():
        cost, coord = hcost.for_zone(conn, op["id"], "window")
        out["weather_cost_low"], out["weather_cost_high"] = m(cost["total"]["low"], USD, "weather cost over the build windows (low)"), m(cost["total"]["high"], USD, "weather cost over the build windows (high)")
        out["coordination_savings_low"] = m(coord["savings"]["low"], USD, "shared standby savings (low)")
        out["coordination_savings_high"] = m(coord["savings"]["high"], USD, "shared standby savings (high)")
        best = ", ".join(x["label"] for x in coord["best_months"][:3])
        if best:
            evidence.append(f"cheapest months to work the pair: {best}")
        exp = exposure.assess(conn, "zone", op["id"], "window")
        if exp:
            out["affected_days_low"] = m(exp["affected_days"]["low"], DAYS, "weather-affected days (low)")
            out["affected_days_high"] = m(exp["affected_days"]["high"], DAYS, "weather-affected days (high)")
            if exp["hazards"]:
                evidence.append(f"lead hazard over the windows: {exp['hazards'][0]['label']}")
    engine.guarded(conn, weather, notes, "weather cost")
    evidence.append(f"#{op['id']}: {op['a_name']} with {op['b_name']}; windows {op['a_start']:%b %Y} to {op['a_end']:%b %Y} and "
                    f"{op['b_start']:%b %Y} to {op['b_end']:%b %Y}; {out['overlap_pct']['value']}% shared")
    return out


def job_metrics(conn, company, job_ids, evidence, notes):
    """Overlaps a set of our projects take part in (a shifted, new or cancelled project)."""
    from app.crewly.app_tools import mine_sql
    ids = [j for j in job_ids]
    rows = conn.execute(mine_sql(company) + " AND (op.job_a = ANY(%s) OR op.job_b = ANY(%s)) ORDER BY op.savings_high DESC", (ids, ids)).fetchall() if ids else []
    out = {"pairs": m(len(rows), COUNT, "overlaps these projects take part in"),
           "savings_low": m(round(sum(float(r["savings_low"]) for r in rows)), USD, "savings across those overlaps (low)"),
           "savings_high": m(round(sum(float(r["savings_high"]) for r in rows)), USD, "savings across those overlaps (high)")}
    partners = sorted({short(partner(r, company)) for r in rows})
    if partners:
        evidence.append("partners: " + ", ".join(partners))
    for r in rows[:5]:
        evidence.append(f"#{r['id']} {short(partner(r, company))}: {r['tier']}, {round(float(r['time_overlap']) * 100)}% shared, "
                        f"${float(r['savings_low']):,.0f} to ${float(r['savings_high']):,.0f}")
    return out


def quarter_of(d):
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def plan_metrics(conn, company, horizon, scenario, evidence, notes):
    plan = planner.build(conn, company, horizon or "quarter")
    items = plan["items"]
    cap = scenario.get("capacity") or {}
    if cap.get("crews_extra"):
        q = str(cap.get("quarter") or "")
        freed = 0
        for it in items:
            if it.get("conflicts") and (not q or quarter_of(engine._d(it["target_start"])) == q):
                it["conflicts"] = []
                freed += 1
        notes.append(f"{cap['crews_extra']} extra crew(s){' in ' + q if q else ''}: {freed} same-project conflict(s) lifted; pairs counted as workable in parallel")
    budget = scenario.get("budget") or {}
    if budget.get("cap_usd"):
        kept, spend = [], 0.0
        for it in sorted(items, key=lambda i: -i["rank"]):
            c = (it.get("project_cost") or {}).get("ours") or 0.0
            if spend + c <= float(budget["cap_usd"]):
                kept.append(it)
                spend += c
        notes.append(f"budget cap ${float(budget['cap_usd']):,.0f} on our project spend keeps {len(kept)} of {len(items)} pairs")
        items = kept
    if budget.get("target_savings_usd"):
        kept, got = [], 0.0
        for it in sorted(items, key=lambda i: -i["rank"]):
            kept.append(it)
            got += it["savings"]["low"]
            if got >= float(budget["target_savings_usd"]):
                break
        notes.append(f"the target of ${float(budget['target_savings_usd']):,.0f} in low-end savings takes {len(kept)} pair(s)" if got >= float(budget["target_savings_usd"])
                     else f"even every pair falls short of ${float(budget['target_savings_usd']):,.0f} in low-end savings")
        items = kept
    sav = {end: round(sum(i["savings"][end] for i in items)) for end in ("low", "high")}
    avoided = {end: round(sum(i["weather"]["avoided"][end] for i in items)) for end in ("low", "high")}
    out = {"plan_pairs": m(len(items), COUNT, "pairs in the plan"),
           "plan_savings_low": m(sav["low"], USD, "plan savings (low)"), "plan_savings_high": m(sav["high"], USD, "plan savings (high)"),
           "weather_avoided_low": m(avoided["low"], USD, "weather cost avoided by the chosen months (low)"),
           "weather_avoided_high": m(avoided["high"], USD, "weather cost avoided by the chosen months (high)"),
           "conflicts": m(sum(1 for i in items if i.get("conflicts")), COUNT, "pairs with a same-project conflict")}
    for it in items[:6]:
        evidence.append(f"#{it['opportunity_id']} {it['partner_short']}: {it['verdict']}, {engine._d(it['target_start']):%b %Y} to "
                        f"{engine._d(it['target_end']):%b %Y}, ${it['savings']['low']:,.0f} to ${it['savings']['high']:,.0f}")
    if plan["totals"].get("note"):
        notes.append(plan["totals"]["note"])
    return out


def event_metrics(conn, company, scenario, scope, evidence, notes):
    """A storm, a past season or a whole year over the jobs in scope, read from the overlay (shifted windows and all)."""
    from app.stormlab import apply_event
    jobs = list(scope.get("job_ids") or [])
    if scope.get("opportunity_id"):
        op = overlap_row(conn, company, scope["opportunity_id"])
        if op:
            jobs = sorted(set(jobs) | {op["job_a"], op["job_b"]})
    if not jobs:  # nothing named: every project of ours still in its build window
        jobs = [r["id"] for r in conn.execute("SELECT id FROM job WHERE org_id = %s AND horizon = 'long' AND upper(work_window) >= now()", (company,)).fetchall()]
    res = apply_event(conn, company, scenario["event"], [{"id": j} for j in jobs]) or {}
    evidence.extend(res.get("evidence") or [])
    notes.extend(res.get("notes") or [])
    return {k: (v if isinstance(v, dict) and "value" in v else m(v)) for k, v in (res.get("metrics") or {}).items()}


def evaluate(conn, company, scenario, scope, applied=None):
    """Every metric group the scope asks for, on the data as it stands in the transaction."""
    t0 = time.perf_counter()
    metrics, evidence, notes = {}, [], []
    touched = [t for t in (applied or {}).get("touched") or []]
    job_ids = sorted(set(scope.get("job_ids") or []) | set(touched))
    if scope.get("opportunity_id"):
        metrics.update(overlap_metrics(conn, company, scope["opportunity_id"], scenario, evidence, notes))
    elif job_ids or scope.get("new_project"):
        metrics.update(job_metrics(conn, company, job_ids, evidence, notes))
    if scope.get("plan_horizon"):
        engine.guarded(conn, lambda: metrics.update(plan_metrics(conn, company, scope["plan_horizon"], scenario, evidence, notes)), notes, "plan")
    if scenario.get("event"):
        def add_event():
            ev = event_metrics(conn, company, scenario, {**scope, "job_ids": job_ids}, evidence, notes)
            metrics.update({(f"event_{k}" if k in metrics else k): v for k, v in ev.items()})  # a storm's savings are not the overlap's savings
        engine.guarded(conn, add_event, notes, "event")
    return {"metrics": metrics, "evidence": evidence, "notes": notes, "ms": round((time.perf_counter() - t0) * 1000)}


def deltas(base, scen):
    """Per shared metric: base, scenario, delta and percent; strings compare without a delta."""
    out = []
    for k, b in base.items():
        s = scen.get(k)
        if s is None:
            continue
        bv, sv = b.get("value"), s.get("value")
        row = {"metric": k, "label": b.get("label") or k, "base": bv, "scenario": sv, "unit": b.get("unit")}
        if isinstance(bv, (int, float)) and isinstance(sv, (int, float)):
            row["delta"] = round(sv - bv, 2)
            row["pct"] = round(100.0 * (sv - bv) / bv, 1) if bv else None
        else:
            row["delta"] = None
        out.append(row)
    return out


def company_label(company):
    return name(company)
