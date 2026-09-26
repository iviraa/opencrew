"""Storm lab, offline: wind fields, affected days, replay math, sensitivity knobs, the finding shape and the experiment registry."""
from datetime import datetime, timezone

import pytest

from app.config import ASSUMPTIONS
from app.stormlab import EXPERIMENTS, apply_event, finding, replay, sensitivity, wind
from app.stormlab.events import site_days

LANDFALL = datetime(2027, 9, 15, 12, tzinfo=timezone.utc)


def test_category_and_wind_follow_the_saffir_simpson_scale():
    assert wind.category_of(120) == 3 and wind.category_of(60) == "ts" and wind.category_of(170) == 5
    assert wind.CATEGORY_MPH[3][0] <= wind.wind_of(3) <= wind.CATEGORY_MPH[3][1]


def test_wind_field_has_nested_bands_and_a_point_at_landfall_is_in_the_strongest():
    wf = wind.field(-80.0, 32.85, LANDFALL, 3)
    assert wf["bands"][64].area < wf["bands"][50].area < wf["bands"][34].area
    band, hours = wind.band_of(wf, -80.0, 32.85)
    assert band == 64 and hours > 0
    assert wind.band_of(wf, -95.0, 40.0) == (None, 0)  # nowhere near


def test_bands_decay_inland_so_a_far_inland_point_only_sees_weaker_winds():
    wf = wind.field(-80.0, 32.85, LANDFALL, 3, heading_deg=0.0)
    near, _ = wind.band_of(wf, -80.0, 33.1)
    far, _ = wind.band_of(wf, -80.0, 36.6)  # ~420 km up the track, past the last hurricane-force hour
    assert near == 64 and far in (50, 34, None)  # a category 3 is no longer hurricane-force that far inland


def test_site_days_add_a_recovery_allowance_by_band():
    assert site_days(64, 20) == {"low": 2.0, "high": 4.0}
    assert site_days(34, 5) == {"low": 1.0, "high": 2.0}
    assert site_days(50, 30)["low"] >= 2.0  # more than a day in the winds is two passage days


def test_year_days_scales_event_days_to_the_months_covered_and_spans_counties():
    rows = [{"county_fips": "13001", "month": 8, "hazard": "wind", "event_days": 31}, {"county_fips": "13003", "month": 8, "hazard": "wind", "event_days": 0},
            {"county_fips": "13001", "month": 9, "hazard": "flood", "event_days": 15}]
    d = replay.year_days(rows, {8: 31, 9: 30}, ["13001", "13003"])
    assert d["wind"] == {"low": 0.0, "high": 31.0} and d["flood"] == {"low": 0.0, "high": 15.0}


def test_quantiles_interpolate():
    assert replay.quantile([1, 2, 3, 4, 5], 0.5) == 3 and replay.quantile([1, 2, 3, 4, 5], 0.9) == 4.6 and replay.quantile([], 0.5) is None


def test_assumption_context_restores_the_value():
    a = ASSUMPTIONS["crew_day_usd"]
    before = (a["low"], a["high"])
    with sensitivity.assumption("crew_day_usd", 1, 2):
        assert (a["low"], a["high"]) == (1, 2)
    assert (a["low"], a["high"]) == before


def test_short_labels_fit_a_chart():
    assert sensitivity.short("Line crew day: 4-6 workers + bucket truck") == "Line crew day"
    assert len(sensitivity.short("x" * 80)) <= 36


def test_finding_shape_and_deltas():
    base = finding.metrics(affected_days_high=10.0, weather_cost_high=1000)
    scen = finding.metrics(affected_days_high=15.0, weather_cost_high=1500, exposed_sites=3)
    f = finding.make("storm_scenario", "t", "q", {"a": 1}, base, scen, notes=["n"], evidence=["e"], knobs=[finding.knob("date", "date", "2027-09-15", "Date")])
    assert set(f) >= {"id", "title", "question", "kind", "params", "base", "scenario", "deltas", "notes", "evidence", "knobs", "sources", "created_at"}
    d = {x["metric"]: x for x in f["deltas"]}
    assert d["affected_days_high"]["delta"] == 5.0 and d["weather_cost_high"]["pct"] == 50 and "exposed_sites" not in d
    assert f["scenario"]["metrics"]["exposed_sites"]["unit"] == "sites"


def test_experiments_registry_and_event_kinds():
    assert set(EXPERIMENTS) == {"storm", "replay", "sensitivity"}
    with pytest.raises(ValueError):
        apply_event(None, "gpc", {"kind": "tsunami"}, [])
