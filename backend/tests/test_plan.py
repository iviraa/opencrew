from datetime import datetime, timezone

from app.engine.plan import construction, decide, min_delay, overlap_months, sentence


def dt(y, m=1):
    return datetime(y, m, 1, tzinfo=timezone.utc)


def row(id, a, b, a_win, b_win, low=100000, high=200000, drive=None, ja=None, jb=None):
    return {"id": id, "a_name": a, "b_name": b, "job_a": ja or a, "job_b": jb or b, "a_org": "desc", "b_org": "gpc",
            "a_start": a_win[0], "a_end": a_win[1], "b_start": b_win[0], "b_end": b_win[1],
            "savings_low": low, "savings_high": high, "score": 0.5, "drive_min": drive}


def test_construction_is_middle_phase():
    s, e = construction(dt(2020), dt(2030))
    assert abs((s - dt(2023, 7)).days) <= 2 and abs((e - dt(2029)).days) <= 2  # 35% and 90% of ten years


def test_min_delay_whole_months():
    fixed = (dt(2025, 1), dt(2026, 1))
    assert min_delay(fixed, (dt(2024, 6), dt(2025, 6)), 3) == 0  # already overlaps 5 months
    assert min_delay(fixed, (dt(2024, 1), dt(2024, 12)), 3) == 4  # needs to move into 2025 by 3 months
    assert min_delay(fixed, (dt(2027, 1), dt(2028, 1)), 3) is None  # later project cannot be delayed backwards
    assert min_delay(fixed, (dt(2024, 1), dt(2024, 3)), 3) is None  # too short to ever overlap 3 months
    assert round(overlap_months(fixed, (dt(2025, 7), dt(2027, 1)))) == 6


def test_delay_limit_rejects_with_numbers():
    rows = [row(1, "Jasper", "McIntosh", (dt(2020), dt(2024)), (dt(2024, 6), dt(2027)))]
    _, _, out = decide(rows, {"max_delay_months": 2})
    d = out[0]
    assert d["decision"] == "no_share"
    r = d["reasons"][0]
    assert r["rule"] == "max_delay" and r["limit_months"] == 2 and r["needed_months"] > 2
    assert "your limit is 2" in d["sentence"]


def test_drive_rule_and_unknown_drive():
    win = (dt(2020), dt(2024))
    _, _, out = decide([row(1, "A", "B", win, win, drive=72), row(2, "C", "D", win, win, drive=None)])
    by = {d["opportunity_id"]: d for d in out}
    assert by[1]["decision"] == "no_share" and by[1]["reasons"] == [{"rule": "drive_time", "minutes": 72, "limit": 45}]
    assert "72 minutes apart by road; your limit is 45" in by[1]["sentence"]
    assert by[2]["decision"] == "share" and by[2]["notes"] == [{"rule": "drive_unknown"}]


def test_crew_goes_to_bigger_saving():
    win = (dt(2020), dt(2024))
    rows = [row(1, "Jasper", "McIntosh", win, win, 100000, 100000), row(2, "Jasper", "Goshen", win, win, 300000, 400000)]
    _, summary, out = decide(rows)
    by = {d["opportunity_id"]: d for d in out}
    assert by[2]["decision"] == "share"
    r = by[1]["reasons"][0]
    assert r == {"rule": "crew_taken", "project": "Jasper", "job_id": "Jasper", "by_opportunity": 2,
                 "their_savings_mid": 350000, "this_savings_mid": 100000}
    assert summary["shared"] == 1 and summary["rejected_by"]["crew_taken"] == 1


def test_accepted_shift_sentence():
    rows = [row(1, "Jasper", "McIntosh", (dt(2020), dt(2024)), (dt(2023, 3), dt(2026)))]
    _, _, out = decide(rows, {"max_delay_months": 12})
    d = out[0]
    assert d["decision"] == "share" and d["shift"]["months"] > 0
    assert d["sentence"].startswith(f"Share crews by delaying {d['shift']['project']} {d['shift']['months']} month")


def test_sentences():
    assert sentence({"rule": "max_delay", "project": "Jasper", "needed_months": 4, "limit_months": 2}) == \
        "Sharing would push Jasper 4 months past its in-service date; your limit is 2."
    assert sentence({"rule": "max_delay", "project": "Jasper", "needed_months": 1, "limit_months": 0}).startswith("Sharing would push Jasper 1 month past")
