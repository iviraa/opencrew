"""Hazard layers, history and exposure math, all offline."""
from datetime import date, datetime, timezone

import pytest
from shapely.geometry import Point, Polygon, shape

from app.hazards import climate, exposure, layers
from app.hazards.api import parse_bbox, parse_hazards
from app.hazards.config import ALERT_EVENTS, EVENT_TYPES, HAZARDS

SQUARE = {"type": "Polygon", "coordinates": [[[-84, 33], [-83, 33], [-83, 34], [-84, 34], [-84, 33]]]}
ZONES = "GA|001|FFC|Dade|GA001|Dade|13083|E|nw|34.85|-85.5\nGA|001|FFC|Dade|GA001|Walker|13295|E|nw|34.85|-85.5\nbad line\n"


def alert(event, geometry=None, ugc=None, zones=None):
    return {"type": "Feature", "geometry": geometry, "properties": {
        "event": event, "sent": "2026-09-26T10:00:00+00:00", "onset": "2026-09-26T12:00:00+00:00", "ends": "2026-09-27T00:00:00+00:00",
        "expires": "2026-09-27T00:00:00+00:00", "headline": f"{event} until midnight", "areaDesc": "Somewhere, GA", "severity": "Severe",
        "id": f"urn:{event}", "geocode": {"UGC": ugc or []}, "affectedZones": zones or []}}


def test_every_alert_event_maps_to_a_known_hazard():
    assert set(ALERT_EVENTS.values()) <= set(HAZARDS)
    assert {v for v in EVENT_TYPES.values() if v} <= set(HAZARDS)


def test_zone_county_file_parses_and_skips_junk():
    z = layers.parse_zone_counties(ZONES)
    assert z == {"GAZ001": ["13083", "13295"]}


def test_alerts_keep_work_hazards_and_draw_zone_alerts_from_counties(monkeypatch):
    monkeypatch.setattr(layers, "zone_counties", lambda: {"GAZ001": ["13083"]})
    monkeypatch.setattr(layers, "county_shapes", lambda: {"13083": shape(SQUARE), "13295": shape(SQUARE)})
    data = {"features": [alert("High Wind Warning", SQUARE), alert("Small Craft Advisory", SQUARE), alert("Tornado Watch", ugc=["GAZ001"]),
                         alert("Heat Advisory", ugc=["GAC295"]), alert("Flood Watch", ugc=["ZZZ999"])]}  # last one has no outline at all
    rows = layers.parse_alerts(data, zone_budget=[0])
    assert [(r["hazard"], r["rank"]) for r in rows] == [("wind", 3), ("tornado", 2), ("heat", 1)]
    assert all(r["layer"] == "alerts" and r["wkt"].startswith("POLYGON") for r in rows)
    assert rows[0]["period_start"] == datetime(2026, 9, 26, 12, tzinfo=timezone.utc)


def test_spc_national_parses_categorical_probabilistic_and_fire():
    feat = lambda label: {"type": "Feature", "geometry": SQUARE, "properties": {"LABEL": label, "VALID": "202609261200", "EXPIRE": "202609271200", "ISSUE": "202609260600"}}
    cat = layers.parse_spc_national({"features": [feat("SLGT"), feat("TSTM"), feat("No Areas")]}, 1, "spc")
    assert [(r["hazard"], r["rank"], r["label"]) for r in cat] == [("storms", 2, "SPC slight risk")]
    prob = layers.parse_spc_national({"features": [feat("0.15"), feat("0.30"), feat("0.05")]}, 5, "spc48")
    assert [r["props"]["level"] for r in prob] == ["15%", "30%"]
    fire = layers.parse_spc_national({"features": [feat("CRIT"), feat("ISODRYT")]}, 1, "spc_fire")
    assert [(r["hazard"], r["rank"]) for r in fire] == [("wildfire", 2), ("wildfire", 1)]


def test_ero_merges_pieces_per_level():
    f = lambda: {"type": "Feature", "geometry": SQUARE, "properties": {"OUTLOOK": "Slight (at least 15%)", "PRODUCT": "Day 2 Excessive Rainfall Outlook",
                                                                       "ISSUE_TIME": "2026-09-26T08:00:00", "START_TIME": "2026-09-27T12:00:00", "END_TIME": "2026-09-28T12:00:00"}}
    rows = layers.parse_ero_national({"features": [f(), f()]})
    assert len(rows) == 1 and rows[0]["hazard"] == "flood" and rows[0]["props"]["day"] == 2 and rows[0]["rank"] == 2


def test_fires_and_quakes_rank_by_size_and_stay_in_the_us():
    fires = layers.parse_fires({"features": [{"type": "Feature", "geometry": SQUARE, "properties": {"attr_IncidentName": "Big", "poly_GISAcres": 12000, "attr_PercentContained": 10}},
                                              {"type": "Feature", "geometry": SQUARE, "properties": {"IncidentName": "Small", "IncidentSize": "40"}}]}, "perimeters")
    assert [(r["rank"], r["label"]) for r in fires] == [(3, "Big fire, 12,000 acres"), (1, "Small fire, 40 acres")]
    quakes = layers.parse_quakes({"features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [-118, 34, 5]}, "properties": {"mag": 4.2, "place": "near LA", "time": 1790000000000}},
                                               {"type": "Feature", "geometry": {"type": "Point", "coordinates": [140, 36, 5]}, "properties": {"mag": 6.0, "place": "Japan", "time": 1790000000000}}]})
    assert len(quakes) == 1 and quakes[0]["rank"] == 2 and quakes[0]["hazard"] == "earthquake"


def test_season_hazard_reads_the_lean_for_the_month():
    assert layers.season_hazard("temp", "Above", 7) == "heat" and layers.season_hazard("temp", "Above", 1) is None
    assert layers.season_hazard("temp", "Below", 1) == "winter" and layers.season_hazard("prcp", "Above", 4) == "flood"
    assert layers.season_hazard("prcp", "Below", 8) == "wildfire" and layers.season_hazard("prcp", "Below", 12) is None


def test_storm_events_tally_counts_distinct_days_per_county_and_month():
    rows = [
        {"EVENT_TYPE": "Thunderstorm Wind", "CZ_TYPE": "C", "STATE_FIPS": "13", "CZ_FIPS": "121", "BEGIN_DATE_TIME": "05-JUN-24 14:00:00", "END_DATE_TIME": "05-JUN-24 14:30:00", "DAMAGE_PROPERTY": "10.00K"},
        {"EVENT_TYPE": "Thunderstorm Wind", "CZ_TYPE": "C", "STATE_FIPS": "13", "CZ_FIPS": "121", "BEGIN_DATE_TIME": "05-JUN-24 18:00:00", "END_DATE_TIME": "05-JUN-24 18:10:00", "DAMAGE_PROPERTY": "2.5M"},
        {"EVENT_TYPE": "Excessive Heat", "CZ_TYPE": "Z", "STATE_FIPS": "13", "CZ_FIPS": "001", "BEGIN_DATE_TIME": "30-JUN-24 00:00:00", "END_DATE_TIME": "02-JUL-24 23:00:00", "DAMAGE_PROPERTY": "0.00K"},
        {"EVENT_TYPE": "Rip Current", "CZ_TYPE": "Z", "STATE_FIPS": "13", "CZ_FIPS": "001", "BEGIN_DATE_TIME": "30-JUN-24 00:00:00", "END_DATE_TIME": "30-JUN-24 23:00:00", "DAMAGE_PROPERTY": "0.00K"},
    ]
    t = climate.tally(rows, {"GAZ001": ["13083", "13295"]})
    assert len(t[("13121", 6, "wind")]["days"]) == 1 and t[("13121", 6, "wind")]["damage"] == 2_510_000
    assert len(t[("13083", 6, "heat")]["days"]) == 1 and len(t[("13083", 7, "heat")]["days"]) == 2  # june 30, july 1 and 2
    assert ("13295", 7, "heat") in t and not any(k[2] not in HAZARDS for k in t)


def test_damage_parses_suffixes():
    assert climate.damage_usd("10.00K") == 10_000 and climate.damage_usd("1.5B") == 1.5e9 and climate.damage_usd("") == 0


def test_nri_scores_take_the_worst_field_per_hazard():
    s = climate.scores({"WNTW_RISKS": 20, "ISTM_RISKS": 55, "CWAV_RISKS": None, "HRCN_RISKS": 80})
    assert s["winter"] == 55 and s["tropical"] == 80 and s["wind"] == 0


def test_period_ranges():
    today = date(2026, 9, 26)
    assert exposure.period_range("now7", today=today) == (today, date(2026, 10, 3))
    assert exposure.period_range("month", 3, today=today) == (date(2027, 3, 1), date(2027, 3, 31))
    assert exposure.period_range("window", window=(datetime(2027, 1, 1), datetime(2027, 6, 30)), today=today) == (date(2027, 1, 1), date(2027, 6, 30))


def test_month_shares_and_history_scale_to_the_period():
    shares = exposure.month_shares(date(2026, 6, 20), date(2026, 7, 10))
    assert shares == {6: 11, 7: 10}
    rows = [{"county_fips": "a", "month": 6, "hazard": "heat", "event_days": 30, "years": 10},   # 3 days per june on average
            {"county_fips": "b", "month": 6, "hazard": "heat", "event_days": 60, "years": 10},
            {"county_fips": "a", "month": 1, "hazard": "winter", "event_days": 50, "years": 10}]  # january is outside the period
    h = exposure.history_days(rows, shares)
    assert h == {"heat": {"low": 1.1, "high": 2.2, "counties": 2}}


def test_live_days_count_calendar_days_per_hazard():
    rows = [{"hazard": "wind", "period_start": datetime(2026, 9, 26, 12, tzinfo=timezone.utc), "period_end": datetime(2026, 9, 28, 6, tzinfo=timezone.utc)},
            {"hazard": "wind", "period_start": datetime(2026, 9, 27, 0, tzinfo=timezone.utc), "period_end": datetime(2026, 9, 27, 1, tzinfo=timezone.utc)},
            {"hazard": "flood", "period_start": datetime(2026, 9, 20, 0, tzinfo=timezone.utc), "period_end": datetime(2026, 9, 21, 0, tzinfo=timezone.utc)}]
    assert exposure.live_days(rows, date(2026, 9, 26), date(2026, 10, 3)) == {"wind": 3, "flood": 0}


def test_api_query_parsing():
    assert parse_hazards("wind,storms,nope") == ["wind", "storms"] and parse_hazards(None) == list(HAZARDS)
    assert parse_bbox("-85,30,-80,35") == (-85, 30, -80, 35) and parse_bbox("x") is None


def test_polygon_only_gives_points_a_footprint():
    assert isinstance(layers.polygon_only(Point(0, 0)), Polygon)
