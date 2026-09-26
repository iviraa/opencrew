"""The coordination planner, offline: ranking, month choice, conflicts, totals, saved states and execution."""
from datetime import date

import pytest

from app.planner import build, execute, store

TODAY = date(2026, 9, 26)


def op(i, a, b, sav_high, score=0.8, drive=20.0, overlap=0.7, a_org="gpc", b_org="desc"):
    return {"id": i, "job_a": a, "job_b": b, "a_org": a_org, "b_org": b_org, "a_name": a.upper(), "b_name": b.upper(), "tier": "crew", "score": score,
            "savings_low": sav_high / 3, "savings_high": float(sav_high), "drive_min": drive, "time_overlap": overlap}


JOBS = {
    "g1": ("gpc", date(2026, 10, 1), date(2027, 12, 31), "approved"), "g2": ("gpc", date(2027, 1, 1), date(2027, 6, 30), "approved"),
    "d1": ("desc", date(2026, 11, 1), date(2027, 9, 30), "approved"), "d2": ("desc", date(2027, 2, 1), date(2027, 5, 31), "proposed"),
    "d3": ("desc", date(2024, 1, 1), date(2025, 3, 31), "approved"), "g3": ("gpc", date(2024, 6, 1), date(2025, 6, 30), "approved"),
}


class FakeConn:
    """Answers the job lookups the builder makes; nothing else is touched."""
    def execute(self, sql, params=None):
        class R:
            def __init__(self, row): self.row = row
            def fetchone(self): return self.row
            def fetchall(self): return [self.row] if self.row else []
        if "FROM job WHERE id" in sql:
            org, s, e, status = JOBS[params[0]]
            return R({"id": params[0], "org_id": org, "name": params[0].upper(), "status": status, "need": None, "cost_usd": 5e6, "in_service": e,
                      "window_basis": "filed", "start_at": s, "end_at": e})
        return R(None)


def flat_months(cost_by_month=None):
    """A pair priced per month: flat except where the test says otherwise."""
    return {m: {"cost": {"low": (cost_by_month or {}).get(m, 100.0), "high": (cost_by_month or {}).get(m, 200.0)}, "days": {"low": 0.5, "high": 1.0}}
            for m in range(1, 13)}


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(build, "requests_for", lambda company: [])
    monkeypatch.setattr(build, "feasibility_for", lambda conn, i, c: None)
    monkeypatch.setattr(build, "news_for", lambda conn, i: [])
    monkeypatch.setattr(build, "solver_evidence", lambda conn, a, b: None)
    monkeypatch.setattr(build.Pricer, "pair", lambda self, o: flat_months({7: 5000.0, 8: 5000.0}))


def test_choose_window_picks_the_cheapest_run_and_reports_what_it_avoids():
    months = flat_months({7: 5000.0, 8: 5000.0, 9: 5000.0})
    allowed = build.months_between(date(2027, 6, 1), date(2027, 12, 31))
    w = build.choose_window(months, allowed)
    assert w["target_start"] == date(2027, 10, 1) and w["target_end"] == date(2027, 12, 31)
    assert w["naive_start"] == date(2027, 6, 1) and w["avoided"]["high"] > 0 and w["avoided"]["low"] >= 0


def test_build_ranks_by_feasibility_times_savings_sequences_by_month_and_flags_conflicts(offline, monkeypatch):
    rows = [op(1, "g1", "d1", 100_000, score=0.9), op(2, "g1", "d2", 300_000, score=0.5), op(3, "g2", "d1", 50_000, score=0.9)]
    monkeypatch.setattr(build, "candidates", lambda conn, c: rows)
    p = build.build(FakeConn(), "gpc", "year", today=TODAY)
    assert p["horizon"] == "year" and p["totals"]["period"] == [str(TODAY), "2027-09-26"]
    ids = [i["id"] for i in p["items"]]
    assert set(ids) == {"1", "2", "3"}
    assert [i["target_start"] for i in p["items"]] == sorted(i["target_start"] for i in p["items"])  # sequenced by start
    ranks = {i["id"]: i["rank"] for i in p["items"]}
    assert ranks["2"] > ranks["1"] > ranks["3"]  # score x savings
    both = [i for i in p["items"] if i["our_job"] == "g1"]
    assert all(set(i["conflicts"]) == {j["id"] for j in both if j is not i} for i in both) or any(not i["conflicts"] for i in both)
    t = p["totals"]
    assert t["savings"]["high"] == 450_000 and t["selected"] == 3 and t["actions"]["wait"] == 1  # d2 is still proposed
    assert next(i for i in p["items"] if i["id"] == "2")["action"] == "wait"


def test_quarter_widens_when_too_few_pairs_start_soon(offline, monkeypatch):
    rows = [op(1, "g1", "d1", 100_000), op(2, "g2", "d2", 100_000), op(3, "g2", "d1", 90_000)]  # only g1/d1 starts this quarter
    monkeypatch.setattr(build, "candidates", lambda conn, c: rows)
    p = build.build(FakeConn(), "gpc", "quarter", today=TODAY)
    assert p["horizon"] == "quarter" and "next year" in p["totals"]["note"]
    assert len(p["items"]) == 3 and p["totals"]["period"][1] == "2027-09-26"
    two = build.build(FakeConn(), "gpc", "quarter", today=date(2028, 1, 1))  # nothing ahead: the whole windows, flagged
    assert "whole build windows" in two["totals"]["note"] and two["totals"]["passed"] == 3


def test_passed_windows_are_flagged_not_planned(offline, monkeypatch):
    monkeypatch.setattr(build, "candidates", lambda conn, c: [op(9, "g3", "d3", 80_000)])
    p = build.build(FakeConn(), "gpc", "window", today=TODAY)
    it = p["items"][0]
    assert it["passed"] and it["action"] == "wait" and "ended" in it["risks"][0] and p["totals"]["passed"] == 1
    y = build.build(FakeConn(), "gpc", "year", today=TODAY)  # nothing ahead in the next year: widened to the windows, still flagged
    assert y["items"][0]["passed"] and "whole build windows" in y["totals"]["note"]


def test_open_requests_drive_the_action(offline, monkeypatch):
    monkeypatch.setattr(build, "candidates", lambda conn, c: [op(1, "g1", "d1", 100_000), op(2, "g2", "d1", 100_000)])
    monkeypatch.setattr(build, "requests_for", lambda c: [
        {"id": 5, "opportunity_id": 1, "status": "pending", "from_company": "gpc", "to_company": "desc", "created_at": "2026-09-10T00:00:00+00:00"},
        {"id": 6, "opportunity_id": 2, "status": "approved", "from_company": "gpc", "to_company": "desc", "created_at": "2026-09-01T00:00:00+00:00"}])
    p = build.build(FakeConn(), "gpc", "year", today=TODAY)
    assert [i["id"] for i in p["items"]] == ["1"] and p["items"][0]["action"] == "follow up" and p["items"][0]["request_id"] == 5


def test_carry_keeps_decisions_across_versions():
    old = [{"opportunity_id": 1, "state": "accepted", "note": "yes", "request_id": None, "goal_id": 7, "target_edited": True,
            "target_start": "2027-03-01", "target_end": "2027-05-31"}, {"opportunity_id": 2, "state": "proposed"}]
    new = [{"opportunity_id": 1, "state": "proposed", "note": "", "target_start": "2027-06-01", "target_end": "2027-08-31"},
           {"opportunity_id": 2, "state": "proposed", "note": ""}, {"opportunity_id": 3, "state": "proposed", "note": ""}]
    out = store.carry(new, old)
    assert out[0]["state"] == "accepted" and out[0]["goal_id"] == 7 and out[0]["target_start"] == "2027-03-01"
    assert out[1]["state"] == "proposed" and out[2]["state"] == "proposed"
    assert store.changes(old, new) == {"added": [3], "dropped": []}


def test_explain_item_only_restates_the_item():
    it = {"id": "1", "opportunity_id": 1, "ours": "A", "theirs": "B", "partner_name": "Dominion Energy SC", "verdict": "possible", "feasibility": 0.6,
          "feasibility_source": "overlap score", "savings": {"low": 1, "high": 3}, "rank": 2, "window": {"overlap_pct": 70, "common": ["2027-01-01", "2027-06-30"]},
          "target_start": "2027-03-01", "target_end": "2027-05-31", "weather": {"target": {"low": 1, "high": 2}, "naive": {"low": 2, "high": 4},
          "avoided": {"low": 1, "high": 2}, "days": {"low": 0.5, "high": 1}, "naive_window": ["2027-01-01", "2027-03-31"]},
          "action": "send request", "action_reason": "r", "risks": [], "news": [], "conflicts": [], "solver": None}
    e = build.explain_item(it)
    assert e["months_because"]["avoided_usd"] == {"low": 1, "high": 2} and e["chosen_because"]["rank"] == 2


def test_execute_turns_accepted_items_into_one_goal(monkeypatch):
    calls = []
    monkeypatch.setattr(execute, "_mine", lambda conn, ctx, i: {"id": i, "a_org": "gpc", "b_org": "desc", "a_name": "A", "b_name": "B", "tier": "crew",
                                                                  "distance_m": 8000.0, "drive_min": 12.0, "time_overlap": 0.6, "a_phase": None, "b_phase": None})
    monkeypatch.setattr(execute, "draft_note", lambda ctx, o: "Hi!")
    monkeypatch.setattr(execute, "rest", lambda ctx, method, table, **kw: calls.append((method, table, kw)) or [{"id": 42, **kw["json"]}])
    saved = {}
    monkeypatch.setattr(store, "set_goal", lambda conn, plan, ids, goal_id: saved.update({"ids": ids, "goal": goal_id}) or plan)
    plan = {"id": 1, "horizon": "quarter", "version": 2, "items": [
        {"id": "1", "opportunity_id": 1, "state": "accepted", "ours": "A", "theirs": "B", "partner": "desc", "target_start": "2027-03-01", "target_end": "2027-05-31", "note": "Yards first."},
        {"id": "2", "opportunity_id": 2, "state": "skipped", "ours": "A", "theirs": "C", "partner": "desc", "target_start": "2027-03-01", "target_end": "2027-05-31", "note": ""},
        {"id": "3", "opportunity_id": 3, "state": "accepted", "ours": "A", "theirs": "D", "partner": "desc", "target_start": "2027-03-01", "target_end": "2027-05-31", "note": "", "goal_id": 9}]}
    out, _ = execute.execute({"company": "gpc", "token": "t"}, None, plan)
    assert out["task_id"] == 42 and out["drafted"] == 1 and saved == {"ids": ["1"], "goal": 42}
    step = calls[0][2]["json"]["steps"][0]
    assert step["plan_item"] == "1" and "Mar 2027 to May 2027" in step["note"] and step["note"].endswith("Yards first.")
    assert execute.execute({"company": "gpc", "token": "t"}, None, {"id": 1, "horizon": "q", "version": 1, "items": plan["items"][1:2]})[0]["error"]


def test_routes_build_edit_and_explain(monkeypatch):
    from fastapi.testclient import TestClient

    from app.auth import current_user
    from app.main import app
    from app.planner import api as plan_api

    saved = {"row": None}
    item = {"id": "1", "opportunity_id": 1, "state": "proposed", "note": "", "target_start": "2027-03-01", "target_end": "2027-05-31", "ours": "A",
            "theirs": "B", "partner_name": "Dominion Energy SC", "verdict": "possible", "feasibility": 0.6, "feasibility_source": "overlap score",
            "savings": {"low": 1000.0, "high": 3000.0}, "rank": 1800, "window": {"overlap_pct": 70, "common": ["2027-01-01", "2027-06-30"]},
            "weather": {"target": {"low": 0, "high": 0}, "naive": {"low": 0, "high": 0}, "avoided": {"low": 0, "high": 0}, "days": {"low": 0, "high": 0},
                        "naive_window": ["2027-01-01", "2027-03-31"]}, "action": "send request", "action_reason": "r", "risks": [], "news": [],
            "conflicts": [], "solver": None, "our_job": "g1", "their_job": "d1", "verdict_source": None}
    totals = build.totals_for([item], 1, {}, (date(2026, 9, 26), date(2026, 12, 26)), "")
    row = {"id": 7, "company_id": "gpc", "horizon": "quarter", "version": 1, "items": [item], "totals": totals, "status": "active",
           "created_at": "2026-09-26T00:00:00+00:00", "updated_at": "2026-09-26T00:00:00+00:00"}
    monkeypatch.setattr(plan_api.build, "build", lambda conn, c, h: {"horizon": h, "items": [item], "totals": totals})
    monkeypatch.setattr(plan_api.store, "latest", lambda conn, c, h: saved["row"])
    monkeypatch.setattr(plan_api.store, "save", lambda conn, c, h, items, t: saved.update(row={**row, "changed": {"added": [1], "dropped": []}}) or saved["row"])
    monkeypatch.setattr(plan_api.store, "get", lambda conn, i, c: saved["row"] if i == 7 else None)

    def update(conn, plan, item_id, patch):
        plan["items"][0].update({k: v for k, v in patch.items() if k in ("state", "note")})
        return plan
    monkeypatch.setattr(plan_api.store, "update_item", update)
    app.dependency_overrides[current_user] = lambda: {"id": "u", "company": "gpc", "username": "georgia", "token": "t"}
    app.dependency_overrides[plan_api.get_conn] = lambda: None
    try:
        c = TestClient(app)
        r = c.get("/api/app/plan?horizon=quarter")
        assert r.status_code == 200 and r.json()["id"] == 7 and r.json()["items"][0]["state"] == "proposed"
        r = c.patch("/api/app/plan/7/items/1", json={"state": "accepted", "note": "go"})
        assert r.status_code == 200 and r.json()["items"][0]["state"] == "accepted" and r.json()["totals"]["selected"] == 1
        assert c.patch("/api/app/plan/8/items/1", json={"state": "accepted"}).status_code == 404
        e = c.get("/api/app/plan/7/explain/1").json()
        assert e["chosen_because"]["savings_usd"] == {"low": 1000.0, "high": 3000.0} and e["action"] == "send request"
    finally:
        app.dependency_overrides.clear()
