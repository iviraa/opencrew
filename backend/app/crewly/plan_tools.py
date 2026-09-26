import copy

from app.engine import plan


def _current(conn):
    conn.execute(plan.TABLE_SQL)
    row = conn.execute("SELECT constraints FROM joint_plan ORDER BY id DESC LIMIT 1").fetchone()
    return copy.deepcopy(row["constraints"]) if row else {}


def _summary(p):
    if p.get("status") in ("infeasible", "empty"):
        return {"status": p["status"], "problem": p.get("problem")}
    shared = [d["sentence"] for d in p["decisions"] if d["decision"] == "share"][:5]
    h = p["headline"]
    jc = h.get("joint_contracting")
    return {"status": p["status"], "solver": h.get("solver"),
            "strict_headline": {k: v for k, v in h.items() if k not in ("crews", "joint_contracting", "solver")},
            "joint_contracting_headline": jc or "off (turn it on to see its separate headline; it assumes one contractor serves both utilities)",
            "separate": p["baseline"], "coordinated": p["coordinated"], "shared_resources": shared,
            "moved_projects": [r["why"] for r in p["schedule"] if r.get("why")][:5]}


def propose_constraints(conn, blackout=None, max_slip=None, crew_count=None, max_advance_months=None, burst=None,
                        burst_gap_weeks=None, joint_contracting=None):
    c = _current(conn)
    changes = []
    if blackout:
        c.setdefault("blackouts", []).append({"site": blackout.get("site", "*"), "months": blackout.get("months", []),
                                               "phase_kind": blackout.get("phase_kind", "energization")})
    if max_slip:
        if max_slip.get("project"):
            c.setdefault("slip_overrides", {})[max_slip["project"]] = int(max_slip["months"])
        else:
            c["max_slip_months"] = int(max_slip["months"])
    if crew_count:
        c.setdefault("crew_counts", {}).setdefault(crew_count["org"], {})[str(crew_count["year"])] = int(crew_count["count"])
    if max_advance_months is not None:
        c["max_advance_months"] = int(max_advance_months)
    if burst:  # specialty assumptions: duration, typical window (% of the phase), cost per mobilization
        spec = {k: burst[k] for k in ("weeks", "mob_low_k", "mob_high_k", "enabled") if burst.get(k) is not None}
        if burst.get("window_start_pct") is not None or burst.get("window_end_pct") is not None:
            cur = plan.merge(c)["bursts"].get(burst.get("type"), {}).get("window", [0, 1])
            spec["window"] = [burst.get("window_start_pct", cur[0] * 100) / 100, burst.get("window_end_pct", cur[1] * 100) / 100]
        c.setdefault("bursts", {}).setdefault(burst.get("type"), {}).update(spec)
    if burst_gap_weeks is not None:
        c["burst_gap_weeks"] = int(burst_gap_weeks)
    if joint_contracting is not None:
        c["joint_contracting"] = bool(joint_contracting)
    checked = plan.validate(conn, c)
    changes = checked["notes"]
    out = {"proposed": checked["constraints"], "rules": changes, "errors": checked["errors"],
           "note": "Not solved yet. The planner confirms or discards these in the Joint plan view."}
    return out, ([] if checked["errors"] else [{"type": "pending_constraints", "constraints": checked["constraints"], "rules": changes}])


def solve_plan(conn, constraints=None):
    checked = plan.validate(conn, constraints if constraints is not None else _current(conn))
    if not checked["valid"]:
        return {"errors": checked["errors"]}, []
    return _summary(plan.run(conn, checked["constraints"])), [{"type": "plan"}]


def compare_plans(conn):
    return _summary(plan.latest(conn)), [{"type": "plan"}]  # strict headline plus the joint contracting one when it is on


def explain_decision(conn, opportunity_id=None, project=None):
    e = plan.explain(conn, opportunity_id, project)
    if e.get("status") in ("infeasible", "empty"):
        return {"problem": e.get("problem")}, [{"type": "plan"}]
    if not e["decisions"] and not e["projects"]:
        return {"error": "nothing in the joint plan matches; try a project name from search_projects"}, []
    out = [{"opportunity_id": d["opportunity_id"], "projects": f"{d['a']} / {d['b']}", "decision": d["decision"],
            "explanation": d["sentence"], "reasons": d["reasons"]} for d in e["decisions"][:6]]
    one = len(out) == 1
    actions = [{"type": "select", "horizon": "long", "opportunity_id": out[0]["opportunity_id"]}] if one else [{"type": "plan"}]
    return {"constraints": e["constraints"], "pairs": out, "projects": e["projects"][:4]}, actions


MONTHS = {"type": "array", "items": {"type": "integer"}, "description": "calendar months 1-12"}
PLAN_TOOLS = {
    "propose_constraints": (propose_constraints, "Turn a planner's rule into structured joint-plan constraints for them to CONFIRM in the UI. "
                            "Does not solve. Use for blackouts (no energization/outage work at a site in some months), slip limits "
                            "(overall or per project), crew counts per utility per year, specialty burst assumptions (heavy haul, "
                            "crane lift, wire stringing, commissioning: weeks, window, cost), the burst gap, and the joint contracting toggle.", {
        "blackout": {"type": "object", "properties": {"site": {"type": "string", "description": "part of a project name, or * for all"},
                                                       "months": MONTHS, "phase_kind": {"type": "string", "enum": plan.PHASE_NAMES}}},
        "max_slip": {"type": "object", "properties": {"project": {"type": "string"}, "months": {"type": "integer"}}},
        "crew_count": {"type": "object", "properties": {"org": {"type": "string", "enum": ["desc", "gpc"]}, "year": {"type": "integer"},
                                                         "count": {"type": "integer"}}},
        "max_advance_months": {"type": "integer"},
        "burst": {"type": "object", "description": "change a specialty assumption", "properties": {
            "type": {"type": "string", "enum": list(plan.BURSTS)}, "weeks": {"type": "integer"},
            "window_start_pct": {"type": "number"}, "window_end_pct": {"type": "number"},
            "mob_low_k": {"type": "number"}, "mob_high_k": {"type": "number"}, "enabled": {"type": "boolean"}}},
        "burst_gap_weeks": {"type": "integer", "description": "longest a shared specialty crew may wait between two jobs"},
        "joint_contracting": {"type": "boolean", "description": "assumption: one contractor serves both utilities' concurrent jobs"}}, []),
    "solve_plan": (solve_plan, "Solve the joint schedule (CP-SAT) with the planner's confirmed constraints and report separate vs "
                   "coordinated results. Only call when the planner asks to solve or has confirmed constraints.", {
        "constraints": {"type": "object", "description": "confirmed constraints; omit to reuse the current ones"}}, []),
    "compare_plans": (compare_plans, "Separate (each utility alone) vs coordinated joint plan: the strict headline (specialty crews and "
                      "yards shared, general crews stay with their utility) and, when turned on, the joint contracting headline, which is "
                      "an assumption. Mobilizations by type, yards, slip, late projects, savings ranges, solver status.", {}, []),
    "explain_decision": (explain_decision, "Explain why the joint plan did or did not share a specialty crew (crane, stringing crew, "
                         "heavy-haul rig, commissioning team) or yard for an opportunity or a project "
                         "(by name), and why a project's work moved. Returns the binding rule, numbers and a ready sentence; restate it.", {
        "opportunity_id": {"type": "integer"}, "project": {"type": "string", "description": "part of a project name, e.g. Jasper"}}, []),
}
