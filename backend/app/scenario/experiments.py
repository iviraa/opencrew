"""Experiments: each kind is a change to the Scenario plus what to measure; a stack of changes evaluates once, as a finding."""
import json
from datetime import date, datetime, timezone

from app.companies import name, short
from app.scenario import engine, metrics, normalize

from app.stormlab import EXPERIMENTS as STORMLAB  # storm, replay, sensitivity: findings of their own, composable through the event change

KINDS = ("shift_window", "assumption", "exclude_partner", "add_project", "cancel_project", "rule", "capacity", "budget", "storm", "replay_year",
         "compose", "swap_partner", "best_windows", "sensitivity", "event")  # the chat cards' names; longer aliases in normalize.ALIASES
TABLE_SQL = """
CREATE TABLE IF NOT EXISTS finding (
  id SERIAL PRIMARY KEY, company_id TEXT NOT NULL, title TEXT NOT NULL, kind TEXT NOT NULL, params JSONB NOT NULL DEFAULT '{}',
  result JSONB NOT NULL, starred BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)"""
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _company(q):
    from app.crewly.app_tools import find_company
    who = find_company(q) if q else None
    if not who:
        raise ValueError(f"no utility called {q!r}")
    return who


def _op(conn, company, opp_id):
    op = metrics.overlap_row(conn, company, opp_id)
    if not op:
        raise ValueError(f"overlap #{opp_id} is not one of ours")
    return op


def _sides(op, company):
    ours, theirs = (op["job_a"], op["job_b"]) if op["a_org"] == company else (op["job_b"], op["job_a"])
    return ours, theirs


def _num(v):
    return {"low": float(v), "high": float(v)} if isinstance(v, (int, float)) else {end: float(v[end]) for end in ("low", "high") if end in v}


# ---------- one change per kind: (scenario fragment, scope fragment, knobs, title) ----------

def ch_shift_window(conn, company, p):
    months = p.get("months")
    if months is not None:
        try:
            months = int(round(float(months)))
        except (TypeError, ValueError):
            raise ValueError("months must be a number, e.g. 3 or -6")
        if abs(months) > 24:
            raise ValueError("shifts are limited to 24 months either way")
        p = {**p, "months": months}
    if p.get("opportunity_id"):
        op = _op(conn, company, p["opportunity_id"])
        ours, theirs = _sides(op, company)
        job = theirs if str(p.get("side", "ours")).lower().startswith("their") else ours
        scope = {"opportunity_id": int(op["id"]), "job_ids": [job]}
    else:
        job = p.get("job_id")
        if not job:
            raise ValueError("shift_window needs opportunity_id (with side) or job_id")
        scope = {"job_ids": [job]}
    spec = engine.window_shifted(conn, job, months, p.get("start"), p.get("end"))
    row = conn.execute(engine.JOB_SQL, (job,)).fetchone()
    what = f"{'later' if months and months > 0 else 'earlier'} by {abs(int(months))} month{'' if abs(int(months)) == 1 else 's'}" if months is not None else f"to {spec.get('start', row['start_at'])} to {spec.get('end', row['end_at'])}"
    knobs = [{"name": "months", "type": "month_shift", "value": int(months or 0), "min": -24, "max": 24, "label": f"shift {row['name'][:40]}"}]
    return {"jobs": {job: spec}}, scope, knobs, f"Shift {row['name'][:50]} {what}"


def ch_assumption(conn, company, p):
    over = normalize.assumption_overrides(p)
    if not over:
        raise ValueError("assumption needs name and pct (or value / low, high), e.g. {name: crew_day_usd, pct: 20}")
    scope = {"opportunity_id": int(p["opportunity_id"])} if p.get("opportunity_id") else {"plan_horizon": p.get("horizon") or "quarter"}
    key = next(iter(over))
    if p.get("pct") is not None or p.get("name"):
        knobs = [{"name": "name", "type": "select", "value": key, "options": sorted(engine.ASSUMPTIONS), "label": "assumption"},
                 {"name": "pct", "type": "number", "value": float(p.get("pct") or 0), "min": -90, "max": 300, "label": "change by %"}]
    else:
        knobs = [{"name": k, "type": "number", "value": v.get("high", v.get("low")), "label": k.replace("_", " ")} for k, v in over.items()]
    fmt = lambda x: f"{x:,.0f}" if x >= 100 else f"{x:g}"  # noqa: E731
    what = ", ".join(f"{k.replace('_', ' ')} {fmt(v['low'])}" + (f" to {fmt(v['high'])}" if v.get("high") != v.get("low") else "") for k, v in over.items())
    if p.get("pct") is not None:
        what = f"{key.replace('_', ' ')} {'+' if float(p['pct']) >= 0 else ''}{float(p['pct']):g}%"
    return {"assumptions": over}, scope, knobs, f"Assumptions: {what}"[:120]


def ch_exclude_partner(conn, company, p):
    who = _company(p.get("partner"))
    scope = {"plan_horizon": p.get("horizon") or "quarter"}
    if p.get("opportunity_id"):
        scope["opportunity_id"] = int(p["opportunity_id"])
    knobs = [{"name": "partner", "type": "select", "value": who, "options": sorted(c for c in _partners(conn, company)), "label": "partner left out"}]
    return {"exclude_partners": [who]}, scope, knobs, f"Without {name(who)}"


def _partners(conn, company):
    from app.crewly.app_tools import mine_sql
    rows = conn.execute(mine_sql(company)).fetchall()
    return {(r["b_org"] if r["a_org"] == company else r["a_org"]) for r in rows}


def ch_add_project(conn, company, p):
    coords, ends = list(p.get("coords") or []), list(p.get("ends") or [])
    for key in ("from", "to"):
        lon, lat, label = normalize.place_of(p.get(key))
        if lon is not None:
            coords.append([lon, lat])
        elif label:
            ends.append(label)
    spec = {"org_id": company, "name": p.get("name") or "Hypothetical project", "kv": p.get("kv"), "start": p.get("start") or None,
            "end": p.get("end") or None, "in_service": p.get("in_service") or p.get("end") or None, "ends": ends or None, "coords": coords or None, "state": p.get("state")}
    knobs = [{"name": "kv", "type": "select", "value": spec["kv"], "options": [115, 138, 161, 230, 345, 500], "label": "kV"},
             {"name": "from", "type": "place", "value": p.get("from"), "label": "from"}, {"name": "to", "type": "place", "value": p.get("to"), "label": "to"},
             {"name": "start", "type": "date", "value": spec["start"], "label": "start"}, {"name": "end", "type": "date", "value": spec["in_service"], "label": "in service"}]
    return {"new_jobs": [spec]}, {"new_project": True}, knobs, f"Add {spec['name'][:50]}"


def ch_cancel_project(conn, company, p):
    job = p.get("job_id")
    if not job and p.get("opportunity_id"):
        op = _op(conn, company, p["opportunity_id"])
        ours, theirs = _sides(op, company)
        job = theirs if str(p.get("side", "ours")).lower().startswith("their") else ours
    row = conn.execute(engine.JOB_SQL, (job,)).fetchone() if job else None
    if not row:
        raise ValueError(f"no project {job!r}")
    knobs = [{"name": "side", "type": "select", "value": p.get("side", "ours"), "options": ["ours", "theirs"], "label": "which project"}] if p.get("opportunity_id") else []
    scope = {"plan_horizon": p.get("horizon") or "quarter", "job_ids": [job]}
    if p.get("opportunity_id"):
        scope["opportunity_id"] = int(p["opportunity_id"])
    return {"jobs": {job: {"cancelled": True}}}, scope, knobs, f"Cancel {row['name'][:50]}"


COASTAL = {"TX", "LA", "MS", "AL", "FL", "GA", "SC", "NC", "VA", "MD", "DE", "NJ", "NY", "CT", "RI", "MA", "NH", "ME", "CA", "OR", "WA"}


def ch_rule(conn, company, p):
    months = [int(x) for x in (p.get("months") or p.get("blackout_months") or []) if 1 <= int(x) <= 12]
    if not months:
        raise ValueError("rule needs months (1-12) to keep work out of")
    where = str(p.get("where") or "everywhere").lower()
    phase = str(p.get("phase") or "all work")
    bl = {}
    if p.get("job_id"):
        bl[p["job_id"]] = months
    elif where == "coast":
        rows = conn.execute("SELECT id FROM job WHERE org_id = %s AND horizon = 'long' AND state = ANY(%s)", (company, sorted(COASTAL))).fetchall()
        for r in rows:
            bl[r["id"]] = months
        if not rows:
            bl["*"] = months
    else:
        bl["*"] = months
    knobs = [{"name": "phase", "type": "select", "value": phase, "options": ["stringing", "crane lifts", "clearing", "all work"], "label": "no"},
             {"name": "months", "type": "months", "value": months, "label": "in"},
             {"name": "where", "type": "select", "value": where, "options": ["coast", "everywhere"], "label": "where"}]
    label = "our coastal projects" if where == "coast" and not p.get("job_id") else p.get("job_id") or "any of our projects"
    return ({"constraints": {"blackout_months": bl}}, {"plan_horizon": p.get("horizon") or "quarter"}, knobs,
            f"Rule: no {phase} in {', '.join(MONTHS[m - 1] for m in months)} at {label}")


def ch_capacity(conn, company, p):
    n = int(p.get("crews") if p.get("crews") is not None else p.get("crews_extra") or 1)
    q = normalize.quarter_of(p)
    year = p.get("year") or (int(q[:4]) if q else date.today().year + 1)
    knobs = [{"name": "crews", "type": "number", "value": n, "min": -3, "max": 5, "label": "extra crews"},
             {"name": "quarter", "type": "select", "value": q[-2:] if q else "Q2", "options": list(normalize.QUARTERS), "label": "quarter"},
             {"name": "year", "type": "number", "value": int(year), "label": "year"}]
    return {"capacity": {"crews_extra": n, "quarter": q}}, {"plan_horizon": p.get("horizon") or "year"}, knobs, f"{n} extra crew(s){' in ' + q if q else ''}"


def ch_budget(conn, company, p):
    b = {}
    if float(p.get("cap_usd") or 0) > 0:
        b["cap_usd"] = float(p["cap_usd"])
    if float(p.get("target_savings_usd") or 0) > 0:
        b["target_savings_usd"] = float(p["target_savings_usd"])
    if not b:
        raise ValueError("budget needs cap_usd or target_savings_usd")
    knobs = [{"name": k, "type": "number", "value": v, "label": k.replace("_", " ")} for k, v in b.items()]
    what = " and ".join(f"cap ${v:,.0f}" if k == "cap_usd" else f"target ${v:,.0f} savings" for k, v in b.items())
    return {"budget": b}, {"plan_horizon": p.get("horizon") or "year"}, knobs, f"Budget: {what}"


def ch_storm(conn, company, p):
    ev = normalize.storm_event(p)
    if ev["kind"] == "storm" and ev.get("lon") is None:
        from app.stormlab.storm import locate
        ev["lon"], ev["lat"], ev["place"] = locate(ev["place"], ev.get("state"))  # the storm lab's own place lookup
    scope = {"event": True, "job_ids": list(p.get("job_ids") or [])}
    if p.get("opportunity_id"):
        scope["opportunity_id"] = int(p["opportunity_id"])
    place = {"lon": ev["lon"], "lat": ev["lat"]} if ev.get("lon") is not None else None
    knobs = [{"name": "place", "type": "place", "value": place, "label": "landfall"},
             {"name": "category", "type": "select", "value": ev.get("category", 3), "options": [1, 2, 3, 4, 5], "label": "category"},
             {"name": "date", "type": "date", "value": ev.get("date"), "label": "date"},
             {"name": "radius_km", "type": "number", "value": ev.get("radius_km", 80), "min": 10, "max": 400, "label": "radius km"}]
    what = ev.get("name") or ev.get("place") or (f"{ev['lat']:.2f}, {ev['lon']:.2f}" if place else "storm")
    return {"event": ev}, scope, knobs, f"Storm: category {ev.get('category', 3)} at {what}"


def ch_replay_year(conn, company, p):
    year = int(p.get("year") or 0)
    if not 2000 <= year <= date.today().year:
        raise ValueError("replay_year needs a year with weather history, e.g. 2018")
    ev = {"kind": "year", "year": year}
    if p.get("hazards"):
        ev["hazards"] = list(p["hazards"])
    scope = {"event": True, "job_ids": list(p.get("job_ids") or [])}
    if p.get("opportunity_id"):
        scope["opportunity_id"] = int(p["opportunity_id"])
    knobs = [{"name": "year", "type": "select", "value": year, "options": list(range(2016, 2026)), "label": "weather of"}]
    return {"event": ev}, scope, knobs, f"Weather of {year}"


def ch_event(conn, company, p):
    ev = p.get("event") or {k: v for k, v in p.items() if k not in ("opportunity_id", "job_ids", "horizon")}
    kind = ev.get("kind")
    if kind == "storm":
        return ch_storm(conn, company, {**ev, **{k: p[k] for k in ("opportunity_id", "job_ids") if k in p}})
    if kind == "year":
        return ch_replay_year(conn, company, {**ev, **{k: p[k] for k in ("opportunity_id", "job_ids") if k in p}})
    if kind == "historical":
        scope = {"event": True, "job_ids": list(p.get("job_ids") or [])}
        if p.get("opportunity_id"):
            scope["opportunity_id"] = int(p["opportunity_id"])
        return {"event": {"kind": "historical", "name": ev.get("name", "helene")}}, scope, [], f"Event: {ev.get('name', 'helene')}"
    raise ValueError("event needs kind: storm, historical or year")


CHANGES = {"shift_window": ch_shift_window, "assumption": ch_assumption, "exclude_partner": ch_exclude_partner, "add_project": ch_add_project,
           "cancel_project": ch_cancel_project, "rule": ch_rule, "capacity": ch_capacity, "budget": ch_budget, "storm": ch_storm,
           "replay_year": ch_replay_year, "event": ch_event}


# ---------- stacks ----------

def stack(conn, company, changes, base=None):
    """Merge every change into one Scenario and one scope; knobs inside a stack are named by their place in it."""
    scenario, scopes, knobs, titles, clean = engine.merge(engine.EMPTY, base), [], [], [], []
    for i, c in enumerate(changes):
        kind = normalize.kind_of(c.get("kind"))
        if kind not in CHANGES:
            raise ValueError(f"{kind} cannot be stacked; use it on its own")
        params = normalize.resolve(c.get("params") or {})
        frag, scope, kn, title = CHANGES[kind](conn, company, params)
        scenario = engine.merge(scenario, frag)
        scopes.append(scope)
        knobs.extend([{**k, "name": f"changes.{i}.{k['name']}"} for k in kn] if len(changes) > 1 else kn)
        titles.append(title)
        clean.append({"kind": kind, "params": params})
    return scenario, metrics.scope_of(*scopes), knobs, titles, clean


def finding(conn, company, kind, params, title, question, base, result, scenario, knobs, notes_extra=(), stack_changes=None):
    conn.execute(TABLE_SQL)
    F = {"title": title, "question": question, "kind": kind, "params": {**params, **({"changes": stack_changes} if stack_changes else {})},
         "scenario": {"metrics": result["metrics"], "overlay": scenario}, "base": {"metrics": base["metrics"]},
         "deltas": metrics.deltas(base["metrics"], result["metrics"]),
         "notes": [*notes_extra, *result["notes"]], "evidence": result["evidence"], "base_evidence": base["evidence"], "knobs": knobs,
         "sources": ["planner data as filed", "engine.cost savings model", "hazards climatology and cost", "feasibility assessment"],
         "timing_ms": {"base": base["ms"], "scenario": result["ms"]}}
    row = conn.execute("INSERT INTO finding (company_id, title, kind, params, result) VALUES (%s, %s, %s, %s, %s) RETURNING id, created_at",
                       (company, title, kind, json.dumps(F["params"], default=str), json.dumps(F, default=str))).fetchone()
    F["id"], F["created_at"], F["company_id"] = row["id"], row["created_at"].isoformat(), company
    conn.execute("UPDATE finding SET result = %s WHERE id = %s", (json.dumps(F, default=str), row["id"]))
    return F


def run_stack(conn, company, kind, params, changes, question=None, base_finding_id=None):
    base_scenario = None
    if base_finding_id:
        prev = get(conn, int(base_finding_id), company)
        if not prev:
            raise ValueError(f"no finding {base_finding_id}")
        base_scenario = (prev.get("scenario") or {}).get("overlay")
    scenario, scope, knobs, titles, clean = stack(conn, company, changes, base_scenario)
    if not any(scope.values()):
        raise ValueError("nothing to measure: give an overlap, a project or a horizon")
    base, result, applied = engine.run(conn, company, scenario, lambda c, sc, ap: metrics.evaluate(c, company, sc, scope, ap), base_scenario)
    notes = [f"{len(changes)} change(s) applied: " + "; ".join(titles)] if len(changes) > 1 else []
    notes += [f"deltas are against finding #{base_finding_id}" if base_finding_id else "deltas are against the untouched base"]
    notes += applied.get("notes", [])
    bp, sp = (base.get("plan_pairs") or {}).get("value"), (result.get("plan_pairs") or {}).get("value")
    if bp is not None and sp is not None and sp > bp:  # the plan refilled freed slots, so plan totals are not like for like
        notes.append(f"the plan grew from {bp} to {sp} pairs (freed slots were refilled, or the horizon widened), so plan totals compare a different set of pairs")
    title = " + ".join(titles) if len(titles) <= 3 else f"{titles[0]} + {len(titles) - 1} more"
    kept = {**clean[0]["params"], **{k: v for k, v in params.items() if k in ("horizon", "job_ids")}} if kind != "compose" else {**params, "changes": clean}
    return finding(conn, company, kind, kept, title[:140], question or title, base, result, scenario, knobs, notes)


def run(conn, company, kind, params, question=None):
    """Any single kind is a one-change stack; compose is the general case; the rest are comparisons or the storm lab's own findings."""
    kind = normalize.kind_of(kind)
    params = normalize.resolve(params or {})
    if kind == "compose":
        return run_stack(conn, company, kind, params, list(params.get("changes") or []), question, params.get("base_finding_id"))
    if kind == "sensitivity":
        return STORMLAB["sensitivity"](conn, company, params)
    if kind == "swap_partner":
        return swap_partner(conn, company, params, question)
    if kind == "best_windows":
        return best_windows(conn, company, params, question)
    if kind == "storm" and not params.get("opportunity_id") and not params.get("job_ids"):  # the storm lab's own wider finding over every site in reach
        ev = normalize.storm_event(params)
        f = STORMLAB["storm"](conn, company, {**params, **({"lon": ev["lon"], "lat": ev["lat"]} if ev.get("lon") is not None else {}),
                                              "place": ev.get("place"), "category": ev.get("category"), "date": ev.get("date")})  # a {lon, lat} place has no name
        return _as_card_kind(conn, company, f, "storm", params)
    if kind == "replay_year" and not params.get("opportunity_id") and not params.get("job_ids"):
        f = STORMLAB["replay"](conn, company, {"opportunity_ids": params.get("opportunity_ids") or [], "job_ids": [], "plan_id": params.get("plan_id"),
                                               "years": [int(params["year"])] if params.get("year") else None, "hazards": params.get("hazards")})
        return _as_card_kind(conn, company, f, "replay_year", params)
    return run_stack(conn, company, kind, params, [{"kind": kind, "params": params}], question, params.get("base_finding_id"))


def _as_card_kind(conn, company, f, kind, params):
    """A storm lab finding re-labelled with the card's kind and params, so a knob re-run comes back the same way."""
    f = dict(f)
    f["kind"], f["params"] = kind, {**params, **{k: v for k, v in (f.get("params") or {}).items() if k not in params}}
    if kind == "storm":
        ev = normalize.storm_event({**f["params"]})
        f["params"]["place"] = {"lon": ev["lon"], "lat": ev["lat"]} if ev.get("lon") is not None else f["params"].get("place")
        f["params"].setdefault("radius_km", 80)
        f["knobs"] = [{"name": "place", "type": "place", "value": f["params"]["place"], "label": "landfall"},
                      {"name": "category", "type": "select", "value": f["params"].get("category", 3), "options": [1, 2, 3, 4, 5], "label": "category"},
                      {"name": "date", "type": "date", "value": str(f["params"].get("date") or "")[:10], "label": "date"},
                      {"name": "radius_km", "type": "number", "value": f["params"]["radius_km"], "min": 10, "max": 400, "label": "radius km"}]
    else:
        f["knobs"] = [{"name": "year", "type": "select", "value": params.get("year"), "options": list(range(2016, 2026)), "label": "weather of"}]
    if f.get("id"):
        conn.execute("UPDATE finding SET kind = %s, params = %s, result = %s WHERE id = %s AND company_id = %s",
                     (kind, json.dumps(f["params"], default=str), json.dumps(f, default=str), f["id"], company))
    return f


def swap_partner(conn, company, p, question):
    """The same project with a different neighbor: base is the given overlap, scenario the best overlap with the other partner."""
    op = _op(conn, company, p["opportunity_id"])
    who = _company(p.get("partner"))
    ours, _ = _sides(op, company)
    from app.crewly.app_tools import mine_sql
    alt = conn.execute(mine_sql(company) + " AND (op.job_a = %s OR op.job_b = %s) AND (ja.org_id = %s OR jb.org_id = %s) ORDER BY op.savings_high DESC LIMIT 1",
                       (ours, ours, who, who)).fetchone()
    knobs = [{"name": "partner", "type": "select", "value": who, "options": sorted(_partners(conn, company)), "label": "partner instead"}]
    if not alt:
        base = engine.run(conn, company, engine.EMPTY, lambda c, sc, ap: metrics.evaluate(c, company, sc, {"opportunity_id": int(op["id"])}, ap))[0]
        result = {"metrics": {"pairs": metrics.m(0, "count", "overlap with that partner")}, "evidence": [], "notes": [f"{name(who)} has no overlap with this project"], "ms": 0}
        return finding(conn, company, "swap_partner", p, f"Swap partner on #{op['id']} to {short(who)}", question or "swap partner", base, result, engine.EMPTY, knobs)
    base, result, _ = engine.run(conn, company, engine.EMPTY, lambda c, sc, ap: metrics.evaluate(c, company, sc, {"opportunity_id": int(op["id"])}, ap))
    _, alt_res, _ = engine.run(conn, company, engine.EMPTY, lambda c, sc, ap: metrics.evaluate(c, company, sc, {"opportunity_id": int(alt["id"])}, ap))
    alt_res["notes"].insert(0, f"scenario is overlap #{alt['id']} with {name(who)}; base is #{op['id']}")
    return finding(conn, company, "swap_partner", p, f"#{op['id']} vs #{alt['id']} with {short(who)}", question or "swap partner", base, alt_res, engine.EMPTY, knobs)


def best_windows(conn, company, p, question):
    """Coordinated windows from the CP-SAT joint scheduler for a few projects, inside the overlay so nothing is stored."""
    from app.engine import plan
    ids = list(p.get("job_ids") or [])
    if p.get("opportunity_id"):
        op = _op(conn, company, p["opportunity_id"])
        ids = sorted(set(ids) | {op["job_a"], op["job_b"]})
    if not ids:
        raise ValueError("best_windows needs job_ids or an opportunity_id")
    conn.execute("SAVEPOINT what_if")
    evidence, notes, out = [], [], {}
    try:
        n = conn.execute("SELECT count(DISTINCT j) AS n FROM opportunity, unnest(ARRAY[job_a, job_b]) AS j WHERE horizon = 'long' AND (job_a = ANY(%s) OR job_b = ANY(%s))", (ids, ids)).fetchone()["n"]
        if n > 30:
            notes.append(f"{n} projects touch these; too many for the solver in a chat turn, narrow the set")
        else:
            conn.execute("DELETE FROM opportunity WHERE horizon = 'long' AND NOT (job_a = ANY(%s) OR job_b = ANY(%s))", (ids, ids))
            res = plan.run(conn, {"force": True, "time_limit_s": 4})
            if res.get("status") == "infeasible":
                notes.append(f"solver: {res.get('problem')}")
            else:
                head = res.get("headline") or {}
                for k in ("separate", "coordinated"):
                    v = head.get(k) if isinstance(head.get(k), dict) else None
                    if v and "cost_k" in v:
                        out[f"solver_{k}_cost_k"] = metrics.m(v["cost_k"], "$k", f"{k} plan cost (solver)")
                for r in res.get("schedule") or []:
                    if r["job_id"] in ids:
                        evidence.append(f"{r['name'][:45]}: {r['phases'][0]['start'][:7] if r.get('phases') else r.get('filed_start', '')[:7]} to "
                                        f"{r['phases'][-1]['end'][:7] if r.get('phases') else r.get('filed_end', '')[:7]}, slip {r.get('slip', 0)} mo, crew {r.get('crew')}")
                out["solver_status"] = metrics.m(res.get("status"), None, "solver status")
                notes.append("windows from the joint scheduler with a 4 s solve limit; not stored")
    finally:
        conn.execute("ROLLBACK TO SAVEPOINT what_if")
        conn.execute("RELEASE SAVEPOINT what_if")
    base = {"metrics": {}, "evidence": [], "notes": [], "ms": 0}
    result = {"metrics": out, "evidence": evidence, "notes": notes, "ms": 0}
    return finding(conn, company, "best_windows", p, f"Best windows for {len(ids)} project(s)", question or "best windows", base, result, engine.EMPTY, [])


# ---------- store ----------

def get(conn, finding_id, company):
    conn.execute(TABLE_SQL)
    row = conn.execute("SELECT result, starred FROM finding WHERE id = %s AND company_id = %s", (finding_id, company)).fetchone()
    if not row:
        return None
    return {**row["result"], "starred": row["starred"]}


def listing(conn, company, starred=False, limit=30):
    conn.execute(TABLE_SQL)
    rows = conn.execute("SELECT id, title, kind, starred, created_at, result->'deltas' AS deltas FROM finding WHERE company_id = %s"
                        + (" AND starred" if starred else "") + " ORDER BY id DESC LIMIT %s", (company, limit)).fetchall()
    return [{"id": r["id"], "title": r["title"], "kind": r["kind"], "starred": r["starred"], "created_at": r["created_at"].isoformat(),
             "headline": next((d for d in (r["deltas"] or []) if d.get("delta")), None)} for r in rows]


def star(conn, finding_id, company, on=True):
    conn.execute("UPDATE finding SET starred = %s WHERE id = %s AND company_id = %s", (on, finding_id, company))
    return get(conn, finding_id, company)


def delete(conn, finding_id, company):
    return conn.execute("DELETE FROM finding WHERE id = %s AND company_id = %s", (finding_id, company)).rowcount


def compare(conn, company, a_id, b_id):
    """Shared metrics of any two findings, scenario side against scenario side."""
    a, b = get(conn, int(a_id), company), get(conn, int(b_id), company)
    if not a or not b:
        raise ValueError("both findings must be ours")
    return {"a": {"id": a["id"], "title": a["title"], "kind": a["kind"]}, "b": {"id": b["id"], "title": b["title"], "kind": b["kind"]},
            "title": f"{a['title'][:50]} vs {b['title'][:50]}", "deltas": metrics.deltas(a["scenario"]["metrics"], b["scenario"]["metrics"]),
            "compared_at": datetime.now(timezone.utc).isoformat()}
