"""Feasibility factors and their combination, all offline on synthetic rows; the route with a fake assessment."""
from datetime import date, datetime

import pytest

from app.feasibility import assess as A, cost, counterparty, forecast, future, location, news, timing
from app.feasibility.common import verdict_for

D = datetime


def job(id="gpc-1", org="gpc", name="Goshen - Kraft 115 kV rebuild", start=D(2024, 6, 1), end=D(2027, 6, 1), **over):
    base = {"id": id, "org_id": org, "name": name, "status": "under construction", "need": "reliability", "cost_usd": 40_660_000, "length_mi": 12.0,
            "voltage_kv": 115, "endpoints": ["Goshen", "Kraft"], "in_service": date(2027, 6, 1), "state": "GA", "planner": "filing", "job_type": "line_upgrade",
            "start": start, "end": end, "history": [], "hazard": None}
    return {**base, **over}


def ctx(**over):
    ours = job()
    theirs = job(id="desc-2", org="desc", name="Okatie-Bluffton 115kV: Rebuild", start=D(2023, 12, 1), end=D(2025, 6, 1), state="SC", endpoints=["Okatie", "Bluffton"])
    op = {"id": 18, "job_a": "desc-2", "job_b": "gpc-1", "tier": "crew", "distance_m": 13059.0, "drive_min": 19.7, "drive_km": 23.8, "overlap_m": 0.0,
          "time_overlap": 0.666, "time_gap_days": 0, "flags": ["hurricane_season_high_risk"], "savings_low": 29000, "savings_high": 58000, "score": 0.82,
          "status": "not_contacted", "a_org": "desc", "b_org": "gpc", "a_name": theirs["name"], "b_name": ours["name"],
          "a_start": theirs["start"], "a_end": theirs["end"], "b_start": ours["start"], "b_end": ours["end"]}
    base = {"company": "gpc", "partner": "desc", "op": op, "ours": ours, "theirs": theirs, "today": date(2025, 1, 15),
            "savings": {"categories": [{"label": "Travel", "low": 20000, "high": 40000}, {"label": "Labor", "low": 9000, "high": 18000}],
                        "share_of_budget": {"low": 0.0007, "high": 0.0014}},
            "neighbours": {}, "plan": {"has_plan": False, "covers_pair": False}, "requests": [], "memories": [], "news": None,
            "hazards": {}, "coordination": None, "month_cost": None}
    base.update(over)
    return base


def test_location_reads_distance_drive_and_state_line():
    f = location.assess(ctx())
    assert f["verdict"] == "possible" and "8.1 mi" in f["evidence"][0] and "20 min drive" in f["evidence"][1]
    assert any("two states" in e for e in f["evidence"]) and any("two states" in c for c in f["conditions"])
    far = ctx(); far["op"]["drive_min"] = 70
    g = location.assess(far)
    assert g["verdict"] == "unlikely" and any("45 min" in c for c in g["conditions"])
    wet = ctx(); wet["ours"]["hazard"] = {"in_floodplain": True, "flood_zones": ["AE"]}
    assert any("floodplain" in e for e in location.assess(wet)["evidence"])


def test_timing_scores_shared_months_firmness_and_slips():
    f = timing.assess(ctx())
    assert f["verdict"] == "strong" and "67% of the shorter window" in f["evidence"][1]
    assert len(f["options"]) == 6 and all(0 <= o["overlap"] <= 1 for o in f["options"])
    soft = ctx(); soft["theirs"]["status"] = "Conceptual"; soft["theirs"]["history"] = [{"observed_at": None, "start": D(2023, 6, 1), "end": D(2025, 1, 1)}]
    g = timing.assess(soft)
    assert g["score"] < f["score"] and any("slipped 1 time" in e for e in g["evidence"]) and any("conceptual" in e for e in g["evidence"])
    apart = ctx(); apart["op"].update(time_overlap=0.0, time_gap_days=400)
    assert timing.assess(apart)["verdict"] == "unlikely"


def test_timing_shift_options_carry_weather_deltas_when_month_costs_exist():
    month_cost = {m: {"low": 1000.0 * (m % 3), "high": 2000.0 * (m % 3)} for m in range(1, 13)}
    f = timing.assess(ctx(month_cost=month_cost))
    deltas = [o["weather_cost_delta"] for o in f["options"]]
    assert all(d is not None and set(d) == {"low", "high"} for d in deltas)
    assert all(o["weather_cost_delta"] is None for o in timing.assess(ctx())["options"])


def test_cost_only_repeats_existing_savings():
    f = cost.assess(ctx())
    assert f["verdict"] == "strong" and "coordinating saves $29k to $58k" == f["evidence"][0]
    assert any("$40.7M" in e for e in f["evidence"]) and any("0.1% of the smaller project" in e for e in f["evidence"])
    none = ctx(); none["op"].update(savings_low=0, savings_high=0, time_overlap=0.0)
    g = cost.assess(none)
    assert g["verdict"] == "unlikely" and any("align the windows" in c for c in g["conditions"])


def season(low, high, total=93, hazards=("wind",)):
    return {"start": "2025-02-12", "end": "2025-05-15", "days": total, "affected_days": {"forecast": 0, "low": low, "high": high},
            "hazards": [{"hazard": h, "label": h.title(), "leans": ["Above-normal precip"], "live": []} for h in hazards]}


def test_forecast_is_unknown_without_layers_and_drags_when_the_season_is_exposed():
    assert forecast.assess(ctx())["verdict"] == "unknown"
    calm = forecast.assess(ctx(hazards={"season": season(1, 3), "now7": {"affected_days": {"forecast": 0}, "hazards": []}}))
    assert calm["verdict"] == "strong" and "next 7 days: 0 affected days" in calm["evidence"][0]
    rough = forecast.assess(ctx(hazards={"season": season(20, 30)}))
    assert rough["verdict"] == "possible" and any("outside the exposed months" in c for c in rough["conditions"])


def test_news_handles_missing_pipeline_empty_feed_and_negative_impacts():
    assert news.assess(ctx())["verdict"] == "unknown"
    assert news.assess(ctx(news=[]))["verdict"] == "possible"
    bad = [{"title": "County board opposes new line", "source": "Local Times", "published": "2025-01-02", "impact": "opposition", "confidence": 0.9},
           {"title": "Rebuild delayed to 2028", "source": "Utility Dive", "published": "2025-01-05", "impact": "delay", "confidence": 0.8}]
    f = news.assess(ctx(news=bad))
    assert f["score"] < 0.5 and f["count"] == 2 and len(f["conditions"]) == 2


def test_counterparty_uses_request_history_and_our_notes():
    assert counterparty.assess(ctx(requests=None))["verdict"] == "unknown"
    reqs = [{"id": 1, "opportunity_id": 18, "from_company": "gpc", "to_company": "desc", "status": "declined", "feedback": "Not this year",
             "created_at": "2025-01-01T10:00:00+00:00", "responded_at": "2025-01-02T10:00:00+00:00"}]
    f = counterparty.assess(ctx(requests=reqs, memories=[{"id": 1, "text": "We never share crews in hurricane season"}]))
    assert "1 request with Dominion Energy SC: 0 approved, 1 declined, 0 pending" in f["evidence"][0]
    assert any("about 24 hours" in e for e in f["evidence"]) and any("declined before" in c for c in f["conditions"])
    assert any("hurricane season" in c for c in f["conditions"])


def test_future_finds_later_work_at_the_same_station():
    later = {"gpc": [{"id": "gpc-9", "name": "Kraft 230 kV expansion", "endpoints": ["Kraft", "Savannah"], "in_service": date(2029, 1, 1), "org_id": "gpc"}]}
    f = future.assess(ctx(neighbours=later))
    assert any("Kraft 230 kV expansion (2029)" in e for e in f["evidence"]) and any("push this one back" in c for c in f["conditions"])
    assert any("state line" in c for c in f["conditions"])


def fake(name, verdict, score):
    return {"factor": name, "label": name, "verdict": verdict, "score": score, "evidence": [f"{name} evidence 1"], "conditions": [], "sources": []}


def test_combination_rule():
    names = [n for n, _, _ in A.FACTORS]
    strong = [fake(n, "strong", 0.9) for n in names]
    assert A.combine(strong) == ("strong", 0.9)
    one_bad = strong[:-1] + [fake("future", "unlikely", 0.2)]
    v, s = A.combine(one_bad)
    assert v == "possible" and s < 0.9
    two_bad = strong[:-2] + [fake("counterparty", "unlikely", 0.2), fake("future", "unlikely", 0.2)]
    assert A.combine(two_bad)[0] == "unlikely"
    unknowns = [fake(n, "unknown", None) for n in names]
    assert A.combine(unknowns) == ("unknown", 0.0)
    assert verdict_for(0.7) == "strong" and verdict_for(0.39) == "unlikely"


def test_build_writes_a_three_sentence_template_without_a_model():
    out = A.build(ctx())
    assert out["verdict"] in ("strong", "possible") and 0 < out["score"] <= 1 and len(out["factors"]) == 7
    assert out["narrative"].count(". ") >= 2 and out["narrative"].startswith("Overlap #18 with desc")
    assert {f["factor"] for f in out["factors"]} == {n for n, _, _ in A.FACTORS}


def test_route_returns_the_assessment_and_404s_for_foreign_overlaps(monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main
    from app.auth import current_user
    from app.db import get_conn
    main.app.dependency_overrides[current_user] = lambda: {"id": "u", "company": "gpc", "username": "georgia", "token": "t"}
    main.app.dependency_overrides[get_conn] = lambda: None
    calls = []

    def fake_assess(conn, oid, company, refresh=False, quick=False, today=None):
        calls.append((oid, company, refresh))
        return {"opportunity_id": oid, "company_id": company, "verdict": "strong", "score": 0.8, "factors": [], "narrative": "ok", "created_at": "now"} if oid == 18 else None

    monkeypatch.setattr(A, "assess", fake_assess)
    try:
        with TestClient(main.app) as c:
            r = c.get("/api/app/feasibility/18?refresh=1")
            assert r.status_code == 200 and r.json()["verdict"] == "strong" and calls[-1] == (18, "gpc", True)
            assert c.get("/api/app/feasibility/999").status_code == 404
    finally:
        main.app.dependency_overrides.clear()


@pytest.mark.parametrize("months", [-6, 6])
def test_phase_at_and_slips_helpers(months):
    assert timing.phase_at(D(2024, 1, 1), D(2025, 1, 1), D(2024, 1, 15)) == "survey & permitting"
    assert timing.phase_at(D(2024, 1, 1), D(2025, 1, 1), D(2024, 9, 1)) == "construction"
    assert timing.slips([{"end": D(2024, 1, 1)}, {"end": D(2026, 1, 1)}], D(2025, 1, 1)) == 1
    assert abs(months) == 6
