"""What-if experiments: the safe calculator and scenario merging offline; overlays against the database when it is up, which must leave it unchanged."""
import psycopg
import pytest

from app.db import DATABASE_URL, connect
from app.scenario import calc, engine, experiments, metrics

try:
    with psycopg.connect(DATABASE_URL, connect_timeout=3) as c:
        HAS_18 = bool(c.execute("SELECT 1 FROM opportunity WHERE id = 18").fetchone())
except Exception:
    HAS_18 = False
needs_db = pytest.mark.skipif(not HAS_18, reason="database not reachable or overlap 18 missing")


@pytest.fixture
def conn():
    with connect() as c:
        yield c
        c.rollback()


# ---------- calculator ----------

def test_calculator_does_arithmetic_with_named_values():
    out = calc.calculate("sum(a, b) * 1.2 - abs(c)", {"a": 10, "b": 5, "c": -3})
    assert out["result"] == 15.0 and out["steps"]
    assert calc.calculate("pct_change(before, after)", {"before": 50, "after": 75})["result"] == 50.0
    assert round(calc.calculate("mi_km(10)")["result"], 3) == 16.093


@pytest.mark.parametrize("bad", ["__import__('os')", "a.__class__", "open('x')", "2 ** 999999", "lambda: 1", "x", "a if a else 1", "[1,2]"])
def test_calculator_refuses_anything_but_arithmetic(bad):
    with pytest.raises(calc.Unsafe):
        calc.calculate(bad, {"a": 1})


def test_calculator_rejects_division_by_zero_and_bad_names():
    with pytest.raises(calc.Unsafe):
        calc.calculate("1 / 0")
    with pytest.raises(calc.Unsafe):
        calc.calculate("a", {"not an identifier": 1})


# ---------- scenario dict ----------

def test_merge_stacks_changes_later_wins_and_lists_union():
    a = engine.merge(engine.EMPTY, {"jobs": {"j1": {"start": "2027-01-01"}}, "exclude_partners": ["desc"], "constraints": {"blackout_months": {"*": [8]}}})
    b = engine.merge(a, {"jobs": {"j1": {"end": "2028-01-01"}, "j2": {"cancelled": True}}, "exclude_partners": ["duke", "desc"],
                         "constraints": {"blackout_months": {"*": [9, 8]}}, "assumptions": {"crew_day_usd": {"low": 5000, "high": 5000}}})
    assert b["jobs"]["j1"] == {"start": "2027-01-01", "end": "2028-01-01"} and b["jobs"]["j2"] == {"cancelled": True}
    assert b["exclude_partners"] == ["desc", "duke"] and b["constraints"]["blackout_months"]["*"] == [8, 9]
    assert engine.is_empty(engine.merge(engine.EMPTY, {})) and not engine.is_empty(b)
    assert a["jobs"]["j1"] == {"start": "2027-01-01"}  # merging never edits its inputs


def test_assumption_overrides_only_know_real_keys():
    o = engine.assumption_overrides({"assumptions": {"crew_day_usd": {"low": 1, "high": 2}, "made_up": {"low": 9}}})
    assert o == {"crew_day_usd": {"low": 1.0, "high": 2.0}}


def test_deltas_compare_numbers_and_carry_strings():
    base = {"savings_low": metrics.m(100, "USD"), "verdict": metrics.m("possible"), "only_base": metrics.m(1)}
    scen = {"savings_low": metrics.m(150, "USD"), "verdict": metrics.m("strong")}
    d = {x["metric"]: x for x in metrics.deltas(base, scen)}
    assert d["savings_low"]["delta"] == 50 and d["savings_low"]["pct"] == 50.0
    assert d["verdict"]["delta"] is None and d["verdict"]["scenario"] == "strong" and "only_base" not in d


def test_scope_union():
    s = metrics.scope_of({"opportunity_id": 18}, {"plan_horizon": "year", "job_ids": ["a"]}, {"job_ids": ["b"], "event": True})
    assert s == {"opportunity_id": 18, "job_ids": ["a", "b"], "plan_horizon": "year", "event": True, "new_project": False}


def test_unknown_kind_is_refused():
    with pytest.raises(ValueError):
        experiments.stack(None, "gpc", [{"kind": "teleport", "params": {}}])


# ---------- overlays against the database ----------

def counts(conn):
    return conn.execute("SELECT (SELECT count(*) FROM job) AS j, (SELECT count(*) FROM opportunity) AS o, "
                        "(SELECT sum(savings_high) FROM opportunity) AS s, (SELECT max(upper(work_window)) FROM job) AS w").fetchone()


@needs_db
def test_shift_window_changes_overlap_and_leaves_the_database_alone(conn):
    before = counts(conn)
    f = experiments.run(conn, "gpc", "shift_window", {"opportunity_id": 18, "side": "ours", "months": 3})
    assert f["kind"] == "shift_window" and f["id"] and f["knobs"][0]["type"] == "month_shift"
    d = {x["metric"]: x for x in f["deltas"]}
    assert d["overlap_pct"]["base"] != d["overlap_pct"]["scenario"] and d["savings_high"]["delta"] != 0
    assert counts(conn) == before


@needs_db
def test_compose_stacks_shift_and_assumptions_in_one_evaluation(conn):
    f = experiments.run(conn, "gpc", "compose", {"changes": [
        {"kind": "shift_window", "params": {"opportunity_id": 18, "side": "ours", "months": 3}},
        {"kind": "change_assumptions", "params": {"overrides": {"crew_day_usd": 9000}}}]})
    d = {x["metric"]: x for x in f["deltas"]}
    assert d["overlap_pct"]["delta"] < 0 and d["weather_cost_low"]["delta"] > 0  # both changes show in one finding
    assert f["params"]["changes"] and any("2 change(s)" in n for n in f["notes"])
    assert f["scenario"]["overlay"]["assumptions"]["crew_day_usd"]["high"] == 9000.0


@needs_db
def test_add_project_finds_new_overlaps_then_vanishes(conn):
    before = counts(conn)
    f = experiments.run(conn, "gpc", "add_project", {"name": "Hypothetical Savannah 230 kV", "kv": 230, "start": "2027-03-01", "in_service": "2028-12-01",
                                                    "coords": [[-81.25, 32.15], [-81.05, 32.30]]})
    d = {x["metric"]: x for x in f["deltas"]}
    assert d["pairs"]["base"] == 0 and d["pairs"]["scenario"] > 0
    assert counts(conn) == before and not conn.execute("SELECT 1 FROM job WHERE id LIKE 'whatif-%%'").fetchone()


@needs_db
def test_rule_and_exclusion_reach_the_plan(conn):
    f = experiments.run(conn, "gpc", "apply_rule", {"months": [8, 9], "horizon": "year"})
    assert "plan_savings_low" in f["scenario"]["metrics"] and {k["name"] for k in f["knobs"]} == {"phase", "months", "where"}
    g = experiments.run(conn, "gpc", "exclude_partner", {"partner": "Dominion", "horizon": "year", "opportunity_id": 18})
    assert g["scenario"]["metrics"]["pairs"]["value"] == 0 and any("no longer exists" in n for n in g["notes"])
    c = experiments.compare(conn, "gpc", f["id"], g["id"])
    assert {x["metric"] for x in c["deltas"]} >= {"plan_savings_low", "plan_savings_high"}


@needs_db
def test_findings_are_kept_starred_and_deleted(conn):
    f = experiments.run(conn, "gpc", "change_assumptions", {"opportunity_id": 18, "overrides": {"crew_day_usd": 6000}})
    assert experiments.get(conn, f["id"], "gpc")["title"] == f["title"]
    assert experiments.get(conn, f["id"], "desc") is None  # not theirs
    assert experiments.star(conn, f["id"], "gpc")["starred"] is True
    assert experiments.listing(conn, "gpc", starred=True)[0]["id"] == f["id"]
    assert experiments.delete(conn, f["id"], "gpc") == 1


# ---------- the shapes the chat cards send ----------

def test_canonical_kinds_and_aliases():
    from app.scenario import normalize
    assert normalize.kind_of("assumption") == "assumption" and normalize.kind_of("change_assumptions") == "assumption"
    assert normalize.kind_of("rule") == "rule" and normalize.kind_of("apply_rule") == "rule" and normalize.kind_of("replay") == "replay_year"
    with pytest.raises(ValueError):
        normalize.kind_of("teleport")


def test_dotted_knob_names_resolve_into_nested_params():
    from app.scenario import normalize
    p = normalize.resolve({"changes": [{"kind": "shift_window", "params": {"months": 3}}], "changes.0.params.months": -2, "changes.1.kind": "budget", "months": 1})
    assert p["changes"][0]["params"]["months"] == -2 and p["changes"][1]["kind"] == "budget" and p["months"] == 1
    assert "changes.0.params.months" not in p


def test_assumption_pct_and_storm_place_shapes():
    from app.scenario import normalize
    from app.config import ASSUMPTIONS
    o = normalize.assumption_overrides({"name": "crew_day_usd", "pct": 50})
    assert o["crew_day_usd"]["low"] == round(float(ASSUMPTIONS["crew_day_usd"]["low"]) * 1.5, 4)
    with pytest.raises(ValueError):
        normalize.assumption_overrides({"name": "drive_limit_min", "pct": 10})
    ev = normalize.storm_event({"place": {"lon": -80.0, "lat": 32.8}, "category": 3, "date": "2027-09-10", "radius_km": 80})
    assert ev == {"kind": "storm", "date": "2027-09-10", "category": 3, "lon": -80.0, "lat": 32.8, "radius_km": 80.0}
    assert normalize.quarter_of({"quarter": "Q2", "year": 2027}) == "2027Q2" and normalize.quarter_of({"quarter": "2028Q1"}) == "2028Q1"


@needs_db
def test_card_shaped_params_run_and_knobs_match_them(conn):
    f = experiments.run(conn, "gpc", "assumption", {"name": "crew_day_usd", "pct": 20, "opportunity_id": 18})
    assert f["kind"] == "assumption" and {k["name"] for k in f["knobs"]} == {"name", "pct"} and f["params"]["pct"] == 20
    g = experiments.run(conn, "gpc", "compose", {"changes": [{"kind": "shift_window", "params": {"opportunity_id": 18, "months": 3}},
                                                             {"kind": "storm", "params": {"place": {"lon": -79.93, "lat": 32.78}, "category": 3, "date": "2027-09-10", "radius_km": 80}}],
                                                 "changes.0.params.months": -1})
    assert g["params"]["changes"][0]["params"]["months"] == -1 and g["knobs"][0]["name"] == "changes.0.months"
    assert any(k.startswith("event_") or k in ("affected_days_low",) for k in g["scenario"]["metrics"])
    assert experiments.compare(conn, "gpc", f["id"], g["id"])["title"]


@needs_db
def test_finding_report_renders_the_numbers(conn):
    from app.crewly import reports
    f = experiments.run(conn, "gpc", "shift_window", {"opportunity_id": 18, "months": 3})
    r = reports.build(conn, "gpc", "finding", str(f["id"]))
    assert "What moved" in r["html"] and "shared build window" in r["html"] and r["title"].startswith("Finding:")
