import copy
import json
from datetime import date

from dateutil.relativedelta import relativedelta
from ortools.sat.python import cp_model

from app.config import ASSUMPTIONS, PHASES

DEFAULTS = {
    "max_slip_months": 6, "slip_overrides": {}, "max_advance_months": 6, "crew_counts": {}, "blackouts": [],
    "chain_gap_months": 2, "crew_drive_min": 45, "crew_km": 40, "yard_km": 8, "time_limit_s": 10,
    "costs": {"mobilization_k": 100, "yard_k": 275, "idle_k_per_month": 30, "slip_k_per_month": 50, "advance_k_per_month": 5},
}
PHASE_NAMES = [p for p, _ in PHASES]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
RELAXED_SLIP = 120  # months allowed in a counterfactual so we can measure how far a project must move

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS joint_plan (
  id           SERIAL PRIMARY KEY,
  run_at       TIMESTAMPTZ DEFAULT now(),
  constraints  JSONB NOT NULL,
  job_ids      TEXT[] NOT NULL,
  status       TEXT NOT NULL,
  baseline     JSONB,
  coordinated  JSONB,
  headline     JSONB,
  schedule     JSONB,
  decisions    JSONB,
  problem      TEXT
)
"""

JOBS_SQL = """
WITH ids AS (SELECT DISTINCT unnest(ARRAY[job_a, job_b]) AS id FROM opportunity WHERE horizon = 'long')
SELECT j.id, j.org_id, j.name, lower(j.work_window)::date AS start_at, j.in_service
FROM job j JOIN ids USING (id) ORDER BY j.id
"""

PAIRS_SQL = """
SELECT a.id AS a, b.id AS b, ST_Distance(a.geom, b.geom) / 1000 AS km FROM job a JOIN job b ON a.id < b.id
WHERE a.id = ANY(%(ids)s) AND b.id = ANY(%(ids)s)
"""

OPPS_SQL = """
SELECT op.id, op.job_a, op.job_b, op.drive_min FROM opportunity op WHERE op.horizon = 'long' ORDER BY op.id
"""

SITES_SQL = """
WITH sites AS (
  SELECT 'job:' || id AS id, 'at ' || name AS label, ST_Centroid(geom::geometry)::geography AS g FROM job WHERE id = ANY(%(ids)s)
  UNION ALL
  SELECT 'opp:' || id, 'between the projects of pair #' || id, ST_Centroid(link::geometry)::geography FROM opportunity WHERE horizon = 'long'
)
SELECT s.id AS site, s.label, ST_X(s.g::geometry) AS lon, ST_Y(s.g::geometry) AS lat, j.id AS job
FROM sites s JOIN job j ON j.id = ANY(%(ids)s) AND ST_DWithin(s.g, j.geom, %(m)s)
"""


# ---------- inputs ----------

def merge(constraints):
    c = copy.deepcopy(DEFAULTS)
    for k, v in (constraints or {}).items():
        if k == "costs" and isinstance(v, dict):
            c["costs"].update({kk: float(vv) for kk, vv in v.items() if kk in c["costs"]})
        elif k in c and v is not None:
            c[k] = v
    for k in ("max_slip_months", "max_advance_months", "chain_gap_months"):
        c[k] = int(c[k])
    return c


def load(conn, yard_km):
    jobs = conn.execute(JOBS_SQL).fetchall()
    ids = [j["id"] for j in jobs]
    opps = conn.execute(OPPS_SQL).fetchall()
    pairs = conn.execute(PAIRS_SQL, {"ids": ids}).fetchall()
    sites, near = {}, {}
    for r in conn.execute(SITES_SQL, {"ids": ids, "m": yard_km * 1000}).fetchall():
        sites.setdefault(r["site"], {"id": r["site"], "label": r["label"], "lon": r["lon"], "lat": r["lat"]})
        near.setdefault(r["job"], set()).add(r["site"])
    return {"jobs": jobs, "opps": opps, "pairs": pairs, "sites": sites, "near": {k: sorted(v) for k, v in near.items()}}


def month_index(origin, d):
    return (d.year - origin.year) * 12 + d.month - origin.month


def month_date(origin, m):
    return origin + relativedelta(months=m)


def durations(total):
    total = max(total, 4)
    d = {p: max(1, round(share * total)) for p, share in PHASES}
    d["energization"] = max(1, total - d["survey & permitting"] - d["clearing"] - d["construction"])
    while sum(d.values()) > total and d["construction"] > 1:
        d["construction"] -= 1
    return d


def prepare(data, c):
    """Month-indexed tasks with limits, plus which pairs are close enough to share a crew."""
    starts = [j["start_at"] for j in data["jobs"]]
    first = min(starts)
    origin = date(first.year, first.month, 1) - relativedelta(months=c["max_advance_months"])
    tasks = {}
    for j in data["jobs"]:
        s, dl = month_index(origin, j["start_at"]), month_index(origin, j["in_service"])
        tasks[j["id"]] = {"id": j["id"], "org": j["org_id"], "name": j["name"], "start": s, "deadline": dl,
                          "dur": durations(dl - s), "slip_limit": int(c["slip_overrides"].get(j["id"], c["max_slip_months"]))}
    drive = {tuple(sorted((o["job_a"], o["job_b"]))): o["drive_min"] for o in data["opps"]}
    near = {}
    for p in data["pairs"]:
        d = drive.get((p["a"], p["b"]))
        ok = float(d) <= c["crew_drive_min"] if d is not None else float(p["km"]) <= c["crew_km"]
        near[(p["a"], p["b"])] = (ok, {"drive_min": None if d is None else round(float(d)), "km": round(float(p["km"]), 1)})
    return origin, tasks, near


def filed(task):
    """The filed plan: phases back to back from the filed start."""
    out, m = {}, task["start"]
    for p in PHASE_NAMES:
        out[p] = m
        m += task["dur"][p]
    return out


def crew_span(task, starts):
    return starts["clearing"], starts["construction"] + task["dur"]["construction"]


def default_crews(tasks, origin):
    """Crews each utility needs per year to run its filed plan."""
    need = {}
    for t in tasks.values():
        a, b = crew_span(t, filed(t))
        for m in range(a, b):
            months = need.setdefault(t["org"], {}).setdefault(month_date(origin, m).year, {})
            months[m] = months.get(m, 0) + 1
    return {org: {y: max(ms.values()) for y, ms in years.items()} for org, years in need.items()}


def capacity(org, year, crews, overrides):
    o = overrides.get(org, {})
    if str(year) in o:
        return int(o[str(year)])
    return crews.get(org, {}).get(year, max(crews.get(org, {0: 1}).values()))


def blackout_hits(task, blackouts):
    return [b for b in blackouts if not b.get("site") or b["site"] == "*" or b["site"] == task["id"]
            or b["site"].lower() in task["name"].lower()]


# ---------- model ----------

def build(tasks, near, sites, c, origin, crews, coordinated, forced=None):
    m = cp_model.CpModel()
    ids = sorted(tasks)
    horizon = max(t["deadline"] + t["slip_limit"] for t in tasks.values()) + 12
    orgs = sorted({t["org"] for t in tasks.values()})
    v = {"start": {}, "crew_iv": {}, "crew_org": {}, "chain": {}, "idle": {}, "slip": {}, "adv": {}, "yard": {}, "open": {}}
    for j in ids:
        t = tasks[j]
        lo, hi = max(0, t["start"] - c["max_advance_months"]), t["deadline"] + t["slip_limit"]
        s = {p: m.NewIntVar(lo, hi, f"s_{j}_{p}") for p in PHASE_NAMES}
        v["start"][j] = s
        m.Add(s["clearing"] >= s["survey & permitting"] + t["dur"]["survey & permitting"])
        m.Add(s["construction"] == s["clearing"] + t["dur"]["clearing"])  # crews stay on from clearing into construction
        m.Add(s["energization"] >= s["construction"] + t["dur"]["construction"])
        slip = m.NewIntVar(0, t["slip_limit"], f"slip_{j}")  # hard in-service limit
        m.AddMaxEquality(slip, [s["energization"] + t["dur"]["energization"] - t["deadline"], 0])
        adv = m.NewIntVar(0, c["max_advance_months"], f"adv_{j}")
        m.AddMaxEquality(adv, [t["start"] - s["survey & permitting"], 0])
        v["slip"][j], v["adv"][j] = slip, adv
        for b in blackout_hits(t, c["blackouts"]):
            kind = b.get("phase_kind") or "energization"
            months = {int(x) for x in b.get("months", [])}
            blocked = [m.NewIntervalVar(k, 1, k + 1, f"bl_{j}_{kind}_{k}") for k in range(horizon) if month_date(origin, k).month in months]
            m.AddNoOverlap([m.NewFixedSizeIntervalVar(s[kind], t["dur"][kind], f"bo_{j}_{kind}")] + blocked)
        length = t["dur"]["clearing"] + t["dur"]["construction"]
        for u in orgs:
            if u != t["org"] and not coordinated:
                continue
            pres = m.NewBoolVar(f"co_{j}_{u}")
            v["crew_org"][(j, u)] = pres
            v["crew_iv"][(j, u)] = m.NewOptionalFixedSizeIntervalVar(s["clearing"], length, pres, f"crew_{j}_{u}")
        m.AddExactlyOne([v["crew_org"][(j, u)] for u in orgs if (j, u) in v["crew_org"]])
    for a in ids:  # a chain means one crew moves straight from task a to task b
        for b in ids:
            ok, _ = near.get(tuple(sorted((a, b))), (False, None))
            if a == b or not ok or (not coordinated and tasks[a]["org"] != tasks[b]["org"]):
                continue
            ch = m.NewBoolVar(f"ch_{a}_{b}")
            end_a = v["start"][a]["construction"] + tasks[a]["dur"]["construction"]
            m.Add(v["start"][b]["clearing"] >= end_a).OnlyEnforceIf(ch)
            m.Add(v["start"][b]["clearing"] <= end_a + c["chain_gap_months"]).OnlyEnforceIf(ch)
            idle = m.NewIntVar(0, c["chain_gap_months"], f"idle_{a}_{b}")
            m.Add(idle == v["start"][b]["clearing"] - end_a).OnlyEnforceIf(ch)
            m.Add(idle == 0).OnlyEnforceIf(ch.Not())
            for u in orgs:  # same crew, so the same utility's crew
                if (b, u) in v["crew_org"]:
                    other = v["crew_org"].get((a, u))
                    m.Add(v["crew_org"][(b, u)] == (other if other is not None else 0)).OnlyEnforceIf(ch)
            v["chain"][(a, b)], v["idle"][(a, b)] = ch, idle
    for j in ids:
        preds = [ch for (a, b), ch in v["chain"].items() if b == j]
        m.Add(sum(preds) <= 1)
        m.Add(sum(ch for (a, b), ch in v["chain"].items() if a == j) <= 1)
        m.Add(v["crew_org"][(j, tasks[j]["org"])] == 1).OnlyEnforceIf([p.Not() for p in preds])  # fresh crews are the job's own
    for u in orgs:  # crew capacity per utility per year
        ivs = [iv for (j, o), iv in v["crew_iv"].items() if o == u]
        demands = [1] * len(ivs)
        caps = [capacity(u, month_date(origin, k).year, crews, c["crew_counts"]) for k in range(horizon)]
        top = max(caps)
        for k, cap in enumerate(caps):
            if top - cap > 0:
                ivs.append(m.NewIntervalVar(k, 1, k + 1, f"cap_{u}_{k}"))
                demands.append(top - cap)
        m.AddCumulative(ivs, demands, top)
    for j in ids:  # yards: each job uses one site within reach
        opts = []
        for site in sites["near"].get(j, [f"job:{j}"]):
            owner = site if coordinated else f"{site}|{tasks[j]['org']}"
            if owner not in v["open"]:
                v["open"][owner] = m.NewBoolVar(f"open_{owner}")
            use = m.NewBoolVar(f"use_{j}_{owner}")
            m.AddImplication(use, v["open"][owner])
            v["yard"][(j, owner)] = use
            opts.append(use)
        m.AddExactlyOne(opts)
    for a, b in forced or []:  # counterfactual: these two must share a crew
        opts = [v["chain"][k] for k in ((a, b), (b, a)) if k in v["chain"]]
        m.AddBoolOr(opts or [m.NewConstant(0)])
    k = c["costs"]
    cost = (int(k["mobilization_k"]) * (len(ids) - sum(v["chain"].values())) + int(k["yard_k"]) * sum(v["open"].values())
            + int(k["idle_k_per_month"]) * sum(v["idle"].values()) + int(k["slip_k_per_month"]) * sum(v["slip"].values())
            + int(k["advance_k_per_month"]) * sum(v["adv"].values()))
    m.Minimize(cost)
    return m, v, cost


def solve(model, c, seconds=None):
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = float(seconds or c["time_limit_s"])
    s.parameters.num_workers = 8
    s.parameters.interleave_search = True  # deterministic parallel search
    s.parameters.random_seed = 0
    return s, s.StatusName(s.Solve(model))


def extract(s, v, tasks):
    chains = {a: b for (a, b), ch in v["chain"].items() if s.Value(ch)}
    preds = {b: a for a, b in chains.items()}
    out = {}
    for j, t in tasks.items():
        st = {p: s.Value(v["start"][j][p]) for p in PHASE_NAMES}
        out[j] = {"job_id": j, "org": t["org"], "name": t["name"], "starts": st,
                  "crew_org": next(u for (jj, u), var in v["crew_org"].items() if jj == j and s.Value(var)),
                  "yard": next(o.split("|")[0] for (jj, o), var in v["yard"].items() if jj == j and s.Value(var)),
                  "slip": s.Value(v["slip"][j]), "advance": s.Value(v["adv"][j]), "pred": preds.get(j), "succ": chains.get(j),
                  "shift": st["clearing"] - filed(t)["clearing"]}
    return out


def hint(model, v, sched, coordinated):
    for j, r in sched.items():
        for p, var in v["start"][j].items():
            model.AddHint(var, r["starts"][p])
        for (jj, u), var in v["crew_org"].items():
            if jj == j:
                model.AddHint(var, int(u == r["crew_org"]))
        for (jj, o), var in v["yard"].items():
            if jj == j:
                model.AddHint(var, int(o.split("|")[0] == r["yard"]))
    for (a, b), var in v["chain"].items():
        model.AddHint(var, int(sched.get(a, {}).get("succ") == b))
    used = {r["yard"] if coordinated else f"{r['yard']}|{r['org']}" for r in sched.values()}
    for o, var in v["open"].items():
        model.AddHint(var, int(o in used))


# ---------- results ----------

def crew_ids(sched, tasks):
    """Name crews by walking chains and packing them per utility."""
    routes = []
    for h in [j for j, r in sched.items() if not r["pred"]]:
        route, j = [h], sched[h]["succ"]
        while j:
            route.append(j)
            j = sched[j]["succ"]
        routes.append((sched[h]["crew_org"], crew_span(tasks[route[0]], sched[route[0]]["starts"])[0],
                       crew_span(tasks[route[-1]], sched[route[-1]]["starts"])[1], route))
    free = {}
    for org, a, b, route in sorted(routes, key=lambda r: (r[0], r[1], r[3][0])):
        ends = free.setdefault(org, [])
        idx = next((i for i, e in enumerate(ends) if e <= a), None)
        if idx is None:
            ends.append(b)
            idx = len(ends) - 1
        ends[idx] = b
        for j in route:
            sched[j]["crew"] = f"{org.upper()} crew {idx + 1}"
    return sched


def idle_of(r, sched, tasks):
    if not r["pred"]:
        return 0
    p = sched[r["pred"]]
    return r["starts"]["clearing"] - (p["starts"]["construction"] + tasks[p["job_id"]]["dur"]["construction"])


def metrics(sched, tasks, c, coordinated):
    k = c["costs"]
    mobs = sum(1 for r in sched.values() if not r["pred"])
    yards = len({r["yard"] if coordinated else (r["yard"], r["org"]) for r in sched.values()})
    idle = sum(idle_of(r, sched, tasks) for r in sched.values())
    slip = sum(r["slip"] for r in sched.values())
    adv = sum(r["advance"] for r in sched.values())
    return {"projects": len(sched), "mobilizations": mobs, "yards": yards, "idle_months": idle, "slip_months": slip,
            "slipped_projects": sum(1 for r in sched.values() if r["slip"] > 0),
            "late_projects": sum(1 for r in sched.values() if r["slip"] > tasks[r["job_id"]]["slip_limit"]),
            "advance_months": adv, "shared_crews": sum(1 for r in sched.values() if r["pred"] and r["crew_org"] != r["org"]),
            "cost_k": round(k["mobilization_k"] * mobs + k["yard_k"] * yards + k["idle_k_per_month"] * idle
                            + k["slip_k_per_month"] * slip + k["advance_k_per_month"] * adv)}


def headline(base, coord, c):
    """Savings range from the same cost model: fewer mobilizations and yards at low/high unit costs, minus extra idle/slip/advance."""
    k = c["costs"]
    dm, dy = base["mobilizations"] - coord["mobilizations"], base["yards"] - coord["yards"]
    extra = ((coord["idle_months"] - base["idle_months"]) * k["idle_k_per_month"] + (coord["slip_months"] - base["slip_months"])
             * k["slip_k_per_month"] + (coord["advance_months"] - base["advance_months"]) * k["advance_k_per_month"]) * 1000
    mob, yard = ASSUMPTIONS["mobilization_usd"], ASSUMPTIONS["yard_usd"]
    return {"mobilizations_before": base["mobilizations"], "mobilizations_after": coord["mobilizations"], "mobilizations_cut": dm,
            "mobilizations_cut_pct": round(100 * dm / base["mobilizations"]) if base["mobilizations"] else 0,
            "yards_before": base["yards"], "yards_after": coord["yards"],
            "savings_low": round(max(dm * mob["low"] + dy * yard["low"] - extra, 0)),
            "savings_high": round(max(dm * mob["high"] + dy * yard["high"] - extra, 0)),
            "late_projects": coord["late_projects"], "cost_cut_k": base["cost_k"] - coord["cost_k"]}


def months_text(n):
    return f"{abs(n)} month{'s' if abs(n) != 1 else ''}"


def move_reason(r, sched, tasks, c, origin, crews):
    """Why a project's crew work moved, from constraint checks on the solved schedule."""
    t = tasks[r["job_id"]]
    if r["shift"] == 0:
        return None
    when = "later" if r["shift"] > 0 else "earlier"
    partner = sched.get(r["pred"]) or sched.get(r["succ"])
    if partner:
        return f"{t['name']} crew work moves {months_text(r['shift'])} {when} so {r['crew']} can go straight between it and {partner['name']}."
    for b in blackout_hits(t, c["blackouts"]):
        kind = b.get("phase_kind") or "energization"
        f = filed(t)[kind]
        if any(month_date(origin, f + i).month in {int(x) for x in b.get("months", [])} for i in range(t["dur"][kind])):
            return f"{t['name']} moves {months_text(r['shift'])} {when} to keep {kind} out of {', '.join(MONTHS[int(x) - 1] for x in b['months'])}."
    a, b = crew_span(t, filed(t))
    for mo in range(a, b):
        y = month_date(origin, mo).year
        cap = capacity(t["org"], y, crews, c["crew_counts"])
        if cap < crews.get(t["org"], {}).get(y, cap):
            return f"{t['name']} moves {months_text(r['shift'])} {when}: {t['org'].upper()} has {cap} crews in {y} but the filed plans need {crews[t['org']][y]}."
    return f"{t['name']} moves {months_text(r['shift'])} {when}; the solver found this cheaper overall at no extra slip."


def decisions(data, sched, tasks, near, sites):
    out = []
    for o in data["opps"]:
        a, b = o["job_a"], o["job_b"]
        if a not in sched or b not in sched:
            continue
        ra, rb = sched[a], sched[b]
        ok, info = near.get(tuple(sorted((a, b))), (False, {}))
        d = {"opportunity_id": o["id"], "a": ra["name"], "b": rb["name"], "job_a": a, "job_b": b, "eligible": ok, "reasons": [],
             "drive_min": info.get("drive_min"), "km": info.get("km")}
        first = a if ra["succ"] == b else b if rb["succ"] == a else None
        if first:
            then = b if first == a else a
            gap = sched[then]["starts"]["clearing"] - (sched[first]["starts"]["construction"] + tasks[first]["dur"]["construction"])
            d["reasons"].append({"rule": "shared_crew", "crew": sched[first]["crew"], "first": sched[first]["name"],
                                 "then": sched[then]["name"], "gap_months": gap})
        elif not ok:
            if info.get("drive_min") is not None:
                d["reasons"].append({"rule": "drive_time", "minutes": info["drive_min"], "limit": None})
            else:
                d["reasons"].append({"rule": "distance", "km": info.get("km"), "limit": None})
        else:
            d["reasons"].append({"rule": "not_chosen"})  # counterfactual computed on request
        if ra["yard"] == rb["yard"]:
            d["reasons"].append({"rule": "shared_yard", "yard": sites[ra["yard"]]["label"] if ra["yard"] in sites else ra["yard"]})
        d["decision"] = "share" if first else "no_share"
        out.append(d)
    return out


def sentence(reason, c=None):
    r = reason["rule"]
    if r == "shared_crew":
        return (f"{reason['crew']} finishes {reason['first']} and starts {reason['then']} {months_text(reason['gap_months'])} later, "
                "saving one mobilization.")
    if r == "shared_yard":
        return f"Both use one staging yard {reason['yard']}."
    if r == "drive_time":
        return f"The two sites are {reason['minutes']} minutes apart by road; the crew limit is {reason.get('limit') or (c or DEFAULTS)['crew_drive_min']}."
    if r == "distance":
        return f"The two sites are {reason['km']} km apart; the crew limit is {reason.get('limit') or (c or DEFAULTS)['crew_km']} km."
    if r == "max_slip":
        return (f"Sharing would push {reason['project']} {months_text(reason['needed_months'])} past in-service; "
                f"limit is {reason['limit_months']}.")
    if r == "costs_more":
        return (f"Sharing is allowed but raises total cost by ${reason['delta_k']:,}k "
                f"({reason['detail']}), so the solver kept them apart.")
    if r == "infeasible":
        return "No schedule lets one crew do both, even with extra slip: crew capacity or a blackout blocks it."
    if r == "not_chosen":
        return "Close enough to share a crew, but the solver found a cheaper plan without it. Ask why for the exact reason."
    return r


def describe(d, c):
    d["sentence"] = " ".join(sentence(r, c) for r in d["reasons"])
    return d


# ---------- runs ----------

def solve_all(data, c):
    origin, tasks, near = prepare(data, c)
    crews = default_crews(tasks, origin)
    base_sched, problems = {}, []
    for org in sorted({t["org"] for t in tasks.values()}):  # each utility alone
        sub = {j: t for j, t in tasks.items() if t["org"] == org}
        model, v, _ = build(sub, near, data, c, origin, crews, coordinated=False)
        s, status = solve(model, c)
        if status not in ("OPTIMAL", "FEASIBLE"):
            problems.append(org)
            continue
        base_sched.update(extract(s, v, sub))
    if problems:
        return {"status": "infeasible", "problem": diagnose(data, c, problems)}, origin, tasks, near, crews
    base = metrics(crew_ids(base_sched, tasks), tasks, c, coordinated=False)
    model, v, cost = build(tasks, near, data, c, origin, crews, coordinated=True)
    hint(model, v, base_sched, coordinated=True)
    model.Add(cost <= base["cost_k"])  # the baseline is a valid joint plan, so never do worse
    s, status = solve(model, c)
    if status not in ("OPTIMAL", "FEASIBLE"):
        return {"status": "infeasible", "problem": "the joint model found no schedule within the time limit"}, origin, tasks, near, crews
    sched = crew_ids(extract(s, v, tasks), tasks)
    coord = metrics(sched, tasks, c, coordinated=True)
    return {"status": status.lower(), "baseline": base, "coordinated": coord, "headline": headline(base, coord, c),
            "sched": sched, "base_sched": base_sched}, origin, tasks, near, crews


def diagnose(data, c, orgs):
    """Name the constraint that makes a utility's plan impossible by relaxing one at a time."""
    tries = [("slip limit", {"max_slip_months": RELAXED_SLIP, "slip_overrides": {}}), ("crew counts", {"crew_counts": {}}),
             ("blackouts", {"blackouts": []})]
    for label, change in tries:
        relaxed = {**c, **change}
        origin, tasks, near = prepare(data, relaxed)
        crews = default_crews(tasks, origin)
        ok = True
        for org in orgs:
            sub = {j: t for j, t in tasks.items() if t["org"] == org}
            model, _, _ = build(sub, near, data, relaxed, origin, crews, coordinated=False)
            ok = ok and solve(model, relaxed, 5)[1] in ("OPTIMAL", "FEASIBLE")
        if ok:
            return f"No schedule for {', '.join(o.upper() for o in orgs)} meets these rules; relaxing the {label} makes it possible."
    return f"No schedule for {', '.join(o.upper() for o in orgs)} meets these rules."


def schedule_rows(sched, tasks, origin, sites, base_sched):
    rows = []
    for j, r in sorted(sched.items(), key=lambda x: (x[1]["crew"], x[1]["starts"]["clearing"])):
        t = tasks[j]
        phases = [{"phase": p, "start": month_date(origin, r["starts"][p]).isoformat(),
                   "end": month_date(origin, r["starts"][p] + t["dur"][p]).isoformat()} for p in PHASE_NAMES]
        f = filed(t)
        rows.append({"job_id": j, "name": t["name"], "org": t["org"], "crew": r["crew"], "crew_org": r["crew_org"],
                     "yard": r["yard"], "yard_label": sites.get(r["yard"], {}).get("label", r["yard"]),
                     "phases": phases, "filed_start": month_date(origin, f["clearing"]).isoformat(),
                     "filed_end": month_date(origin, f["construction"] + t["dur"]["construction"]).isoformat(),
                     "in_service": month_date(origin, t["deadline"]).isoformat(), "slip": r["slip"], "slip_limit": t["slip_limit"],
                     "shift": r["shift"], "baseline_crew": base_sched.get(j, {}).get("crew"), "why": r.get("why")})
    return rows


def run(conn, constraints=None):
    conn.execute(TABLE_SQL)
    c = merge(constraints)
    data = load(conn, c["yard_km"])
    ids = [j["id"] for j in data["jobs"]]
    if not ids:
        return {"status": "empty", "problem": "no long-range opportunities to plan"}
    res, origin, tasks, near, crews = solve_all(data, c)
    saved = {k: v for k, v in c.items() if k != "time_limit_s"}
    if res["status"] == "infeasible":
        row = conn.execute("INSERT INTO joint_plan (constraints, job_ids, status, problem) VALUES (%s, %s, 'infeasible', %s) RETURNING id",
                           (json.dumps(saved), ids, res["problem"])).fetchone()
        return {"plan_id": row["id"], "status": "infeasible", "problem": res["problem"], "constraints": saved}
    sched = res["sched"]
    for r in sched.values():
        r["why"] = move_reason(r, sched, tasks, c, origin, crews)
    decs = [describe(d, c) for d in decisions(data, sched, tasks, near, data["sites"])]
    rows = schedule_rows(sched, tasks, origin, data["sites"], res["base_sched"])
    crew_table = {org: {str(y): capacity(org, y, crews, c["crew_counts"]) for y in years} for org, years in crews.items()}
    out = {"status": res["status"], "baseline": res["baseline"], "coordinated": res["coordinated"],
           "headline": {**res["headline"], "crews": crew_table}}
    row = conn.execute("""INSERT INTO joint_plan (constraints, job_ids, status, baseline, coordinated, headline, schedule, decisions)
                          VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id, run_at""",
                       (json.dumps(saved), ids, res["status"], json.dumps(res["baseline"]), json.dumps(res["coordinated"]),
                        json.dumps(out["headline"]), json.dumps(rows), json.dumps(decs))).fetchone()
    return {"plan_id": row["id"], "run_at": row["run_at"], "constraints": saved, **out, "schedule": rows, "decisions": decs}


def as_result(row):
    return {"plan_id": row["id"], "run_at": row["run_at"], "constraints": row["constraints"], "status": row["status"],
            "problem": row["problem"], "baseline": row["baseline"], "coordinated": row["coordinated"], "headline": row["headline"],
            "schedule": row["schedule"] or [], "decisions": row["decisions"] or []}


def latest(conn):
    conn.execute(TABLE_SQL)
    row = conn.execute("SELECT * FROM joint_plan ORDER BY id DESC LIMIT 1").fetchone()
    ids = sorted(j["id"] for j in conn.execute(JOBS_SQL).fetchall())
    if not row or sorted(row["job_ids"]) != ids:  # data was rebuilt since the last run
        return run(conn, row["constraints"] if row else None)
    return as_result(row)


def counterfactual(conn, plan, d):
    """Re-solve with the pair forced to share a crew and slip relaxed for the two projects, then name what binds."""
    c = merge(plan["constraints"])
    base_limits = {j: int(c["slip_overrides"].get(j, c["max_slip_months"])) for j in (d["job_a"], d["job_b"])}
    relaxed = merge({**plan["constraints"], "slip_overrides": {**c["slip_overrides"], d["job_a"]: RELAXED_SLIP, d["job_b"]: RELAXED_SLIP}})
    data = load(conn, c["yard_km"])
    origin, tasks, near = prepare(data, relaxed)
    crews = default_crews(tasks, origin)
    model, v, _ = build(tasks, near, data, relaxed, origin, crews, coordinated=True, forced=[(d["job_a"], d["job_b"])])
    s, status = solve(model, relaxed, 5)
    if status not in ("OPTIMAL", "FEASIBLE"):
        return {"rule": "infeasible"}
    sched = extract(s, v, tasks)
    over = [(sched[j]["slip"] - base_limits[j], j) for j in base_limits if sched[j]["slip"] > base_limits[j]]
    if over:
        _, j = max(over)
        return {"rule": "max_slip", "project": tasks[j]["name"], "needed_months": sched[j]["slip"], "limit_months": base_limits[j]}
    cf = metrics(crew_ids(sched, tasks), tasks, c, coordinated=True)
    now = plan["coordinated"]
    parts = [f"{label} {cf[key] - now[key]:+d}" for key, label in (("mobilizations", "mobilizations"), ("idle_months", "idle months"),
             ("slip_months", "slip months"), ("advance_months", "months started early"), ("yards", "yards")) if cf[key] != now[key]]
    return {"rule": "costs_more", "delta_k": max(cf["cost_k"] - now["cost_k"], 0), "detail": ", ".join(parts) or "same counts"}


def explain(conn, opportunity_id=None, project=None):
    plan = latest(conn)
    if plan.get("status") in ("infeasible", "empty"):
        return {"plan_id": plan.get("plan_id"), "status": plan["status"], "problem": plan.get("problem"), "decisions": [], "projects": []}
    q = (project or "").lower()
    hits = [d for d in plan["decisions"] if (opportunity_id is not None and d["opportunity_id"] == opportunity_id)
            or (q and (q in d["a"].lower() or q in d["b"].lower()))]
    changed = False
    for d in hits[:6]:  # counterfactuals are a few seconds each, so only for what was asked
        for i, r in enumerate(d["reasons"]):
            if r["rule"] == "not_chosen":
                d["reasons"][i] = counterfactual(conn, plan, d)
                describe(d, merge(plan["constraints"]))
                changed = True
    if changed:
        conn.execute("UPDATE joint_plan SET decisions = %s WHERE id = %s", (json.dumps(plan["decisions"]), plan["plan_id"]))
    projects = [{"job_id": r["job_id"], "name": r["name"], "crew": r["crew"], "shift": r["shift"], "slip": r["slip"],
                 "why": r["why"]} for r in plan["schedule"] if q and q in r["name"].lower()]
    return {"plan_id": plan["plan_id"], "constraints": plan["constraints"], "decisions": hits, "projects": projects}


def validate(conn, constraints):
    """Check planner or Crewly constraints against the data and echo them in structured form."""
    c = merge(constraints)
    jobs = conn.execute(JOBS_SQL).fetchall()
    orgs = {j["org_id"] for j in jobs}
    notes, errors, slips = [], [], {}
    for name, months in (constraints or {}).get("slip_overrides", {}).items():
        match = [j for j in jobs if j["id"] == name or name.lower() in j["name"].lower()]
        if not match:
            errors.append(f"no planned project matches '{name}'")
        for j in match:
            slips[j["id"]] = int(months)
            notes.append(f"{j['name']}: may slip up to {months_text(int(months))}")
    c["slip_overrides"] = slips
    for b in c["blackouts"]:
        months = [int(x) for x in b.get("months", []) if 1 <= int(x) <= 12]
        if not months:
            errors.append("a blackout needs at least one month (1-12)")
        b["months"] = months
        b["phase_kind"] = b.get("phase_kind") or "energization"
        if b["phase_kind"] not in PHASE_NAMES:
            errors.append(f"unknown phase '{b['phase_kind']}'")
        hit = [j["name"] for j in jobs if not b.get("site") or b["site"] == "*" or b["site"].lower() in j["name"].lower()]
        if not hit:
            errors.append(f"blackout site '{b.get('site')}' matches no planned project")
        notes.append(f"No {b['phase_kind']} in {', '.join(MONTHS[m - 1] for m in months)} at {len(hit)} project(s)")
    for org, years in c["crew_counts"].items():
        if org not in orgs:
            errors.append(f"unknown utility '{org}'")
        for y, n in years.items():
            if int(n) < 0:
                errors.append("crew counts cannot be negative")
            notes.append(f"{org.upper()} has {n} crews in {y}")
    return {"constraints": {k: v for k, v in c.items() if k != "time_limit_s"}, "notes": notes, "errors": errors, "valid": not errors}
