import hashlib
import json
import math
import re
from datetime import timedelta

from ortools.sat.python import cp_model

from app.storm import briefing

DEFAULTS = {"crews_gpc": 8, "crews_desc": 4, "repair_h": 6, "extra_incident_h": 2, "max_repair_h": 12, "max_drive_min": 90, "solve_s": 5}  # storm crews relocate for days, so help travels farther than the 45 min daily-commute rule
ORG_NAME = briefing.ORG_NAME
MODEL = "restoration-v3"  # bump when the plan's shape or math changes so cached plans refresh
TABLE_SQL = "CREATE TABLE IF NOT EXISTS storm_plan (fingerprint TEXT PRIMARY KEY, result JSONB, created_at TIMESTAMPTZ DEFAULT now())"
JOBS_SQL = """
SELECT j.id, j.org_id, j.name, j.description, j.confidence, lower(j.work_window) AS reported,
       ST_X(j.geom::geometry) AS lon, ST_Y(j.geom::geometry) AS lat
FROM job j WHERE j.horizon = 'emergency' AND lower(j.work_window) <= %(t)s ORDER BY lower(j.work_window), j.id
"""
NEAREST_ASSET_SQL = """
SELECT ST_X(geom::geometry) AS lon, ST_Y(geom::geometry) AS lat FROM asset WHERE org_id = %(org)s
ORDER BY geom <-> ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography LIMIT 1
"""


def minutes_text(m):
    m = round(m)
    return f"{m // 60} h {m % 60} min" if m >= 60 else f"{m} min"


def load(conn, t, opt):
    jobs = []
    for r in conn.execute(JOBS_SQL, {"t": t}).fetchall():
        n = int(m.group(1)) if (m := re.match(r"(\d+) incident", r["description"] or "")) else 1
        repair = min(opt["max_repair_h"], opt["repair_h"] + opt["extra_incident_h"] * (n - 1))
        weight = min(5, n) * (1.0 if r["confidence"] >= 0.5 else 0.5)  # unverified damage counts half
        jobs.append({**r, "incidents": n, "repair_min": int(repair * 60), "weight": weight})
    return jobs


def yards(conn, jobs):
    """Once winds drop, crews move to a yard at their own substation nearest each cluster of damage."""
    out = {}
    for org in ("gpc", "desc"):
        own = [{"lon": j["lon"], "lat": j["lat"]} for j in jobs if j["org_id"] == org]
        if not own:
            continue
        k = 1 if len(own) < 6 else 2 if len(own) <= 15 else 3
        for c in briefing.clusters(own, k):
            a = conn.execute(NEAREST_ASSET_SQL, {"org": org, "lon": c["lon"], "lat": c["lat"]}).fetchone()
            out.setdefault(org, []).append({"lon": a["lon"], "lat": a["lat"], "county": briefing.county_of(a["lon"], a["lat"]), "damage": c["substations"]})
    return out


def crews_for(yard_map, opt):
    """Split each utility's crews across its yards in proportion to the damage there (largest remainder)."""
    crews = []
    for org in ("gpc", "desc"):
        ys, n = yard_map.get(org) or [], int(opt[f"crews_{org}"])
        if not ys:
            continue
        total = sum(y["damage"] for y in ys)
        share = [n * y["damage"] / total for y in ys]
        count = [int(x) for x in share]
        for i in sorted(range(len(ys)), key=lambda i: share[i] - count[i], reverse=True)[:n - sum(count)]:
            count[i] += 1
        k = 0
        for y, c in zip(ys, count):
            for _ in range(c):
                k += 1
                crews.append({"id": f"{org}-{k}", "org": org, "label": f"{ORG_NAME[org]} crew {k}", "yard": y})
    return crews


def solve(jobs, crews, drive, t0, opt, mutual):
    m = cp_model.CpModel()
    horizon = max(j["release"] for j in jobs) + sum(j["repair_min"] + 240 for j in jobs)
    x, s, e, ends = {}, {}, {}, {}
    per_crew = {c["id"]: [] for c in crews}
    for jj, j in enumerate(jobs):
        ends[jj] = m.NewIntVar(0, horizon, f"end{jj}")
        opts = []
        for cc, c in enumerate(crews):
            d = drive[cc][jj]
            cross = c["org"] != j["org_id"]
            if cross and (not mutual or d > opt["max_drive_min"]):
                continue  # own jobs always allowed; other utility's only within the drive limit with mutual aid on
            dur = int(2 * d) + j["repair_min"]  # drive out, repair, drive back to the yard
            b = m.NewBoolVar(f"x{cc}_{jj}")
            st = m.NewIntVar(j["release"], horizon, f"s{cc}_{jj}")
            en = m.NewIntVar(0, horizon, f"e{cc}_{jj}")
            per_crew[c["id"]].append(m.NewOptionalIntervalVar(st, dur, en, b, f"i{cc}_{jj}"))
            m.Add(ends[jj] == en).OnlyEnforceIf(b)
            x[cc, jj], s[cc, jj], e[cc, jj] = b, st, en
            opts.append(b)
        if not opts:
            return None
        m.AddExactlyOne(opts)
    for ivs in per_crew.values():
        m.AddNoOverlap(ivs)
    obj = sum(int(j["weight"] * 10) * ends[jj] for jj, j in enumerate(jobs))
    m.Minimize(obj)
    sv = cp_model.CpSolver()
    sv.parameters.max_time_in_seconds = opt["solve_s"]
    sv.parameters.num_workers = 8
    sv.parameters.random_seed = 0
    status = sv.Solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    chosen = {jj: cc for (cc, jj), b in x.items() if sv.Value(b)}
    return {"status": sv.StatusName(status).lower(), "objective": sv.ObjectiveValue(), "chosen": chosen,
            "start": {jj: sv.Value(s[cc, jj]) for jj, cc in chosen.items()}, "end": {jj: sv.Value(ends[jj]) for jj in chosen}}


def summary(res, jobs):
    waits = [(res["end"][jj] - j["release"]) / 60 for jj, j in enumerate(jobs)]
    weighted = sum(j["weight"] * w for j, w in zip(jobs, waits)) / sum(j["weight"] for j in jobs)  # what the solver minimizes
    return {"done_hours": round(max(res["end"].values()) / 60, 1), "avg_wait_hours": round(sum(waits) / len(waits), 1),
            "weighted_wait_hours": round(weighted, 2), "status": res["status"]}


def build(conn, t, scenario="helene", mutual_aid=True, options=None):
    opt = {**DEFAULTS, **{k: float(v) for k, v in (options or {}).items() if k in DEFAULTS}}
    if scenario != "helene":
        return {"jobs": 0, "headline": "No storm damage to plan for right now."}
    jobs = load(conn, t, opt)
    if not jobs:
        return {"jobs": 0, "headline": "No damage reported near either utility yet. Crews stay staged."}
    t0 = min(j["reported"] for j in jobs)
    for j in jobs:
        j["release"] = int((j["reported"] - t0).total_seconds() // 60)
    yard_map = yards(conn, jobs)
    crews = crews_for(yard_map, opt)
    fp = hashlib.sha1(json.dumps([MODEL, t.isoformat(), opt, [(j["id"], j["release"]) for j in jobs],
                                  [(c["id"], round(c["yard"]["lon"], 4), round(c["yard"]["lat"], 4)) for c in crews]], sort_keys=True).encode()).hexdigest()
    conn.execute(TABLE_SQL)
    hit = conn.execute("SELECT result FROM storm_plan WHERE fingerprint = %s", (fp,)).fetchone()
    result = hit["result"] if hit else None
    if not result:
        result = plan(jobs, crews, t0, opt)
        conn.execute("INSERT INTO storm_plan (fingerprint, result) VALUES (%s, %s) ON CONFLICT DO NOTHING", (fp, json.dumps(result, default=str)))
    shown = result["mutual"] if mutual_aid else result["alone"]
    return {**{k: v for k, v in result.items() if k not in ("mutual", "alone")}, "mutual_aid": mutual_aid,
            "routes": shown["routes"], "explanations": shown["explanations"]}


def plan(jobs, crews, t0, opt):
    ypts = [(c["yard"]["lon"], c["yard"]["lat"]) for c in crews]
    uniq = sorted(set(ypts))
    table = briefing.drive_table(uniq, [(j["lon"], j["lat"]) for j in jobs])
    drive = []
    for c, yp in zip(crews, ypts):
        row = table[uniq.index(yp)]
        drive.append([m if m is not None else briefing.km(*yp, j["lon"], j["lat"]) * 1.3 / 50 * 60 for m, j in zip(row, jobs)])  # no route: 50 km/h on a 1.3x detour
    alone = solve(jobs, crews, drive, t0, opt, mutual=False)
    mutual = solve(jobs, crews, drive, t0, opt, mutual=True)
    if mutual is None or mutual["objective"] > alone["objective"]:
        mutual = alone  # the alone plan is always allowed with mutual aid, so never report a worse one
    a, mu = summary(alone, jobs), summary(mutual, jobs)
    moves = sum(1 for jj, cc in mutual["chosen"].items() if crews[cc]["org"] != jobs[jj]["org_id"])
    faster = round(a["done_hours"] - mu["done_hours"], 1)
    headline = (f"With mutual aid, all repairs are done {faster:g} hours sooner; the average wait drops from {a['avg_wait_hours']:g} to {mu['avg_wait_hours']:g} hours."
                if faster > 0 or mu["avg_wait_hours"] < a["avg_wait_hours"] else
                "Mutual aid does not speed things up here: each utility's own crews are already closest to its damage.")
    return {"at_first_report": t0.isoformat(), "jobs": len(jobs), "crews": {o: sum(c["org"] == o for c in crews) for o in ("gpc", "desc")},
            "alone": {**a, **detail(alone, jobs, crews, drive, t0)}, "mutual": {**mu, **detail(mutual, jobs, crews, drive, t0)},
            "summary": {"alone": a, "mutual_aid": mu, "cross_utility_jobs": moves}, "headline": headline,
            "assumptions": {"crews_gpc": {"value": opt["crews_gpc"], "label": "Georgia Power repair crews"},
                            "crews_desc": {"value": opt["crews_desc"], "label": "Dominion Energy SC repair crews"},
                            "repair_h": {"value": opt["repair_h"], "label": "Hours to repair one damaged site"},
                            "max_drive_min": {"value": opt["max_drive_min"], "label": "Longest drive for help across utilities"},
                            "yards": {"value": "nearest own substation to each damage cluster", "label": "Where crews work from once winds drop"}}}


def detail(res, jobs, crews, drive, t0):
    routes, explanations = {}, []
    order = sorted(res["chosen"].items(), key=lambda kv: res["start"][kv[0]])
    for jj, cc in order:
        c, j = crews[cc], jobs[jj]
        start, end = t0 + timedelta(minutes=res["start"][jj]), t0 + timedelta(minutes=res["end"][jj])
        cross = c["org"] != j["org_id"]
        r = routes.setdefault(c["id"], {"crew": c["label"], "org": c["org"], "yard": c["yard"], "jobs": []})
        first = not r["jobs"]
        r["jobs"].append({"job_id": j["id"], "name": j["name"], "org": j["org_id"], "lon": j["lon"], "lat": j["lat"], "start": start.isoformat(),
                          "end": end.isoformat(), "drive_min": round(drive[cc][jj]), "cross_utility": cross})
        wait_h = (res["end"][jj] - j["release"]) / 60
        if cross:
            own = [drive[k][jj] for k, o in enumerate(crews) if o["org"] == j["org_id"]]
            near = f"{ORG_NAME[j['org_id']]}'s nearest crew is {minutes_text(min(own))} out" if own else f"{ORG_NAME[j['org_id']]} has no crew staged nearby"
            text = f"{c['label']} goes to {j['name']} {'first' if first else 'next'}: {minutes_text(drive[cc][jj])} away, and {near}."
        else:
            text = f"{c['label']} takes {j['name']}: {minutes_text(drive[cc][jj])} from its {c['yard']['county']} yard, fixed {wait_h:.0f} hours after it was reported."
        explanations.append({"job_id": j["id"], "crew": c["label"], "crew_id": c["id"], "cross_utility": cross, "sentence": text})
    return {"routes": list(routes.values()), "explanations": explanations}
