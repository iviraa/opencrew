import pytest

from app.geo import audit, geolocate, llm_pick
from app.geo.names import clean, endpoint_names, foreign, mentioned_stations, stated_full_miles
from app.ingest.pipeline import geometry, outside_zone


def test_clean_strips_equipment_and_prefixes():
    assert clean("SAV: RICE HOPE NEW AUTO TRANSFORMER") == "RICE HOPE"
    assert clean("GRADY 230/115KV RELAY MODERNIZATION") == "GRADY"


def test_endpoint_names_splits_and_drops_customer_tag():
    assert endpoint_names({"name": "x", "endpoints": ["THALMANN AND COLERAIN"]}) == ["THALMANN", "COLERAIN"]
    assert endpoint_names({"name": "x", "endpoints": ["CC", "SHUGART"]}) == ["SHUGART"]


def test_mentions_keep_full_station_name():
    text = "Install reactors at Line Creek 230kV substation and at the Anthony Shoals substation."
    assert mentioned_stations(text) == ["Line Creek", "Anthony Shoals"]


def test_stated_miles_ignores_segments():
    assert stated_full_miles("Rebuild the 11 mile line with 1033 ACSR") == 11
    assert stated_full_miles("Rebuild 4 miles of the Adamsville - Buzzard Roost line") is None


def test_foreign_endpoint():
    assert foreign("WEBB (APC)") and not foreign("LOWER RIVER")


def pick(name, lat, lon, conf=1.0, via="node/1", query=None, approx=False):
    return {"name": name, "lat": lat, "lon": lon, "conf": conf, "via": via, "query": query or name, "approx": approx}


def test_audit_flags_line_much_longer_than_filing():
    job = {"name": "A - B", "description": "Rebuild the 5 mile line"}
    coords = [[-84.0, 33.0], [-84.0, 33.6]]  # ~41 mi
    status, reasons = audit.assess(job, [pick("A", 33.0, -84.0), pick("B", 33.6, -84.0)], coords)
    assert status == "wrong" and "filing says 5 mi" in reasons[0]


def test_audit_flags_weak_name_and_town_only():
    job = {"name": "EDENWOOD SUB", "description": ""}
    status, reasons = audit.assess(job, [pick("Danwood Substation", 34.0, -81.0, query="Edenwood")], [[-81.0, 34.0]])
    assert status == "suspect" and "name score" in reasons[0]
    status, _ = audit.assess(job, [pick("Kathleen", 32.5, -83.6, approx=True, via="town:Kathleen")], [[-83.6, 32.5]])
    assert status == "suspect"


def test_audit_ok_for_exact_close_match():
    job = {"name": "ANTHONY SHOALS", "description": ""}
    status, reasons = audit.assess(job, [pick("Anthony Shoals", 34.0, -82.6)], [[-82.6, 34.0]], zone=((34.1, -82.7), 60))
    assert status == "ok" and reasons == []


def test_weak_pick_outside_planning_zone_is_rejected():
    job = {"name": "ADAMSVILLE - X", "zone": "208"}
    far = pick("Adairsville Substation", 34.37, -84.93, conf=0.7, via="node/9")
    assert "planning zone 208" in outside_zone(job, [far, None], {"208": ((33.4, -84.4), 60)})
    assert outside_zone(job, [pick("Adamsville", 33.75, -84.5), None], {"208": ((33.4, -84.4), 60)}) is None


def test_town_geometry_is_approx_and_capped():
    job = {"job_type": "substation"}
    wkt, quality, conf = geometry(job, [pick("Kathleen", 32.5, -83.6, conf=0.35, approx=True)])
    assert quality == "approx_area" and conf <= 0.4 and wkt.startswith("POINT")


@pytest.fixture
def loc(monkeypatch):
    geolocate.HOME.setdefault("gpc", "GA")
    loc = geolocate.Locator.__new__(geolocate.Locator)  # skip loading the real layers
    loc.gold, loc.gold_project, loc._prepared = {}, {}, {}
    loc.osm = [{"osm": "node/1", "name": "Pine Mountain Substation", "operator": "Georgia Power", "lat": 32.86, "lon": -84.85},
               {"osm": "node/2", "name": "Scottdale Substation", "operator": "Georgia Power", "lat": 33.79, "lon": -84.26}]
    for s in loc.osm:
        s["norm"] = geolocate.norm(s["name"])
    monkeypatch.setattr(loc, "home", lambda org: type("H", (), {"contains": lambda self, p: True})())
    monkeypatch.setattr(loc, "town", lambda org, name: None)
    return loc


def test_word_coverage_rejects_partial_name(loc):
    assert loc.candidates("gpc", "MOUNTAIN VIEW") == []
    assert loc.candidates("gpc", "SCOTTDALE")[0]["via"] == "node/2"


def test_gemini_only_chooses_among_candidates(loc, monkeypatch):
    seen = {}

    def choose(job, options):
        seen["options"] = options
        return options[0]

    monkeypatch.setattr(llm_pick, "choose", choose)
    job = {"name": "PINE RELAY", "endpoints": None, "description": ""}
    picks, why = loc.place_job("gpc", job)
    assert why is None and picks[0]["via"] == "gemini:node/1" and picks[0]["conf"] == geolocate.LLM_CONF
    assert (picks[0]["lat"], picks[0]["lon"]) == (seen["options"][0]["lat"], seen["options"][0]["lon"])  # coordinates come from OSM


def test_unplaced_gets_a_reason(loc, monkeypatch):
    monkeypatch.setattr(llm_pick, "choose", lambda job, options: None)
    picks, why = loc.place_job("gpc", {"name": "CC - PROJECT PAYTON BAINBRIDGE", "endpoints": None, "description": ""})
    assert picks == [None] and "customer connection" in why


def test_llm_pick_never_returns_outside_options(monkeypatch, tmp_path):
    monkeypatch.setattr(llm_pick, "CACHE", tmp_path / "cache.json")
    monkeypatch.setattr(llm_pick, "provider", lambda: "gemini")
    monkeypatch.setattr(llm_pick, "_down", [False])
    monkeypatch.setattr(llm_pick, "generate_json", lambda prompt, schema: '{"choice": 7, "reason": "made up"}')
    assert llm_pick.choose({"name": "X"}, [{"osm": "node/1", "name": "A"}]) is None
