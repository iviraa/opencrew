"""Regressions from the stress pass: weird inputs get a clear refusal or a clamp, never a crash or a silent wrong answer."""
import pytest

from app.scenario import calc, experiments, normalize
from app.stormlab import wind


def test_calculate_accepts_list_values():
    assert calc.calculate("sum(x) / 3", {"x": [1, 2, 3]})["result"] == 2.0
    assert calc.calculate("avg(x) + max(x)", {"x": [2, 4]})["result"] == 7.0


@pytest.mark.parametrize("expr,values", [("sum(x)", {"x": "many"}), ("a + 1", {"a": [1, "b"]}), ("min(x)", {"x": []}), ("1/0", {}), ("10**10**10", {}),
                                         ("__import__('os')", {}), ("a.__class__", {"a": 1})])
def test_calculate_refuses_cleanly(expr, values):
    with pytest.raises(calc.Unsafe):
        calc.calculate(expr, values)


def test_shift_months_are_whole_and_bounded():
    with pytest.raises(ValueError, match="24 months"):
        experiments.ch_shift_window(None, "gpc", {"opportunity_id": 18, "side": "ours", "months": 120})
    with pytest.raises(ValueError, match="number"):
        experiments.ch_shift_window(None, "gpc", {"opportunity_id": 18, "side": "ours", "months": "three"})


def test_percent_changes_are_bounded():
    with pytest.raises(ValueError, match="-90%"):
        normalize.assumption_overrides({"name": "crew_day_usd", "pct": 10000})
    assert normalize.assumption_overrides({"name": "crew_day_usd", "pct": 20})["crew_day_usd"]["low"] > 0


def test_unknown_kind_is_named():
    with pytest.raises(ValueError, match="unknown experiment"):
        normalize.kind_of("teleport")


@pytest.mark.parametrize("value,expected", [(7, 5), (0, "ts"), ("EF3", "EF3"), ("ef9", "EF5"), ("hurricane", 3), (None, 3), (3.0, 3)])
def test_storm_categories_clamp(value, expected):
    cat, _ = wind.parse_category(value)
    assert cat == expected


def test_out_of_scale_categories_say_so():
    assert "beyond" in wind.parse_category(7)[1]
    assert "below" in wind.parse_category(0)[1]


def test_tornado_is_a_narrow_field():
    from datetime import datetime, timezone
    wf = wind.field(-79.93, 32.78, datetime(2027, 9, 10, 12, tzinfo=timezone.utc), "EF3", speed_mph=0.0)
    assert wf["category"] == "EF3" and wf["radii_nm"] == wind.TORNADO_RADII_NM
    assert wind.wind_of("EF3") > wind.wind_of(3)  # an EF3 tornado is stronger than a category 3 hurricane


@pytest.fixture
def conn():
    from app.db import connect
    with connect() as c:
        yield c
        c.rollback()


def test_other_companys_overlap_is_invisible(conn):
    from app.hazards.api import visible
    from app.stormlab import sensitivity
    assert visible(conn, "gpc", "zone", "18") and not visible(conn, "desc", "zone", "6163") and not visible(conn, "gpc", "zone", "6070")
    assert not visible(conn, "gpc", "zone", "eighteen")
    with pytest.raises(ValueError, match="no overlap"):
        sensitivity.sensitivity(conn, "desc", 6163)


def test_replay_only_sees_our_side(conn):
    from app.stormlab import replay
    with pytest.raises(ValueError, match="ours"):
        replay.jobs_for(conn, "desc", opportunity_ids=[6163])
    rows = replay.jobs_for(conn, "gpc", opportunity_ids=[18])
    assert rows and {r["org_id"] for r in rows} <= {"gpc", "desc"}
