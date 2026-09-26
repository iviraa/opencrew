from datetime import date

from app.engine import plan


def job(id, org, start, end, name=None):
    return {"id": id, "org_id": org, "name": name or id, "start_at": start, "in_service": end}


def data(jobs, pairs, opps=()):
    sites = {f"job:{j['id']}": {"id": f"job:{j['id']}", "label": f"at {j['name']}", "lon": 0, "lat": 0} for j in jobs}
    near = {j["id"]: [f"job:{j['id']}"] for j in jobs}
    return {"jobs": jobs, "opps": list(opps), "pairs": [{"a": a, "b": b, "km": km} for a, b, km in pairs], "sites": sites, "near": near}


def solve(d, **cons):
    c = plan.merge({"time_limit_s": 5, **cons})
    res, *_ = plan.solve_all(d, c)
    return res


def test_durations_fill_the_window():
    for total in (4, 7, 18, 36, 61):
        d = plan.durations(total)
        assert sum(d.values()) == total and min(d.values()) >= 1


def test_cross_utility_chain_saves_a_mobilization():
    # DESC crew work ends right before GPC's nearby job starts; no utility can chain alone
    d = data([job("desc-a", "desc", date(2024, 1, 1), date(2025, 1, 1)), job("gpc-b", "gpc", date(2024, 9, 1), date(2025, 9, 1))],
             [("desc-a", "gpc-b", 5.0)], [{"id": 1, "job_a": "desc-a", "job_b": "gpc-b", "drive_min": 20}])
    res = solve(d, max_advance_months=0)
    assert res["baseline"]["mobilizations"] == 2
    assert res["coordinated"]["mobilizations"] == 1 and res["coordinated"]["shared_crews"] == 1
    assert res["coordinated"]["cost_k"] <= res["baseline"]["cost_k"]
    assert res["headline"]["mobilizations_cut_pct"] == 50 and res["headline"]["late_projects"] == 0


def test_drive_time_blocks_sharing():
    d = data([job("desc-a", "desc", date(2024, 1, 1), date(2025, 1, 1)), job("gpc-b", "gpc", date(2024, 9, 1), date(2025, 9, 1))],
             [("desc-a", "gpc-b", 5.0)], [{"id": 1, "job_a": "desc-a", "job_b": "gpc-b", "drive_min": 70}])
    res = solve(d, max_advance_months=0)
    assert res["coordinated"]["mobilizations"] == 2  # 70 minutes by road is over the 45 minute crew limit


def test_coordinated_never_worse_and_shared_yard():
    jobs = [job("desc-a", "desc", date(2024, 1, 1), date(2026, 1, 1)), job("gpc-b", "gpc", date(2024, 1, 1), date(2026, 1, 1))]
    d = data(jobs, [("desc-a", "gpc-b", 3.0)], [{"id": 1, "job_a": "desc-a", "job_b": "gpc-b", "drive_min": 10}])
    d["sites"]["opp:1"] = {"id": "opp:1", "label": "between", "lon": 0, "lat": 0}
    d["near"] = {"desc-a": ["job:desc-a", "opp:1"], "gpc-b": ["job:gpc-b", "opp:1"]}
    res = solve(d)
    assert res["baseline"]["yards"] == 2 and res["coordinated"]["yards"] == 1
    assert res["coordinated"]["cost_k"] <= res["baseline"]["cost_k"]


def test_blackout_moves_energization():
    d = data([job("desc-a", "desc", date(2024, 1, 1), date(2025, 7, 1), "Okatie sub")], [])
    res = solve(d, blackouts=[{"site": "Okatie", "months": [5, 6, 7, 8], "phase_kind": "energization"}], max_advance_months=3)
    st = res["sched"]["desc-a"]["starts"]
    origin = date(2023, 10, 1)  # three months of allowed advance before the filed start
    t = plan.prepare(d, plan.merge({"max_advance_months": 3}))[1]["desc-a"]
    months = {plan.month_date(origin, st["energization"] + i).month for i in range(t["dur"]["energization"])}
    assert not months & {5, 6, 7, 8}


def test_slip_limit_and_crew_counts_make_it_infeasible():
    jobs = [job("desc-a", "desc", date(2024, 1, 1), date(2025, 1, 1)), job("desc-b", "desc", date(2024, 1, 1), date(2025, 1, 1))]
    res = solve(data(jobs, []), crew_counts={"desc": {"2024": 1}}, max_slip_months=0, max_advance_months=0)
    assert res["status"] == "infeasible" and "relaxing the slip limit" in res["problem"]


def test_sentences():
    assert plan.sentence({"rule": "max_slip", "project": "Jasper – Okatie", "needed_months": 4, "limit_months": 2}) == \
        "Sharing would push Jasper – Okatie 4 months past in-service; limit is 2."
    assert plan.sentence({"rule": "drive_time", "minutes": 72, "limit": 45}) == "The two sites are 72 minutes apart by road; the crew limit is 45."
    assert "saving one mobilization" in plan.sentence({"rule": "shared_crew", "crew": "DESC crew 1", "first": "A", "then": "B", "gap_months": 1})
