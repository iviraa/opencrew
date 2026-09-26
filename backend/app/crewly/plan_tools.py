from app.engine import plan


def run_crew_plan(conn, max_delay_months=None, max_drive_min=None, min_overlap_months=None):
    p = plan.run(conn, {"max_delay_months": max_delay_months, "max_drive_min": max_drive_min, "min_overlap_months": min_overlap_months})
    shared = [{"opportunity_id": d["opportunity_id"], "projects": f"{d['a']} / {d['b']}", "why": d["sentence"]}
              for d in p["decisions"] if d["decision"] == "share"]
    return {"limits": p["limits"], "summary": p["summary"], "shared": shared[:10]}, [{"type": "plan"}]


def explain_decision(conn, opportunity_id=None, project=None):
    e = plan.explain(conn, opportunity_id, project)
    if not e["decisions"]:
        return {"error": "no crew-plan decision matches; try a project name from search_projects"}, []
    out = [{"opportunity_id": d["opportunity_id"], "projects": f"{d['a']} / {d['b']}", "decision": d["decision"],
            "explanation": d["sentence"], "reasons": d["reasons"], "shift": d["shift"], "drive_min": d["drive_min"]}
           for d in e["decisions"][:8]]
    one = len(out) == 1
    actions = [{"type": "select", "horizon": "long", "opportunity_id": out[0]["opportunity_id"]}] if one else [{"type": "plan"}]
    return {"limits": e["limits"], "matches": len(e["decisions"]), "decisions": out}, actions


PLAN_TOOLS = {
    "run_crew_plan": (run_crew_plan, "Run the crew-sharing optimizer with planner limits (max delay to any project, max road minutes "
                      "between sites, minimum months of overlapping construction). Each project shares its crew with at most one partner. "
                      "Opens the Crew plan view.", {
        "max_delay_months": {"type": "integer"}, "max_drive_min": {"type": "integer"}, "min_overlap_months": {"type": "integer"}}, []),
    "explain_decision": (explain_decision, "Explain why the crew-sharing optimizer did or did not share crews for an opportunity or a "
                         "project (by name). Returns the exact rule, numbers and a ready sentence; restate it, do not recompute.", {
        "opportunity_id": {"type": "integer"}, "project": {"type": "string", "description": "part of a project name, e.g. Jasper"}}, []),
}
