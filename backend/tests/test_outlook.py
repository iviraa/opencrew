import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from shapely import STRtree, wkt
from shapely.geometry import LineString, Point

from app.storm import hazards, outlook

F = Path(__file__).parent / "fixtures/outlooks"
UTC = timezone.utc


def load(name):
    return json.loads((F / name).read_text())


# ---------- parsers ----------

def test_spc_day1_keeps_severe_levels_in_the_southeast():
    rows = outlook.parse_spc(load("spc_day1_20240926.geojson"), 1, "replay")
    assert [r["level"] for r in rows] == ["MRGL", "SLGT", "ENH"]  # general thunder is dropped
    assert [r["rank"] for r in rows] == [1, 2, 3]
    r = rows[-1]
    assert r["issued"] == datetime(2024, 9, 26, 6, 0, tzinfo=UTC)
    assert (r["valid_from"], r["valid_to"]) == (datetime(2024, 9, 26, 12, tzinfo=UTC), datetime(2024, 9, 27, 12, tzinfo=UTC))
    assert r["label"] == "SPC enhanced risk"
    minx, miny, maxx, maxy = wkt.loads(r["wkt"]).bounds
    assert minx >= -89 and maxx <= -74 and miny >= 24 and maxy <= 37.5  # clipped to the southeast


def test_spc_day4_with_nothing_forecast_gives_no_rows():
    assert outlook.parse_spc48(load("spc_day4_too_low.geojson"), 4) == []


def test_spc_day4_probability_levels():
    data = {"features": [
        {"geometry": {"type": "Polygon", "coordinates": [[[-84, 31], [-81, 31], [-81, 33], [-84, 33], [-84, 31]]]},
         "properties": {"LABEL": "0.15", "VALID": "202409271200", "EXPIRE": "202409281200", "ISSUE": "202409240900"}},
        {"geometry": {"type": "Polygon", "coordinates": [[[-83, 31.5], [-82, 31.5], [-82, 32.5], [-83, 32.5], [-83, 31.5]]]},
         "properties": {"LABEL": "0.30", "VALID": "202409271200", "EXPIRE": "202409281200", "ISSUE": "202409240900"}}]}
    rows = outlook.parse_spc48(data, 4, "replay")
    assert [(r["level"], r["rank"]) for r in rows] == [("15%", 2), ("30%", 3)]
    assert rows[0]["label"] == "SPC 15% chance of severe storms"


def test_wpc_ero_parses_times_and_drops_areas_outside_the_southeast():
    rows = outlook.parse_ero(load("wpc_ero_day5.geojson"))
    assert len(rows) == 1  # the slight risk sits over the plains
    r = rows[0]
    assert (r["level"], r["rank"], r["day"]) == ("Marginal", 1, 5)
    assert r["label"] == "WPC marginal risk of flash flooding (at least 5%)"
    assert r["valid_from"] == datetime(2026, 9, 30, 12, tzinfo=UTC) and r["valid_to"] - r["valid_from"] == timedelta(days=1)


def test_gtwo_areas_from_the_archive():
    rows = outlook.gtwo_rows((F / "gtwo_areas.zip").read_bytes(), "replay", None)
    by_area = {r["props"]["area"]: r for r in rows}
    helene = by_area["2"]  # the western caribbean area that became helene
    assert (helene["level"], helene["rank"], helene["props"]["risk7day"]) == ("70%", 3, "High")
    assert helene["issued"] == datetime(2024, 9, 22, 5, 12, tzinfo=UTC)
    assert helene["valid_to"] - helene["valid_from"] == timedelta(days=7)
    assert outlook.basin_region(wkt.loads(helene["wkt"])) == "the Caribbean and the Gulf of Mexico"  # as nhc described it


def test_wsp_grid_points_become_nested_bands():
    rows = outlook.wsp_rows((F / "wsp_2024092512.zip").read_bytes(), "replay", None)
    assert [r["level"] for r in rows] == ["10%", "30%", "50%", "70%", "90%"]
    areas = [wkt.loads(r["wkt"]).area for r in rows]
    assert areas == sorted(areas, reverse=True) and areas[-1] > 0  # higher bands sit inside lower ones, as polygons
    assert rows[0]["issued"] == datetime(2024, 9, 25, 12, tzinfo=UTC) and rows[0]["valid_to"] - rows[0]["issued"] == timedelta(hours=120)


def test_utc_stamps():
    assert outlook.utc("202409261300") == datetime(2024, 9, 26, 13, tzinfo=UTC)
    assert outlook.utc("2024092512") == datetime(2024, 9, 25, 12, tzinfo=UTC)


# ---------- heads-up sentences ----------

KNOWN = datetime(2024, 9, 25, 12, tzinfo=UTC)  # 8 AM Wednesday in Georgia


def test_severe_sentence_with_work_sites_says_when_to_pause():
    f = {"kind": "severe", "day": "Tomorrow", "label": "SPC enhanced risk", "city": "Savannah", "known": KNOWN,
         "sites": ["A", "B"], "work_sites": ["A"], "assets": {"gpc": 129, "desc": 7},
         "pause_at": datetime(2024, 9, 26, 16, tzinfo=UTC)}
    assert outlook.describe(f) == ("Tomorrow: severe storms possible (SPC enhanced risk) around Savannah; 2 active work sites and "
                                   "136 substations (Georgia Power 129, DESC 7) inside; pause crane and line work by noon tomorrow")


def test_severe_sentence_without_sites_has_no_action():
    f = {"kind": "severe", "day": "Friday", "label": "SPC marginal risk", "city": "Florence", "known": KNOWN, "sites": [], "work_sites": [],
         "assets": {}, "pause_at": KNOWN + timedelta(days=2)}
    assert outlook.describe(f) == "Friday: severe storms possible (SPC marginal risk) around Florence; no active work sites and 0 substations inside"


def test_flood_wind_tropical_and_watch_sentences():
    base = {"known": KNOWN, "city": "Albany", "assets": {"gpc": 1}}
    assert outlook.describe({**base, "kind": "flood", "day": "Today", "label": "WPC slight risk of flash flooding", "sites": ["A"]}) == (
        "Today: flash flooding possible (WPC slight risk of flash flooding) around Albany; 1 active work site and 1 substation "
        "(Georgia Power 1) inside; plan crews around low-lying access roads")
    assert outlook.describe({**base, "kind": "wind", "level": "90%", "sites": []}) == (
        "90% or higher chance of tropical-storm-force winds around Albany in the next 5 days (NHC); no active work sites and "
        "1 substation (Georgia Power 1) inside")
    assert outlook.describe({"kind": "tropical", "prob": "70%", "risk": "High", "region": "the Caribbean"}) == (
        "NHC gives a 70% chance of a tropical storm forming in the Caribbean within 7 days (high risk)")
    until = datetime(2024, 9, 26, 22, tzinfo=UTC)
    assert outlook.describe({"kind": "watch", "label": "Hurricane Watch", "until": until, "places": "Chatham [GA]", "n_sites": 3}) == (
        "Hurricane Watch until Thursday 6 PM for Chatham [GA]; 3 active work sites inside")


def test_pause_time_wording():
    noon = lambda d: datetime(2024, 9, d, 16, tzinfo=UTC)  # noon eastern daylight time
    assert outlook.pause_text(noon(25), KNOWN) == "pause crane and line work by noon today"
    assert outlook.pause_text(noon(27), KNOWN) == "pause crane and line work by noon Friday"
    assert outlook.pause_text(noon(25), KNOWN + timedelta(hours=6)) == "pause crane and line work now"  # already past noon


def test_day_labels_follow_the_georgia_clock():
    late = datetime(2024, 9, 26, 2, tzinfo=UTC)  # 10 PM Wednesday eastern, already Thursday in utc
    assert outlook.day_label(late, late) == "Today"
    assert outlook.day_label(late + timedelta(hours=14), late) == "Tomorrow"
    assert outlook.day_label(KNOWN + timedelta(days=3), KNOWN) == "Saturday"
    assert outlook.nearest_city(32.1, -81.1) == "Savannah"


# ---------- long-range hazards ----------

def test_hurdat_parse_and_climatology():
    storms = hazards.parse_hurdat((F / "hurdat2_sample.txt").read_text())
    assert [s["name"] for s in storms] == ["Able", "Hugo", "Helene"]
    hugo = storms[1]
    assert hugo["year"] == 1989 and hugo["points"][0][:2] == (-20.0, 13.2)
    geoms, meta = hazards.track_pieces(storms)
    tree = STRtree(geoms)
    charleston = hazards.climatology(Point(-79.93, 32.78), tree, geoms, meta)
    assert charleston["hurricanes_50mi"] == 1 and charleston["peak_month"] == 9  # hugo made landfall there as a hurricane
    valdosta = hazards.climatology(LineString([(-83.4, 30.8), (-83.2, 30.9)]), tree, geoms, meta)
    assert valdosta["storms_50mi"] >= 1 and valdosta["hurricanes_50mi"] == 1  # helene crossed south georgia as a hurricane
    assert hazards.climatology(Point(-70, 45), tree, geoms, meta)["storms_50mi"] == 0


def test_nfhl_flags():
    assert hazards.parse_nfhl(load("nfhl_floodplain.json")) == (True, ["A", "AE"])
    assert hazards.parse_nfhl(load("nfhl_dry.json")) == (False, [])
    assert hazards.parse_nfhl(load("nfhl_unmapped.json")) == (None, [])  # no flood map, not "safe"


def test_hazard_sentences():
    h = {"in_floodplain": True, "flood_zones": ["AE", "X"], "hurricanes_50mi": 8, "storms_50mi": 40, "peak_month": 9, "since_year": 1950}
    out = hazards.describe(h, year=2026)
    assert out["in_floodplain"] is True and out["hurricane_exposure"] is True
    assert out["lines"] == ["Crosses a FEMA 100-year floodplain (zone AE)", "8 hurricanes passed within 50 miles since 1950, about one every 10 years",
                            "Storms here peak in September; avoid long outages then"]
    quiet = hazards.describe({"in_floodplain": None, "hurricanes_50mi": 0, "since_year": 1950})
    assert quiet["hurricane_exposure"] is False and quiet["lines"] == ["FEMA has no flood map here", "No hurricane passed within 50 miles since 1950"]


# ---------- stored outlooks (needs the database) ----------

@pytest.fixture
def conn():
    try:
        from app.db import connect, init_schema
        c = connect()
        init_schema(c)
    except Exception:
        pytest.skip("database not reachable")
    if not c.execute("SELECT 1 FROM job LIMIT 1").fetchone():
        c.close()
        pytest.skip("no data loaded")
    yield c
    c.rollback()  # leave the database as it was
    c.close()


def test_frame_only_uses_forecasts_known_at_the_time(conn):
    conn.execute("DELETE FROM outlook WHERE mode = 'test'")
    rows = [outlook.row("test", "spc", 1, datetime(2030, 1, d, 6, tzinfo=UTC), datetime(2030, 1, d, 12, tzinfo=UTC), datetime(2030, 1, d + 1, 12, tzinfo=UTC),
                        "SLGT", 2, "SPC slight risk", wkt.loads("POLYGON((-84 31,-81 31,-81 33,-84 33,-84 31))")) for d in (1, 2)]
    rows.append(outlook.row("test", "spc", 2, datetime(2030, 1, 1, 6, tzinfo=UTC), datetime(2030, 1, 2, 12, tzinfo=UTC), datetime(2030, 1, 3, 12, tzinfo=UTC),
                            "MRGL", 1, "SPC marginal risk", wkt.loads("POLYGON((-84 31,-81 31,-81 33,-84 33,-84 31))")))
    outlook.store(conn, rows)
    view = datetime(2030, 1, 2, 18, tzinfo=UTC)
    early = outlook.frame(conn, view, datetime(2030, 1, 1, 12, tzinfo=UTC), "test")  # looking ahead from jan 1
    assert [f["properties"]["level"] for f in early["features"]] == ["MRGL"]
    later = outlook.frame(conn, view, view, "test")  # the newer day 1 outlook replaces it
    assert [f["properties"]["level"] for f in later["features"]] == ["SLGT"]
    assert later["features"][0]["geometry"]["type"] == "Polygon"
    items = outlook.heads_up(conn, datetime(2030, 1, 2, 12, tzinfo=UTC), "test", days=1)
    assert len(items) == 1 and items[0]["text"].startswith("Today: severe storms possible (SPC slight risk) around")


def test_outlook_api_never_reads_forecasts_from_the_future(conn):
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    r = c.get("/api/outlook/frame", params={"scenario": "helene", "at": "2024-09-25T12:00:00Z"}).json()
    assert r["known"] == r["view"] == "2024-09-25T12:00:00+00:00"
    assert r["outlooks"]["type"] == "FeatureCollection" and isinstance(r["heads_up"], list)
    far = c.get("/api/outlook/frame", params={"scenario": "helene", "at": "2024-12-01T00:00:00Z"}).json()
    assert far["known"] == far["clock"] and far["view"] > far["clock"]  # looking ahead keeps the clock's forecasts
    assert c.get("/api/outlook/frame", params={"scenario": "nope"}).status_code == 400
