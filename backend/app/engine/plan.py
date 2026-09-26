import copy
import json
import math
import re
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from ortools.sat.python import cp_model

from app.config import ASSUMPTIONS, PHASES
from app.ingest.classify import endpoints

MODEL = 2  # bump when the model changes so stored plans get re-solved
WPM = 4  # model weeks per month; burst dates are measured from their phase start so the rounding stays inside a phase
BURSTS = {  # editable assumptions, not public data: duration, where in the phase, cost per mobilization ($k)
    "heavy_haul": {"label": "heavy haul", "resource": "heavy-haul rig", "phase": "construction", "window": [0.0, 0.35], "weeks": 2,
                   "mob_low_k": 40, "mob_high_k": 90, "applies": ["substation", "new_line", "line_upgrade"], "enabled": True},
    "crane_lift": {"label": "crane lift", "resource": "crane", "phase": "construction", "window": [0.2, 0.8], "weeks": 2,
                   "mob_low_k": 60, "mob_high_k": 150, "applies": ["substation", "new_line", "line_upgrade"], "enabled": True},
    "wire_stringing": {"label": "wire stringing", "resource": "stringing crew", "phase": "construction", "window": [0.4, 1.0], "weeks": 4,
                       "mob_low_k": 80, "mob_high_k": 200, "applies": ["new_line", "line_upgrade"], "enabled": True},
    "commissioning": {"label": "commissioning", "resource": "commissioning team", "phase": "energization", "window": [0.0, 1.0], "weeks": 2,
                      "mob_low_k": 30, "mob_high_k": 80, "applies": ["substation", "new_line", "line_upgrade"], "enabled": True},
}
BURST_KEYS = {"weeks", "window", "mob_low_k", "mob_high_k", "enabled"}
DEFAULTS = {
    "max_slip_months": 6, "slip_overrides": {}, "max_advance_months": 6, "crew_counts": {}, "blackouts": [],
    "chain_gap_months": 2, "crew_drive_min": 45, "crew_km": 40, "yard_km": 8, "time_limit_s": 8,
    "bursts": BURSTS, "burst_gap_weeks": 2, "joint_contracting": False, "jc_overlap_months": 3,
    "costs": {"mobilization_k": 100, "yard_k": 275, "idle_k_per_month": 30, "slip_k_per_month": 50, "advance_k_per_month": 5,
              "burst_idle_k_per_week": 10},
}
JC_NOTE = "Assumes one contractor serves both utilities' jobs that run at the same time within a 45 minute drive."
PHASE_NAMES = [p for p, _ in PHASES]
C_PHASE = {b: s["phase"] for b, s in BURSTS.items()}  # burst phases are fixed; only weeks, windows and costs are editable
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
SELECT j.id, j.org_id, j.name, j.job_type, lower(j.work_window)::date AS start_at, j.in_service
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
        elif k == "bursts" and isinstance(v, dict):
            for name, spec in v.items():
                if name in c["bursts"] and isinstance(spec, dict):
                    c["bursts"][name].update({kk: vv for kk, vv in spec.items() if kk in BURST_KEYS})
        elif k in c and v is not None:
            c[k] = v
    for k in ("max_slip_months", "max_advance_months", "chain_gap_months", "burst_gap_weeks", "jc_overlap_months"):
        c[k] = int(c[k])
    c["joint_contracting"] = bool(c["joint_contracting"])
    for b in c["bursts"].values():
        b["weeks"], b["enabled"] = max(1, int(b["weeks"])), bool(b["enabled"])
        b["window"] = [float(b["window"][0]), float(b["window"][1])]
        b["mob_low_k"], b["mob_high_k"] = float(b["mob_low_k"]), float(b["mob_high_k"])
    return c


def mid_k(c):
    return {b: int(round((s["mob_low_k"] + s["mob_high_k"]) / 2)) for b, s in c["bursts"].items()}


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


def burst_windows(dur, job_type, c):
    """Week window (from phase start) and length for each specialty burst this kind of job needs."""
    out = {}
    for name, b in c["bursts"].items():
        if not b["enabled"] or (job_type or "line_upgrade") not in b["applies"]:
            continue
        span = dur[b["phase"]] * WPM
        n = min(b["weeks"], span)
        lo, hi = math.floor(b["window"][0] * span), math.ceil(b["window"][1] * span)
        if hi - lo < n:
            lo, hi = 0, span  # phase too short for the typical window: anywhere in the phase
        out[name] = (lo, hi, n, lo + (hi - lo - n) // 2)  # last value: typical slot, the middle of the window
    return out


def short(name):
    """'SAV: GOSHEN (SAV) - KRAFT 115KV LINE REBUILD' -> 'Goshen–Kraft'."""
    ends = [re.sub(r"\(.*?\)|#\s*\d+", "", e).strip().title() for e in endpoints(name)]
    ends = [e for e in ends if e]
    return "–".join(ends) if ends else name[:40]


def prepare(data, c):
    """Month-indexed tasks with limits and bursts, plus which pairs are close enough to share a crew."""
    starts = [j["start_at"] for j in data["jobs"]]
    first = min(starts)
    origin = date(first.year, first.month, 1) - relativedelta(months=c["max_advance_months"])
    tasks = {}
    for j in data["jobs"]:
        s, dl = month_index(origin, j["start_at"]), month_index(origin, j["in_service"])
        dur = durations(dl - s)
        tasks[j["id"]] = {"id": j["id"], "org": j["org_id"], "name": j["name"], "short": short(j["name"]), "type": j.get("job_type"),
                          "start": s, "deadline": dl, "dur": dur, "bursts": burst_windows(dur, j.get("job_type"), c),
                          "slip_limit": int(c["slip_overrides"].get(j["id"], c["max_slip_months"]))}
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


def bounds(task, c):
    """Earliest and latest start month of each phase given advance and slip limits."""
    before, e, l = 0, {}, {}
    total = sum(task["dur"].values())
    for p in PHASE_NAMES:
        e[p] = max(0, task["start"] - c["max_advance_months"]) + before
        l[p] = task["deadline"] + task["slip_limit"] - (total - before)
        before += task["dur"][p]
    return e, l


def burst_range(task, b, c):
    e, l = bounds(task, c)
    ph = c["bursts"][b]["phase"]
    lo, hi, n, _ = task["bursts"][b]
    return WPM * e[ph] + lo, WPM * l[ph] + hi - n


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


def close(near, a, b):
    return near.get(tuple(sorted((a, b))), (False, None))[0]


def can_chain(ta, tb, c):
    """Could b's crew work start right after a's ends, within the allowed gap?"""
    (ea, la), (eb, lb) = bounds(ta, c), bounds(tb, c)
    end_lo, end_hi = ea["construction"] + ta["dur"]["construction"], la["construction"] + ta["dur"]["construction"]
    return lb["clearing"] >= end_lo and eb["clearing"] <= end_hi + c["chain_gap_months"]


def can_overlap(ta, tb, c):
    (ea, la), (eb, lb) = bounds(ta, c), bounds(tb, c)
    end_a, end_b = la["construction"] + ta["dur"]["construction"], lb["construction"] + tb["dur"]["construction"]
    return ea["clearing"] + c["jc_overlap_months"] <= end_b and eb["clearing"] + c["jc_overlap_months"] <= end_a


# ---------- model ----------

def interacting(tasks, near, sites):
    """Projects coordination can change: a partner of the other utility within reach, or a yard site both utilities could use."""
    out = set()
    for (a, b), (ok, _) in near.items():
        if ok and a in tasks and b in tasks and tasks[a]["org"] != tasks[b]["org"]:
            out |= {a, b}
    orgs = {}
    for j, ss in sites["near"].items():
        for site in ss:
            if j in tasks:
                orgs.setdefault(site, set()).add(tasks[j]["org"])
    out |= {j for j, ss in sites["near"].items() if j in tasks and any(len(orgs[site]) > 1 for site in ss)}
    return out


def build(tasks, near, sites, c, origin, crews, coordinated, jc=False, forced=None, fixed=None):
    """coordinated: bursts and yards may be shared across utilities; jc: concurrent jobs may share one contractor;
    fixed: projects pinned to a known schedule (their standalone optimum) so the search only moves the rest."""
    m = cp_model.CpModel()
    ids = sorted(tasks)
    horizon = max(t["deadline"] + t["slip_limit"] for t in tasks.values()) + 12
    orgs = sorted({t["org"] for t in tasks.values()})
    gap = c["burst_gap_weeks"]
    v = {"start": {}, "crew_iv": {}, "chain": {}, "idle": {}, "slip": {}, "adv": {}, "yard": {}, "open": {},
         "bw": {}, "bdev": {}, "blink": {}, "bgap": {}, "jc": {}}
    for j in ids:
        t = tasks[j]
        e, l = bounds(t, c)
        s = {p: m.NewIntVar(e[p], max(e[p], l[p]), f"s_{j}_{p}") for p in PHASE_NAMES}
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
        v["crew_iv"][j] = m.NewFixedSizeIntervalVar(s["clearing"], t["dur"]["clearing"] + t["dur"]["construction"], f"crew_{j}")
        for b, (wlo, whi, n, ref) in t["bursts"].items():  # specialty bursts sit inside their phase window
            rlo, rhi = burst_range(t, b, c)
            w = m.NewIntVar(rlo, max(rlo, rhi), f"w_{j}_{b}")
            ph = c["bursts"][b]["phase"]
            m.Add(w >= WPM * s[ph] + wlo)
            m.Add(w + n <= WPM * s[ph] + whi)
            dev = m.NewIntVar(0, whi, f"dev_{j}_{b}")  # weeks away from the typical slot in its phase
            m.Add(dev >= w - WPM * s[ph] - ref)
            m.Add(dev >= WPM * s[ph] + ref - w)
            v["bw"][(j, b)], v["bdev"][(j, b)] = w, dev
    for a in ids:  # general crews never cross utilities: a crew moves straight to its own utility's next job
        for b in ids:
            if a == b or tasks[a]["org"] != tasks[b]["org"] or not close(near, a, b) or not can_chain(tasks[a], tasks[b], c):
                continue
            ch = m.NewBoolVar(f"ch_{a}_{b}")
            end_a = v["start"][a]["construction"] + tasks[a]["dur"]["construction"]
            m.Add(v["start"][b]["clearing"] >= end_a).OnlyEnforceIf(ch)
            m.Add(v["start"][b]["clearing"] <= end_a + c["chain_gap_months"]).OnlyEnforceIf(ch)
            idle = m.NewIntVar(0, c["chain_gap_months"], f"idle_{a}_{b}")
            m.Add(idle == v["start"][b]["clearing"] - end_a).OnlyEnforceIf(ch)
            m.Add(idle == 0).OnlyEnforceIf(ch.Not())
            v["chain"][(a, b)], v["idle"][(a, b)] = ch, idle
    for (x, b), wx in v["bw"].items():  # one specialty resource serves bursts back to back
        for (y, b2), wy in v["bw"].items():
            if b2 != b or x == y or not close(near, x, y) or (not coordinated and tasks[x]["org"] != tasks[y]["org"]):
                continue
            n = tasks[x]["bursts"][b][2]
            (xlo, xhi), (ylo, yhi) = burst_range(tasks[x], b, c), burst_range(tasks[y], b, c)
            if yhi < xlo + n or ylo > xhi + n + gap:
                continue  # these bursts can never run back to back
            link = m.NewBoolVar(f"bl_{b}_{x}_{y}")
            m.Add(wy >= wx + n).OnlyEnforceIf(link)
            m.Add(wy <= wx + n + gap).OnlyEnforceIf(link)
            g = m.NewIntVar(0, gap, f"bg_{b}_{x}_{y}")
            m.Add(g == wy - wx - n).OnlyEnforceIf(link)
            m.Add(g == 0).OnlyEnforceIf(link.Not())
            v["blink"][(b, x, y)], v["bgap"][(b, x, y)] = link, g
    for (j, b) in v["bw"]:
        m.Add(sum(l for (bb, x, y), l in v["blink"].items() if bb == b and y == j) <= 1)
        m.Add(sum(l for (bb, x, y), l in v["blink"].items() if bb == b and x == j) <= 1)
    if jc:  # joint contracting: one contractor base serves two concurrent jobs of different utilities
        for a in ids:
            for b in ids:
                if a >= b or tasks[a]["org"] == tasks[b]["org"] or not close(near, a, b) or not can_overlap(tasks[a], tasks[b], c):
                    continue
                on = m.NewBoolVar(f"jc_{a}_{b}")
                end_a = v["start"][a]["construction"] + tasks[a]["dur"]["construction"]
                end_b = v["start"][b]["construction"] + tasks[b]["dur"]["construction"]
                m.Add(v["start"][a]["clearing"] + c["jc_overlap_months"] <= end_b).OnlyEnforceIf(on)
                m.Add(v["start"][b]["clearing"] + c["jc_overlap_months"] <= end_a).OnlyEnforceIf(on)
                v["jc"][(a, b)] = on
    for j in ids:
        preds = [ch for (a, b), ch in v["chain"].items() if b == j]
        m.Add(sum(preds) <= 1)
        m.Add(sum(ch for (a, b), ch in v["chain"].items() if a == j) <= 1)
        m.Add(sum(preds) + sum(on for (a, b), on in v["jc"].items() if j in (a, b)) <= 1)  # a job's crew comes from one place
    for u in orgs:  # crew capacity per utility per year
        ivs = [iv for j, iv in v["crew_iv"].items() if tasks[j]["org"] == u]
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
    users = {}
    for (j, owner), use in v["yard"].items():
        users.setdefault(owner, []).append((j, use))
    for owner, js in users.items():  # one yard serves two jobs only if they are within the crew drive limit of each other
        for i, (a, ua) in enumerate(js):
            for b, ub in js[i + 1:]:
                if not close(near, a, b):
                    m.AddBoolOr([ua.Not(), ub.Not()])
    for j, r in (fixed or {}).items():  # pinned projects keep their standalone schedule
        for p in PHASE_NAMES:
            m.Add(v["start"][j][p] == r["starts"][p])
        for b, x in r["bursts"].items():
            if (j, b) in v["bw"]:
                m.Add(v["bw"][(j, b)] == x["week"])
        for (jj, o), use in v["yard"].items():
            if jj == j:
                m.Add(use == int(o.split("|")[0] == r["yard"]))
    for (a, b), ch in v["chain"].items():
        if a in (fixed or {}) and b in fixed:
            m.Add(ch == int(fixed[a]["succ"] == b))
    for (b, x, y), link in v["blink"].items():
        if x in (fixed or {}) and y in fixed:
            m.Add(link == int(fixed[x]["bursts"].get(b, {}).get("succ") == y))
    for b, x, y in forced or []:  # counterfactual: this burst must be shared between the two jobs
        opts = [v["blink"][k] for k in ((b, x, y), (b, y, x)) if k in v["blink"]]
        m.AddBoolOr(opts or [m.NewConstant(0)])
    k, mid = c["costs"], mid_k(c)
    cost = (int(k["mobilization_k"]) * (len(ids) - sum(v["chain"].values()) - sum(v["jc"].values()))
            + sum(mid[b] for (_, b) in v["bw"]) - sum(mid[b] * l for (b, _, _), l in v["blink"].items())
            + int(k["yard_k"]) * sum(v["open"].values()) + int(k["idle_k_per_month"]) * sum(v["idle"].values())
            + int(k["burst_idle_k_per_week"]) * sum(v["bgap"].values())
            + int(k["slip_k_per_month"]) * sum(v["slip"].values()) + int(k["advance_k_per_month"]) * sum(v["adv"].values()))
    m.Minimize(cost)
    v["dev_total"] = sum(v["bdev"].values())
    return m, v, cost


def solve(model, c, seconds=None):
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = float(seconds or c["time_limit_s"])
    s.parameters.num_workers = 8
    s.parameters.random_seed = 0
    return s, s.StatusName(s.Solve(model))


def tidy(model, v, cost, s, c):
    """Second pass: keep the cost found, move bursts as little as possible from their typical slot (only for clearer explanations)."""
    best = int(round(s.ObjectiveValue()))
    model.ClearHints()
    for i in range(len(model.Proto().variables)):
        var = model.GetIntVarFromProtoIndex(i)
        model.AddHint(var, s.Value(var))
    model.Add(cost <= best)
    model.Minimize(v["dev_total"])
    t, status = solve(model, c, min(2, c["time_limit_s"]))
    return t if status in ("OPTIMAL", "FEASIBLE") else s


def extract(s, v, tasks):
    chains = {a: b for (a, b), ch in v["chain"].items() if s.Value(ch)}
    preds = {b: a for a, b in chains.items()}
    links = {(b, x): y for (b, x, y), l in v["blink"].items() if s.Value(l)}
    bpreds = {(b, y): x for (b, x), y in links.items()}
    contractor = {}
    for (a, b), on in v["jc"].items():
        if s.Value(on):
            contractor[a], contractor[b] = b, a
    out = {}
    for j, t in tasks.items():
        st = {p: s.Value(v["start"][j][p]) for p in PHASE_NAMES}
        bursts = {b: {"week": s.Value(w), "weeks": t["bursts"][b][2], "succ": links.get((b, j)), "pred": bpreds.get((b, j)),
                      "moved": s.Value(w) - WPM * st[C_PHASE[b]] - t["bursts"][b][3]}
                  for (jj, b), w in v["bw"].items() if jj == j}
        out[j] = {"job_id": j, "org": t["org"], "name": t["name"], "starts": st, "crew_org": t["org"],
                  "yard": next(o.split("|")[0] for (jj, o), var in v["yard"].items() if jj == j and s.Value(var)),
                  "slip": s.Value(v["slip"][j]), "advance": s.Value(v["adv"][j]), "pred": preds.get(j), "succ": chains.get(j),
                  "shift": st["clearing"] - filed(t)["clearing"], "bursts": bursts, "contractor": contractor.get(j)}
    return out


def hint(model, v, sched, coordinated):
    for j, r in sched.items():
        for p, var in v["start"][j].items():
            model.AddHint(var, r["starts"][p])
        for (jj, o), var in v["yard"].items():
            if jj == j:
                model.AddHint(var, int(o.split("|")[0] == r["yard"]))
        for b, x in r["bursts"].items():
            if (j, b) in v["bw"]:
                model.AddHint(v["bw"][(j, b)], x["week"])
    for (a, b), var in v["chain"].items():
        model.AddHint(var, int(sched.get(a, {}).get("succ") == b))
    for (b, x, y), var in v["blink"].items():
        model.AddHint(var, int(sched.get(x, {}).get("bursts", {}).get(b, {}).get("succ") == y))
    for (a, b), var in v["jc"].items():
        model.AddHint(var, int(sched.get(a, {}).get("contractor") == b))
    used = {r["yard"] if coordinated else f"{r['yard']}|{r['org']}" for r in sched.values()}
    for o, var in v["open"].items():
        model.AddHint(var, int(o in used))


# ---------- results ----------

def crew_ids(sched, tasks, c=None):
    """Name crews by walking chains and packing them per utility; name specialty resources by walking burst chains."""
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
    resources = (c or DEFAULTS)["bursts"]
    heads = sorted(((x["week"], b, j) for j, r in sched.items() for b, x in r["bursts"].items() if not x["pred"]))
    count = {}
    for _, b, j in heads:
        count[b] = count.get(b, 0) + 1
        route, k = [j], sched[j]["bursts"][b]["succ"]
        while k:
            route.append(k)
            k = sched[k]["bursts"][b]["succ"]
        shared = len({sched[x]["org"] for x in route}) > 1
        for x in route:
            sched[x]["bursts"][b]["resource_id"] = f"{resources[b]['resource'].capitalize()} {count[b]}"
            sched[x]["bursts"][b]["shared"] = shared
    return sched


def idle_of(r, sched, tasks):
    if not r["pred"]:
        return 0
    p = sched[r["pred"]]
    return r["starts"]["clearing"] - (p["starts"]["construction"] + tasks[p["job_id"]]["dur"]["construction"])


def burst_gap(sched, j, b):
    x = sched[j]["bursts"][b]
    if not x["pred"]:
        return 0
    p = sched[x["pred"]]["bursts"][b]
    return x["week"] - (p["week"] + p["weeks"])


def metrics(sched, tasks, c, coordinated):
    k, mid = c["costs"], mid_k(c)
    spec = {}
    for r in sched.values():
        for b, x in r["bursts"].items():
            spec[b] = spec.get(b, 0) + (0 if x["pred"] else 1)
    contractor = sum(1 for r in sched.values() if r.get("contractor")) // 2
    mobs = sum(1 for r in sched.values() if not r["pred"]) - contractor
    yards = len({r["yard"] if coordinated else (r["yard"], r["org"]) for r in sched.values()})
    idle = sum(idle_of(r, sched, tasks) for r in sched.values())
    bidle = sum(burst_gap(sched, j, b) for j, r in sched.items() for b in r["bursts"])
    bshift = sum(abs(x["moved"]) for r in sched.values() for x in r["bursts"].values())
    shared_bursts = sum(1 for r in sched.values() for x in r["bursts"].values() if x["pred"] and sched[x["pred"]]["org"] != r["org"])
    slip = sum(r["slip"] for r in sched.values())
    adv = sum(r["advance"] for r in sched.values())
    cost = (int(k["mobilization_k"]) * mobs + sum(mid[b] * n for b, n in spec.items()) + int(k["yard_k"]) * yards
            + int(k["idle_k_per_month"]) * idle + int(k["burst_idle_k_per_week"]) * bidle
            + int(k["slip_k_per_month"]) * slip + int(k["advance_k_per_month"]) * adv)
    return {"projects": len(sched), "mobilizations": mobs, "specialty_mobilizations": sum(spec.values()), "specialty": spec,
            "all_mobilizations": mobs + sum(spec.values()), "shared_bursts": shared_bursts, "contractor_pairs": contractor,
            "yards": yards, "idle_months": idle, "burst_idle_weeks": bidle, "burst_shift_weeks": bshift, "slip_months": slip,
            "slipped_projects": sum(1 for r in sched.values() if r["slip"] > 0),
            "late_projects": sum(1 for r in sched.values() if r["slip"] > tasks[r["job_id"]]["slip_limit"]),
            "advance_months": adv, "cost_k": cost}


def headline(base, coord, c):
    """Savings range from the same cost model: fewer mobilizations and yards at low/high unit costs, minus extra idle/slip/advance."""
    k = c["costs"]
    dm, dy = base["mobilizations"] - coord["mobilizations"], base["yards"] - coord["yards"]
    ds = {b: base["specialty"].get(b, 0) - coord["specialty"].get(b, 0) for b in c["bursts"]}
    extra = ((coord["idle_months"] - base["idle_months"]) * k["idle_k_per_month"]
             + (coord["burst_idle_weeks"] - base["burst_idle_weeks"]) * k["burst_idle_k_per_week"]
             + (coord["slip_months"] - base["slip_months"]) * k["slip_k_per_month"]
             + (coord["advance_months"] - base["advance_months"]) * k["advance_k_per_month"]) * 1000
    mob, yard = ASSUMPTIONS["mobilization_usd"], ASSUMPTIONS["yard_usd"]
    low = dm * mob["low"] + dy * yard["low"] + sum(n * c["bursts"][b]["mob_low_k"] * 1000 for b, n in ds.items()) - extra
    high = dm * mob["high"] + dy * yard["high"] + sum(n * c["bursts"][b]["mob_high_k"] * 1000 for b, n in ds.items()) - extra
    before, after = base["all_mobilizations"], coord["all_mobilizations"]
    return {"mobilizations_before": before, "mobilizations_after": after, "mobilizations_cut": before - after,
            "mobilizations_cut_pct": round(100 * (before - after) / before) if before else 0,
            "crew_mobilizations_before": base["mobilizations"], "crew_mobilizations_after": coord["mobilizations"],
            "specialty": {b: {"label": c["bursts"][b]["label"], "before": base["specialty"].get(b, 0), "after": coord["specialty"].get(b, 0)}
                          for b in c["bursts"] if base["specialty"].get(b, 0)},
            "shared_bursts": coord["shared_bursts"], "yards_before": base["yards"], "yards_after": coord["yards"],
            "savings_low": round(max(low, 0)), "savings_high": round(max(high, 0)),
            "late_projects": coord["late_projects"], "cost_cut_k": base["cost_k"] - coord["cost_k"]}


def months_text(n):
    return f"{abs(n)} month{'s' if abs(n) != 1 else ''}"


def weeks_text(n):
    return f"{abs(n)} week{'s' if abs(n) != 1 else ''}"


def move_reason(r, sched, tasks, c, origin, crews):
    """Why a project's work moved, from constraint checks on the solved schedule."""
    t = tasks[r["job_id"]]
    if r["shift"] == 0:
        return None
    when = "later" if r["shift"] > 0 else "earlier"
    partner = sched.get(r["pred"]) or sched.get(r["succ"])
    if partner:
        return f"{t['name']} crew work moves {months_text(r['shift'])} {when} so {r['crew']} can go straight between it and {partner['name']}."
    for b, x in r["bursts"].items():
        other = x["pred"] or x["succ"]
        if other and sched[other]["org"] != r["org"]:
            return (f"{t['name']} moves {months_text(r['shift'])} {when} so the {c['bursts'][b]['resource']} can go straight between it "
                    f"and {sched[other]['name']}.")
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


def burst_reason(b, first, then, sched, tasks, c):
    """A shared burst: which side moved from its typical slot and whether both stay on time."""
    size, moved = max((abs(sched[j]["bursts"][b]["moved"]), j) for j in (first, then))
    other = then if moved == first else first
    return {"rule": "shared_burst", "burst": b, "label": c["bursts"][b]["label"], "resource": c["bursts"][b]["resource"],
            "first": tasks[first]["short"], "then": tasks[then]["short"], "gap_weeks": burst_gap(sched, then, b),
            "moved": tasks[moved]["short"] if size else None, "other": tasks[other]["short"] if size else None,
            "moved_weeks": sched[moved]["bursts"][b]["moved"], "on_time": all(sched[j]["slip"] == 0 for j in (first, then))}


def decisions(data, sched, tasks, near, sites, c, base_sched, jc_sched=None):
    out = []
    for o in data["opps"]:
        a, b = o["job_a"], o["job_b"]
        if a not in sched or b not in sched:
            continue
        ra, rb = sched[a], sched[b]
        ok, info = near.get(tuple(sorted((a, b))), (False, {}))
        d = {"opportunity_id": o["id"], "a": ra["name"], "b": rb["name"], "job_a": a, "job_b": b, "eligible": ok, "reasons": [],
             "drive_min": info.get("drive_min"), "km": info.get("km"), "shared": []}
        for bt in sorted(set(ra["bursts"]) & set(rb["bursts"])):
            first = a if ra["bursts"][bt]["succ"] == b else b if rb["bursts"][bt]["succ"] == a else None
            if first:
                d["reasons"].append(burst_reason(bt, first, b if first == a else a, sched, tasks, c))
                d["shared"].append(c["bursts"][bt]["resource"])
        if not d["shared"]:
            if not ok and info.get("drive_min") is not None:
                d["reasons"].append({"rule": "drive_time", "minutes": info["drive_min"], "limit": c["crew_drive_min"]})
            elif not ok:
                d["reasons"].append({"rule": "distance", "km": info.get("km"), "limit": c["crew_km"]})
            else:
                d["reasons"].append({"rule": "not_chosen"})  # counterfactual computed on request
        if ra["yard"] == rb["yard"]:
            d["reasons"].append({"rule": "shared_yard", "yard": sites[ra["yard"]]["label"] if ra["yard"] in sites else ra["yard"]})
            d["shared"].append("yard")
        if jc_sched and jc_sched.get(a, {}).get("contractor") == b:
            d["reasons"].append({"rule": "joint_contractor"})
            d["contractor"] = True
        d["decision"] = "share" if d["shared"] else "no_share"
        out.append(d)
    return out


def sentence(reason, c=None):
    r = reason["rule"]
    lim = c or DEFAULTS
    if r == "shared_burst":
        stay = "both stay on time" if reason.get("on_time", True) else "both stay within their slip limits"
        if reason.get("moved"):
            when = "earlier" if reason["moved_weeks"] < 0 else "later"
            return (f"{reason['label'].capitalize()} at {reason['moved']} moved {weeks_text(reason['moved_weeks'])} {when} so the same "
                    f"{reason['resource']} serves {reason['other']}; saves one mobilization, {stay}.")
        after = "right after" if not reason["gap_weeks"] else f"{weeks_text(reason['gap_weeks'])} later"
        return (f"The same {reason['resource']} does the {reason['label']} at {reason['first']}, then at {reason['then']} "
                f"{after}; saves one mobilization, {stay}.")
    if r == "shared_crew":
        return (f"{reason['crew']} finishes {reason['first']} and starts {reason['then']} {months_text(reason['gap_months'])} later, "
                "saving one mobilization.")
    if r == "shared_yard":
        return f"Both use one staging yard {reason['yard']}."
    if r == "joint_contractor":
        return "With joint contracting on, one contractor serves both jobs while they run at the same time (an assumption)."
    if r == "drive_time":
        return f"The two sites are {reason['minutes']} minutes apart by road; the crew limit is {reason.get('limit') or lim['crew_drive_min']}."
    if r == "distance":
        return f"The two sites are {reason['km']} km apart; the crew limit is {reason.get('limit') or lim['crew_km']} km."
    if r == "max_slip":
        what = f"Sharing the {reason['resource']}" if reason.get("resource") else "Sharing"
        return f"{what} would push {reason['project']} {months_text(reason['needed_months'])} past in-service; limit is {reason['limit_months']}."
    if r == "costs_more":
        what = f"Sharing the {reason['resource']}" if reason.get("resource") else "Sharing"
        return f"{what} is allowed but raises total cost by ${reason['delta_k']:,}k ({reason['detail']}), so the solver kept them apart."
    if r == "infeasible":
        return "No schedule lets one specialty crew serve both, even with extra slip: crew capacity or a blackout blocks it."
    if r == "not_chosen":
        return "Close enough to share specialty crews, but the solver found a cheaper plan without it. Ask why for the exact reason."
    return r


def describe(d, c):
    d["sentence"] = " ".join(sentence(r, c) for r in d["reasons"])
    return d


# ---------- runs ----------

def solve_all(data, c):
    origin, tasks, near = prepare(data, c)
    crews = default_crews(tasks, origin)
    base_sched, problems, base_status = {}, [], "optimal"
    for org in sorted({t["org"] for t in tasks.values()}):  # each utility alone
        sub = {j: t for j, t in tasks.items() if t["org"] == org}
        model, v, _ = build(sub, near, data, c, origin, crews, coordinated=False)
        s, status = solve(model, c, c["time_limit_s"] * 3)  # the baseline must be proven optimal for the savings to be fair
        if status not in ("OPTIMAL", "FEASIBLE"):
            problems.append(org)
            continue
        base_status = base_status if status == "OPTIMAL" else "feasible"
        base_sched.update(extract(s, v, sub))
    if problems:
        return {"status": "infeasible", "problem": diagnose(data, c, problems)}, origin, tasks, near, crews
    base = metrics(crew_ids(base_sched, tasks, c), tasks, c, coordinated=False)
    free = interacting(tasks, near, data)
    pinned = {j: r for j, r in base_sched.items() if j not in free}  # nothing across the river to share with: keep its own optimum
    model, v, cost = build(tasks, near, data, c, origin, crews, coordinated=True, fixed=pinned)
    hint(model, v, base_sched, coordinated=True)
    model.Add(cost <= base["cost_k"])  # the baseline is a valid joint plan, so never do worse
    s, status = solve(model, c)
    if status not in ("OPTIMAL", "FEASIBLE"):
        return {"status": "infeasible", "problem": "the joint model found no schedule within the time limit"}, origin, tasks, near, crews
    gap_k = max(0, int(round(s.ObjectiveValue() - s.BestObjectiveBound())))  # how much cheaper a proven optimum could still be
    s = tidy(model, v, cost, s, c)
    sched = crew_ids(extract(s, v, tasks), tasks, c)
    coord = metrics(sched, tasks, c, coordinated=True)
    res = {"status": status.lower(), "baseline": base, "coordinated": coord, "headline": {**headline(base, coord, c), "free_projects": len(free)},
           "sched": sched, "base_sched": base_sched, "base_status": base_status, "gap_k": gap_k}
    if c["joint_contracting"]:  # optional assumption, solved on top of the strict plan so it can only add
        model, v, cost = build(tasks, near, data, c, origin, crews, coordinated=True, jc=True,
                               fixed={j: r for j, r in sched.items() if j not in free})
        hint(model, v, sched, coordinated=True)
        model.Add(cost <= coord["cost_k"])
        s, st = solve(model, c)
        if st in ("OPTIMAL", "FEASIBLE"):
            jc_sched = crew_ids(extract(s, v, tasks), tasks, c)
            jcm = metrics(jc_sched, tasks, c, coordinated=True)
            pairs = sorted({tuple(sorted((j, r["contractor"]))) for j, r in jc_sched.items() if r.get("contractor")})
            res["jc"] = {"metrics": jcm, "sched": jc_sched, "headline": {**headline(base, jcm, c), "contractor_pairs": len(pairs),
                         "pairs": [[tasks[a]["short"], tasks[b]["short"]] for a, b in pairs], "assumption": JC_NOTE}}
    return res, origin, tasks, near, crews


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


def burst_rows(r, t, origin, c, sched):
    out = []
    for b, x in r["bursts"].items():
        ph = c["bursts"][b]["phase"]
        start = month_date(origin, r["starts"][ph]) + timedelta(weeks=x["week"] - WPM * r["starts"][ph])
        partner = [sched[k]["name"] for k in (x["pred"], x["succ"]) if k and sched[k]["org"] != r["org"]]
        out.append({"burst": b, "label": c["bursts"][b]["label"], "resource": x.get("resource_id"), "shared": x.get("shared", False),
                    "start": start.isoformat(), "end": (start + timedelta(weeks=x["weeks"])).isoformat(), "partner": partner[0] if partner else None})
    return out


def schedule_rows(sched, tasks, origin, sites, base_sched, c):
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
                     "shift": r["shift"], "baseline_crew": base_sched.get(j, {}).get("crew"), "why": r.get("why"),
                     "bursts": burst_rows(r, t, origin, c, sched)})
    return rows


def saved_constraints(c):
    return {**{k: v for k, v in c.items() if k != "time_limit_s"}, "model": MODEL}


def run(conn, constraints=None):
    conn.execute(TABLE_SQL)
    c = merge(constraints)
    data = load(conn, c["yard_km"])
    ids = [j["id"] for j in data["jobs"]]
    if not ids:
        return {"status": "empty", "problem": "no long-range opportunities to plan"}
    res, origin, tasks, near, crews = solve_all(data, c)
    saved = saved_constraints(c)
    if res["status"] == "infeasible":
        row = conn.execute("INSERT INTO joint_plan (constraints, job_ids, status, problem) VALUES (%s, %s, 'infeasible', %s) RETURNING id",
                           (json.dumps(saved), ids, res["problem"])).fetchone()
        return {"plan_id": row["id"], "status": "infeasible", "problem": res["problem"], "constraints": saved}
    sched = res["sched"]
    for r in sched.values():
        r["why"] = move_reason(r, sched, tasks, c, origin, crews)
    jc = res.get("jc")
    decs = [describe(d, c) for d in decisions(data, sched, tasks, near, data["sites"], c, res["base_sched"], jc and jc["sched"])]
    rows = schedule_rows(sched, tasks, origin, data["sites"], res["base_sched"], c)
    crew_table = {org: {str(y): capacity(org, y, crews, c["crew_counts"]) for y in years} for org, years in crews.items()}
    head = {**res["headline"], "crews": crew_table, "joint_contracting": jc["headline"] if jc else None}
    head["solver"] = {"separate": res["base_status"], "coordinated": res["status"], "coordinated_gap_k": res["gap_k"]}
    out = {"status": res["status"], "baseline": res["baseline"], "coordinated": res["coordinated"], "headline": head}
    row = conn.execute("""INSERT INTO joint_plan (constraints, job_ids, status, baseline, coordinated, headline, schedule, decisions)
                          VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id, run_at""",
                       (json.dumps(saved), ids, res["status"], json.dumps(res["baseline"]), json.dumps(res["coordinated"]),
                        json.dumps(head), json.dumps(rows), json.dumps(decs))).fetchone()
    return {"plan_id": row["id"], "run_at": row["run_at"], "constraints": saved, **out, "schedule": rows, "decisions": decs}


def as_result(row):
    return {"plan_id": row["id"], "run_at": row["run_at"], "constraints": row["constraints"], "status": row["status"],
            "problem": row["problem"], "baseline": row["baseline"], "coordinated": row["coordinated"], "headline": row["headline"],
            "schedule": row["schedule"] or [], "decisions": row["decisions"] or []}


def latest(conn):
    conn.execute(TABLE_SQL)
    row = conn.execute("SELECT * FROM joint_plan ORDER BY id DESC LIMIT 1").fetchone()
    ids = sorted(j["id"] for j in conn.execute(JOBS_SQL).fetchall())
    stale = not row or sorted(row["job_ids"]) != ids or row["constraints"].get("model") != MODEL  # data or model changed
    if stale:
        return run(conn, {k: v for k, v in row["constraints"].items() if k != "model"} if row else None)
    return as_result(row)


def counterfactual(conn, plan, d):
    """Re-solve with a specialty burst forced shared and slip relaxed for the two projects, then name what binds."""
    c = merge({k: v for k, v in plan["constraints"].items() if k != "model"})
    base_limits = {j: int(c["slip_overrides"].get(j, c["max_slip_months"])) for j in (d["job_a"], d["job_b"])}
    relaxed = merge({**{k: v for k, v in plan["constraints"].items() if k != "model"},
                     "slip_overrides": {**c["slip_overrides"], d["job_a"]: RELAXED_SLIP, d["job_b"]: RELAXED_SLIP}})
    data = load(conn, c["yard_km"])
    origin, tasks, near = prepare(data, relaxed)
    crews = default_crews(tasks, origin)
    mid = mid_k(c)
    common = sorted(set(tasks[d["job_a"]]["bursts"]) & set(tasks[d["job_b"]]["bursts"]), key=lambda b: -mid[b])[:2]
    results = []
    for b in common:  # the most valuable shared resources first
        model, v, _ = build(tasks, near, data, relaxed, origin, crews, coordinated=True, forced=[(b, d["job_a"], d["job_b"])])
        s, status = solve(model, relaxed, 4)
        if status not in ("OPTIMAL", "FEASIBLE"):
            continue
        sched = extract(s, v, tasks)
        over = [(sched[j]["slip"] - base_limits[j], j) for j in base_limits if sched[j]["slip"] > base_limits[j]]
        if over:
            _, j = max(over)
            return {"rule": "max_slip", "resource": c["bursts"][b]["resource"], "project": tasks[j]["short"],
                    "needed_months": sched[j]["slip"], "limit_months": base_limits[j]}
        cf = metrics(crew_ids(sched, tasks, c), tasks, c, coordinated=True)
        now = plan["coordinated"]
        parts = [f"{label} {cf[key] - now[key]:+d}" for key, label in (
            ("specialty_mobilizations", "specialty mobilizations"), ("mobilizations", "crew mobilizations"), ("idle_months", "idle months"),
            ("burst_idle_weeks", "specialty standby weeks"), ("burst_shift_weeks", "weeks bursts moved"), ("slip_months", "slip months"), ("advance_months", "months started early"),
            ("yards", "yards")) if cf.get(key, 0) != now.get(key, 0)]
        results.append({"rule": "costs_more", "resource": c["bursts"][b]["resource"], "delta_k": max(cf["cost_k"] - now["cost_k"], 0),
                        "detail": ", ".join(parts) or "same counts"})
    return results[0] if results else {"rule": "infeasible"}


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
                describe(d, merge({k: v for k, v in plan["constraints"].items() if k != "model"}))
                changed = True
    if changed:
        conn.execute("UPDATE joint_plan SET decisions = %s WHERE id = %s", (json.dumps(plan["decisions"]), plan["plan_id"]))
    projects = [{"job_id": r["job_id"], "name": r["name"], "crew": r["crew"], "shift": r["shift"], "slip": r["slip"],
                 "why": r["why"], "bursts": r.get("bursts", [])} for r in plan["schedule"] if q and q in r["name"].lower()]
    return {"plan_id": plan["plan_id"], "constraints": plan["constraints"], "decisions": hits, "projects": projects}


def validate(conn, constraints):
    """Check planner or Crewly constraints against the data and echo them in structured form."""
    constraints = {k: v for k, v in (constraints or {}).items() if k != "model"}
    c = merge(constraints)
    jobs = conn.execute(JOBS_SQL).fetchall()
    orgs = {j["org_id"] for j in jobs}
    notes, errors, slips = [], [], {}
    for name, months in constraints.get("slip_overrides", {}).items():
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
    for name in constraints.get("bursts", {}) or {}:
        if name not in BURSTS:
            errors.append(f"unknown specialty burst '{name}' (use {', '.join(BURSTS)})")
    for name, b in c["bursts"].items():
        lo, hi = b["window"]
        if not (0 <= lo < hi <= 1):
            errors.append(f"{b['label']} window must be fractions with 0 <= start < end <= 1")
        if b["mob_low_k"] < 0 or b["mob_low_k"] > b["mob_high_k"]:
            errors.append(f"{b['label']} cost range must be 0 <= low <= high")
        if any(b[k] != BURSTS[name][k] for k in BURST_KEYS):  # only mention assumptions that differ from the defaults
            notes.append(f"{b['label'].capitalize()}: {weeks_text(b['weeks'])} in {b['phase']} ({round(lo * 100)}-{round(hi * 100)}%), "
                         f"${b['mob_low_k']:,.0f}k-${b['mob_high_k']:,.0f}k per mobilization" + ("" if b["enabled"] else ", turned off"))
    if c["burst_gap_weeks"] < 0:
        errors.append("burst gap cannot be negative")
    if "burst_gap_weeks" in constraints:
        notes.append(f"A shared specialty crew may wait up to {weeks_text(c['burst_gap_weeks'])} between jobs")
    if constraints.get("joint_contracting"):
        notes.append("Joint contracting on: " + JC_NOTE)
    return {"constraints": saved_constraints(c), "notes": notes, "errors": errors, "valid": not errors}
