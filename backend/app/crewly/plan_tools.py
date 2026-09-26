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
    return {"status": p["status"], "headline": {k: v for k, v in p["headline"].items() if k != "crews"},
            "separate": p["baseline"], "coordinated": p["coordinated"], "shared_crews": shared,
            "moved_projects": [r["why"] for r in p["schedule"] if r.get("why")][:5]}


def propose_constraints(conn, blackout=None, max_slip=None, crew_count=None, max_advance_months=None):
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
    return _summary(plan.latest(conn)), [{"type": "plan"}]


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
                            "(overall or per project) and crew counts per utility per year.", {
        "blackout": {"type": "object", "properties": {"site": {"type": "string", "description": "part of a project name, or * for all"},
                                                       "months": MONTHS, "phase_kind": {"type": "string", "enum": plan.PHASE_NAMES}}},
        "max_slip": {"type": "object", "properties": {"project": {"type": "string"}, "months": {"type": "integer"}}},
        "crew_count": {"type": "object", "properties": {"org": {"type": "string", "enum": ["desc", "gpc"]}, "year": {"type": "integer"},
                                                         "count": {"type": "integer"}}},
        "max_advance_months": {"type": "integer"}}, []),
    "solve_plan": (solve_plan, "Solve the joint schedule (CP-SAT) with the planner's confirmed constraints and report separate vs "
                   "coordinated results. Only call when the planner asks to solve or has confirmed constraints.", {
        "constraints": {"type": "object", "description": "confirmed constraints; omit to reuse the current ones"}}, []),
    "compare_plans": (compare_plans, "Separate (each utility alone) vs coordinated joint plan: mobilizations, yards, slip, late projects, "
                      "savings range.", {}, []),
    "explain_decision": (explain_decision, "Explain why the joint plan did or did not share a crew or yard for an opportunity or a project "
                         "(by name), and why a project's work moved. Returns the binding rule, numbers and a ready sentence; restate it.", {
        "opportunity_id": {"type": "integer"}, "project": {"type": "string", "description": "part of a project name, e.g. Jasper"}}, []),
}
