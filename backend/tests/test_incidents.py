import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.geo import nominatim
from app.storm import incidents, live, news

FIX = Path(__file__).parent / "fixtures"
T0 = datetime(2024, 9, 27, 9, tzinfo=timezone.utc)


def item(kind="downed_line", lon=-81.96, lat=33.47, hours=0.0, stype="news", name="wrdw.com", method="gemini", precision="town", quote=None):
    return {"ts": T0 + timedelta(hours=hours), "kind": kind, "lon": lon, "lat": lat, "where_text": "Augusta, GA", "precision": precision,
            "utility_mentioned": None, "customers_affected": None,
            "sources": [{"type": stype, "name": name, "url": f"https://{name}/a", "quote_evidence": quote or f"report from {name}", "method": method}]}


def test_classify():
    assert incidents.classify("Trees and power lines down along Highway 25") == "downed_line"
    assert incidents.classify("A tree fell onto power lines on Walton Way") == "tree_on_line"
    assert incidents.classify("The Martinez substation flooded") == "substation_damage"
    assert incidents.classify("12,000 customers without power in Aiken") == "outage"
    assert incidents.classify("Trees down on Route 1", "TORNADO") == "tornado"
    assert incidents.classify("Large limbs down") == "wind_damage"


def test_customers_and_utility():
    assert incidents.customers("Georgia Power said 1,200 customers and later 15,400 customers were out") == 15400
    assert incidents.customers("no numbers here") is None
    assert incidents.utility("crews from Georgia Power are working") == "Georgia Power"
    assert incidents.utility("Dominion Energy reported outages") == "Dominion Energy"


def test_merge_rule():
    merged = incidents.merge([item(), item(lon=-81.95, hours=2, name="wjbf.com"), item(kind="outage", hours=1),
                              item(lon=-81.90, hours=3), item(hours=7)])
    kinds = sorted((m["kind"], len(m["sources"])) for m in merged)
    assert kinds == [("downed_line", 1), ("downed_line", 1), ("downed_line", 2), ("outage", 1)]  # 1 km apart merges, 6 km or 7 h do not


def test_news_never_overrides_official():
    merged = incidents.merge([item(lon=-81.955, lat=33.475), item(stype="official", name="NWS local storm report", hours=1, precision="road")])
    assert len(merged) == 1 and merged[0]["lon"] == -81.96 and merged[0]["precision"] == "road"


def test_confidence_and_verified():
    one = incidents.merge([item()])[0]
    two = incidents.merge([item(), item(name="wjbf.com", hours=1)])[0]
    off = incidents.merge([item(stype="official", name="SPC storm report", precision="road")])[0]
    rules = incidents.merge([item(method="rules")])[0]
    unknown = incidents.merge([item(name="someblog.net")])[0]
    c1, v1 = incidents.score(one)
    c2, v2 = incidents.score(two)
    co, vo = incidents.score(off)
    cr, _ = incidents.score(rules)
    cu, _ = incidents.score(unknown)
    assert not v1 and v2 and vo  # official or two independent sources
    assert c2 > c1 > cr and c1 > cu and co > c2
    assert incidents.score(one, official_nearby=True)[0] > c1


def test_syndicated_copies_are_not_independent():
    wire = "Police escorted an ambulance around downed power lines."
    syndicated = incidents.merge([item(name="wlky.com", quote=wire), item(name="kmbc.com", quote=wire, hours=1)])[0]
    same_outlet = incidents.merge([item(name="wrdw.com", quote="a"), item(name="wrdw.com", quote="b", hours=1)])[0]
    assert incidents.independent(syndicated["sources"]) == 1 and not incidents.score(syndicated)[1]
    assert incidents.independent(same_outlet["sources"]) == 1


def test_precision_mapping():
    assert nominatim.precision({"addresstype": "road"}) == "road"
    assert nominatim.precision({"addresstype": "town"}) == "town"
    assert nominatim.precision({"addresstype": "county"}) == "county"
    assert nominatim.precision({"addresstype": "house"}) == "exact"


ROW = {"url": "https://wrdw.com/story", "date": "20240927120000", "domain": "wrdw.com", "title": "Helene knocks out power across the CSRA",
       "places": [{"full": "Hephzibah, Georgia, United States", "name": "Hephzibah", "lat": 33.31, "lon": -82.10, "adm1": "USGA"}]}
TEXT = ("Crews worked overnight. Downed power lines closed Highway 25 in Hephzibah early Friday. "
        "Georgia Power said 1,200 customers were without power in Richmond County.")


def test_llm_extract_validates_schema_and_quotes(monkeypatch):
    fake = {"incidents": [
        {"what": "downed_line", "where_text": "Highway 25, Hephzibah, Richmond County, GA", "quote_evidence": "Downed power lines closed Highway 25 in Hephzibah early Friday."},
        {"what": "meteor", "where_text": "Augusta", "quote_evidence": "Crews worked overnight."},
        {"what": "outage", "where_text": "Martinez, GA", "quote_evidence": "The Martinez substation was underwater."},
    ]}
    monkeypatch.setattr(news, "_llm", lambda prompt: json.dumps(fake))
    ok, rejected = news.llm_extract(ROW, TEXT)
    assert [e.what for e in ok] == ["downed_line"]
    assert {r["reason"] for r in rejected} >= {"quote not found in article"} and len(rejected) == 2


def test_llm_items_are_geocoded_by_code(monkeypatch):
    fake = {"incidents": [{"what": "downed_line", "where_text": "Highway 25, Hephzibah, GA", "quote_evidence": "Downed power lines closed Highway 25 in Hephzibah early Friday.",
                           "customers_affected": 1200}]}
    monkeypatch.setattr(news, "_llm", lambda prompt: json.dumps(fake))
    monkeypatch.setattr(nominatim, "lookup", lambda q: {"lat": "33.30", "lon": "-82.09", "addresstype": "road"})
    items = news.items_for(ROW, TEXT, use_llm=True)
    assert len(items) == 1 and items[0]["precision"] == "road" and items[0]["sources"][0]["method"] == "gemini"


def test_rule_fallback_needs_town_and_reported_power_damage():
    items = news.items_for(ROW, TEXT, use_llm=False)
    assert [(i["kind"], i["precision"]) for i in items] == [("downed_line", "town"), ("outage", "town")]
    assert items[0]["sources"][0]["method"] == "rules" and "Hephzibah" in items[0]["sources"][0]["quote_evidence"]
    assert items[1]["customers_affected"] == 1200
    assert news.items_for({**ROW, "title": "Storm recap"}, "Trees fell across town.", use_llm=False) == []
    assert news.items_for(ROW, "Georgia Power expects outages in Hephzibah tonight.", use_llm=False) == []  # forecasts are not damage
    assert news.items_for({**ROW, "title": "Storm recap"}, "Recap. Weather. Lines are down across the county.", use_llm=False) == []  # town never named
    assert news.items_for(ROW, "Hephzibah update. Stay away from downed power lines.", use_llm=False) == []  # advice, not a report
    assert news.items_for(ROW, "Hephzibah update. Millions are without power across the Southeast.", use_llm=False) == []  # roundup
    assert news.items_for(ROW, "Hephzibah update. 900,000 customers in Georgia and 800,000 in Florida were without power.", use_llm=False) == []
    assert news.items_for(ROW, "Hephzibah update. Customers can report and check the status of an outage online.", use_llm=False) == []


def test_gkg_filter_keeps_region_power_articles():
    cols = [""] * 27
    cols[4], cols[1], cols[3] = "https://wrdw.com/x", "20240927120000", "wrdw.com"
    cols[7] = "MANMADE_DISASTER_DOWNED_POWER_LINES;NATURAL_DISASTER_HURRICANE"
    cols[10] = "3#Grovetown, Georgia, United States#US#USGA#GA073#33.4504#-82.1982#355789#120;3#Tampa, Florida, United States#US#USFL##27.9#-82.4#1#5"
    cols[26] = "<PAGE_TITLE>Downed lines in Grovetown</PAGE_TITLE>"
    other = list(cols)
    other[7] = "SPORTS"
    rows = news.gkg_rows("\t".join(cols) + "\n" + "\t".join(other) + "\n")
    assert len(rows) == 1 and rows[0]["places"][0]["name"] == "Grovetown" and rows[0]["title"] == "Downed lines in Grovetown"


def test_live_parsers():
    alerts = live.parse_alerts(json.loads((FIX / "nws_alerts.json").read_text()),
                               zone_geometry=lambda url: {"type": "Polygon", "coordinates": [[[-81.3, 32.0], [-81.0, 32.0], [-81.0, 32.2], [-81.3, 32.0]]]})
    assert [a[3]["label"] for a in alerts] == ["Tornado Warning", "Wind Advisory"] and all(a[2] for a in alerts)
    now = datetime(2026, 9, 26, 20, tzinfo=timezone.utc)
    spc = live.parse_spc((FIX / "spc_today_wind.csv").read_text(), "wind", now)
    assert len(spc) == 2 and spc[0][0] == datetime(2026, 9, 26, 15, 30, tzinfo=timezone.utc) and spc[1][0].day == 27
    lsr = live.parse_lsr(json.loads((FIX / "lsr.json").read_text()))
    assert lsr[0][3]["mode"] == "live" and "Walton Way" in lsr[0][3]["remark"]


def test_daily_gusts_and_alert_text():
    gusts = live.daily_gusts(json.loads((FIX / "gridpoint.json").read_text()))
    assert max(gusts.values()) == 45  # 72.4 km/h
    day = max(gusts, key=gusts.get)
    assert live.alert_text(45, day, "Okatie", "crane lift") == f"Gusts of 45 mph forecast {day:%A} at the Okatie site; the crane lift should move."


@pytest.fixture
def conn():
    try:
        from app.db import connect
        c = connect()
    except Exception:
        pytest.skip("database not reachable")
    if not c.execute("SELECT to_regclass('incident') AS t").fetchone()["t"] or not c.execute("SELECT 1 FROM incident LIMIT 1").fetchone():
        c.close()
        pytest.skip("no incidents loaded")
    yield c
    c.rollback()  # leave the database as it was
    c.close()


def test_grid_connection(conn):
    from app.storm.restoration import build_restoration
    news_only = item(kind="downed_line", lon=-81.1751, lat=32.3521, name="someblog.net")  # right at Plant McIntosh
    incidents.rebuild(conn, "replay", [news_only])
    n = build_restoration(conn)
    assert n >= 41
    jobs = conn.execute("SELECT name, confidence FROM job WHERE horizon = 'emergency' AND name LIKE '%%needs confirmation%%'").fetchall()
    assert all(j["confidence"] <= 0.4 for j in jobs)  # unverified news alone stays low priority
    near = conn.execute("SELECT nearest FROM incident WHERE mode = 'replay' AND nearest IS NOT NULL LIMIT 1").fetchone()
    assert near and all("asset" in v and "km" in v for v in near["nearest"].values())


def test_phase_risks_with_fake_forecast(conn):
    grid = json.loads((FIX / "gridpoint.json").read_text())
    out = live.phase_risks(conn, limit_mph=0, fetch=lambda lat, lon: grid, store=False)  # zero limit: every active day alerts
    assert out["phases_checked"] >= 0 and all(r[5].startswith("Gusts of") for r in out["rows"])
