"""Crewly's what-if abilities: run an experiment (or a stack of them), do arithmetic it can trust, compare and list findings."""
from app.scenario import calc, experiments


def _bind(ctx, fn):
    return lambda conn, **kw: fn(ctx, conn, **kw)


def _card(f):
    key = [d for d in f["deltas"] if d.get("delta")][:6]
    return {"finding_id": f["id"], "title": f["title"], "kind": f["kind"], "key_deltas": key, "notes": f["notes"][:4], "evidence": f["evidence"][:6],
            "scenario_metrics": {k: v.get("value") for k, v in f["scenario"]["metrics"].items()},
            "base_metrics": {k: v.get("value") for k, v in f["base"]["metrics"].items()}}


def run_experiment(ctx, conn, kind, params=None, question=None):
    f = experiments.run(conn, ctx["company"], kind, params or {}, question)
    return _card(f), [{"type": "finding", "finding": f}]


def calculate(ctx, conn, expression, values=None):
    try:
        return calc.calculate(expression, values or {}), []
    except calc.Unsafe as e:
        return {"error": str(e), "allowed": "numbers, + - * / ^ %, parentheses, and " + ", ".join(sorted(calc.FUNCS))}, []


def compare_findings(ctx, conn, a, b):
    c = experiments.compare(conn, ctx["company"], a, b)
    return c, [{"type": "compare", "compare": c}]


def list_findings(ctx, conn, starred=False):
    return {"findings": experiments.listing(conn, ctx["company"], bool(starred))}, []


PARAMS = ("params by kind: shift_window {opportunity_id, side: ours|theirs, months} or {job_id, months} or {job_id, start, end}; "
          "assumption {name: crew_day_usd, pct: 20} or {name, value} (an overlap via opportunity_id, else the plan); swap_partner {opportunity_id, partner}; "
          "exclude_partner {partner, horizon?, opportunity_id?}; add_project {name, kv, start, end, from: station name or {lon, lat}, to: same}; "
          "cancel_project {opportunity_id, side} or {job_id}; rule {phase, months: [8, 9], where: coast|everywhere, horizon?}; "
          "capacity {crews, quarter: 'Q2', year, horizon?}; budget {cap_usd or target_savings_usd, horizon?}; best_windows {opportunity_id or job_ids}; "
          "storm {place: county or city name or {lon, lat}, date, category, opportunity_id?}; replay_year {year, opportunity_id?}; "
          "sensitivity {opportunity_id, metric?}; compose {changes: [{kind, params}, ...], base_finding_id?} stacks several changes and evaluates once.")


def scenario_tools(ctx):
    return {
        "run_experiment": (_bind(ctx, run_experiment), "Run a what-if on an overlay of the real data (nothing real changes) and return a finding: "
                           "base vs scenario metrics with deltas. Kinds: " + ", ".join(experiments.KINDS) + ". " + PARAMS, {
            "kind": {"type": "string", "enum": list(experiments.KINDS)},
            "params": {"type": "object", "description": "see the kind's params"},
            "question": {"type": "string", "description": "the user's question, in their words"}}, ["kind"]),
        "calculate": (_bind(ctx, calculate), "Exact arithmetic over numbers from earlier tool results: + - * / ^ %, sum, min, max, avg, abs, round, "
                      "sqrt, pct(a, b), pct_change(a, b), mi_km, km_mi. Pass the numbers in values and refer to them by name in the expression.", {
            "expression": {"type": "string", "description": "e.g. 'sum(a, b) * 1.2' or 'pct_change(before, after)'"},
            "values": {"type": "object", "description": "named numbers, e.g. {a: 56700, b: 235500}"}}, ["expression"]),
        "compare_findings": (_bind(ctx, compare_findings), "Shared metrics of two saved findings side by side.", {
            "a": {"type": "integer"}, "b": {"type": "integer"}}, ["a", "b"]),
        "list_findings": (_bind(ctx, list_findings), "Saved findings from earlier experiments, newest first.", {
            "starred": {"type": "boolean"}}, []),
    }


PROMPT = """
- "What if ..." questions are experiments: call run_experiment with the matching kind and params from the user's words (months, partner,
  dates, kV, assumption values, quarter, budget). Several changes at once ("shift ours 3 months AND leave Duke out") are ONE run_experiment
  with kind compose and a changes list, so the effects stack. Answer with the one or two deltas that matter (the finding card carries the
  rest) and say nothing real was changed.
- Scope: when the user names an overlap (#18) or a project, pass opportunity_id or job_id so the experiment measures that pair; use
  horizon only for plan-wide asks ("our plan", "next year"). If a cost change moves nothing, say why (for example no weather days in
  the windows, or the windows already passed) instead of just repeating the numbers.
- Units: shifts are whole months. Turn weeks or days into months (3 weeks is 1 month, 90 days is 3 months, 10 days rounds to 0: say a shift
  under two weeks is too small to model) and say what you rounded to. Shifts stay within 24 months and percent changes within -90% to +500%.
- Storms: a hurricane takes a category 1-5 (clamp and say so when asked for 0 or 7); a tornado is kind storm with category "EF0".."EF5"
  (use EF2 when no rating is given) and is modeled as a narrow wind field where it touches down; other disasters (flood, ice, heat, wildfire)
  are read from the hazard exposure and replay_year tools rather than simulated. on numbers you already have (totals, differences, percent changes, per-mile figures) goes through calculate; never do the
  math yourself. Use compare_findings to put two experiments side by side."""
