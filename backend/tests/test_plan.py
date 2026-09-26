from datetime import date

from app.engine import plan


def job(id, org, start, end, name=None, job_type="line_upgrade"):
    return {"id": id, "org_id": org, "name": name or id, "job_type": job_type, "start_at": start, "in_service": end}


def data(jobs, pairs, opps=()):
    sites = {f"job:{j['id']}": {"id": f"job:{j['id']}", "label": f"at {j['name']}", "lon": 0, "lat": 0} for j in jobs}
    near = {j["id"]: [f"job:{j['id']}"] for j in jobs}
    return {"jobs": jobs, "opps": list(opps), "pairs": [{"a": a, "b": b, "km": km} for a, b, km in pairs], "sites": sites, "near": near}


def solve(d, **cons):
    c = plan.merge({"time_limit_s": 5, **cons})
    res, *_ = plan.solve_all(d, c)
    return res


def twins(drive_min, job_type="substation"):
    """A DESC and a GPC job running at the same time a short distance apart."""
    jobs = [job("desc-a", "desc", date(2024, 1, 1), date(2025, 7, 1), job_type=job_type),
            job("gpc-b", "gpc", date(2024, 1, 1), date(2025, 7, 1), job_type=job_type)]
    return data(jobs, [("desc-a", "gpc-b", 5.0)], [{"id": 1, "job_a": "desc-a", "job_b": "gpc-b", "drive_min": drive_min}])


def test_durations_fill_the_window():
    for total in (4, 7, 18, 36, 61):
        d = plan.durations(total)
        assert sum(d.values()) == total and min(d.values()) >= 1


def test_general_crews_stay_with_their_utility():
    # DESC crew work ends right before GPC's nearby job starts; strict mode never lends a general crew across utilities
    d = data([job("desc-a", "desc", date(2024, 1, 1), date(2025, 1, 1)), job("gpc-b", "gpc", date(2024, 9, 1), date(2025, 9, 1))],
             [("desc-a", "gpc-b", 5.0)], [{"id": 1, "job_a": "desc-a", "job_b": "gpc-b", "drive_min": 20}])
    res = solve(d, max_advance_months=0)
    assert res["baseline"]["mobilizations"] == res["coordinated"]["mobilizations"] == 2


def test_shared_specialty_crews_save_mobilizations():
    res = solve(twins(20))
    base, coord, head = res["baseline"], res["coordinated"], res["headline"]
    assert base["specialty_mobilizations"] == 6 and base["shared_bursts"] == 0  # heavy haul, crane, commissioning each
    assert coord["specialty_mobilizations"] < base["specialty_mobilizations"] and coord["shared_bursts"] > 0
    assert coord["cost_k"] <= base["cost_k"] and head["late_projects"] == 0 and head["mobilizations_cut"] > 0
    assert head["savings_low"] > 0 and head["savings_low"] <= head["savings_high"]


def test_drive_time_blocks_sharing():
    res = solve(twins(70))
    assert res["coordinated"]["specialty_mobilizations"] == res["baseline"]["specialty_mobilizations"]  # 70 min is over 45
    assert res["coordinated"]["shared_bursts"] == 0 and res["headline"]["mobilizations_cut"] == 0


def test_bursts_respect_windows_and_deadlines():
    d = twins(20, "new_line")
    c = plan.merge({"time_limit_s": 5})
    res, origin, tasks, near, crews = plan.solve_all(d, c)
    for j, r in res["sched"].items():
        t = tasks[j]
        assert r["slip"] <= t["slip_limit"]
        for b, x in r["bursts"].items():
            lo, hi, n, _ = t["bursts"][b]
            start = plan.WPM * r["starts"][c["bursts"][b]["phase"]]
            assert start + lo <= x["week"] and x["week"] + n <= start + hi
    assert set(tasks["desc-a"]["bursts"]) == {"heavy_haul", "crane_lift", "wire_stringing", "commissioning"}


def test_joint_contracting_is_off_by_default_and_only_adds():
    assert "jc" not in solve(twins(20))
    res = solve(twins(20), joint_contracting=True)
    jc = res["jc"]
    assert jc["metrics"]["cost_k"] <= res["coordinated"]["cost_k"]
    assert jc["metrics"]["mobilizations"] < res["coordinated"]["mobilizations"] and jc["headline"]["contractor_pairs"] == 1
    assert "one contractor" in jc["headline"]["assumption"]


def test_coordinated_never_worse_and_shared_yard():
    jobs = [job("desc-a", "desc", date(2024, 1, 1), date(2026, 1, 1)), job("gpc-b", "gpc", date(2024, 1, 1), date(2026, 1, 1))]
    d = data(jobs, [("desc-a", "gpc-b", 3.0)], [{"id": 1, "job_a": "desc-a", "job_b": "gpc-b", "drive_min": 10}])
    d["sites"]["opp:1"] = {"id": "opp:1", "label": "between", "lon": 0, "lat": 0}
    d["near"] = {"desc-a": ["job:desc-a", "opp:1"], "gpc-b": ["job:gpc-b", "opp:1"]}
    res = solve(d)
    assert res["baseline"]["yards"] == 2 and res["coordinated"]["yards"] == 1
    assert res["coordinated"]["cost_k"] <= res["baseline"]["cost_k"]


def test_no_shared_yard_across_a_long_drive():
    jobs = [job("desc-a", "desc", date(2024, 1, 1), date(2026, 1, 1)), job("gpc-b", "gpc", date(2024, 1, 1), date(2026, 1, 1))]
    d = data(jobs, [("desc-a", "gpc-b", 3.0)], [{"id": 1, "job_a": "desc-a", "job_b": "gpc-b", "drive_min": 60}])
    d["sites"]["opp:1"] = {"id": "opp:1", "label": "between", "lon": 0, "lat": 0}
    d["near"] = {"desc-a": ["job:desc-a", "opp:1"], "gpc-b": ["job:gpc-b", "opp:1"]}
    assert solve(d)["coordinated"]["yards"] == 2  # 3 km apart but an hour by road


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
    assert plan.sentence({"rule": "max_slip", "resource": "stringing crew", "project": "Jasper–Okatie", "needed_months": 4,
                          "limit_months": 2}) == "Sharing the stringing crew would push Jasper–Okatie 4 months past in-service; limit is 2."
    assert plan.sentence({"rule": "shared_burst", "label": "crane lift", "resource": "crane", "first": "Okatie–Bluffton",
                          "then": "Goshen–Kraft", "gap_weeks": 0, "moved": "Goshen–Kraft", "other": "Okatie–Bluffton", "moved_weeks": -3,
                          "on_time": True}) == ("Crane lift at Goshen–Kraft moved 3 weeks earlier so the same crane serves Okatie–Bluffton; "
                                                "saves one mobilization, both stay on time.")
    assert plan.sentence({"rule": "drive_time", "minutes": 72, "limit": 45}) == "The two sites are 72 minutes apart by road; the crew limit is 45."
    assert "right after" in plan.sentence({"rule": "shared_burst", "label": "heavy haul", "resource": "heavy-haul rig", "first": "A",
                                           "then": "B", "gap_weeks": 0, "moved": None, "moved_weeks": 0})
    assert plan.short("SAV: GOSHEN (SAV) - KRAFT 115KV LINE REBUILD") == "Goshen–Kraft"
