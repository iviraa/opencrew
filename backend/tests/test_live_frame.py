import json
from datetime import datetime, timedelta, timezone

import pytest

from app.storm import live
from app.storm.helene import LANDFALL, REPLAY


@pytest.fixture
def conn():
    try:
        from app.db import connect
        c = connect()
    except Exception:
        pytest.skip("database not reachable")
    if not c.execute("SELECT to_regclass('incident') AS t").fetchone()["t"] or not c.execute("SELECT 1 FROM job LIMIT 1").fetchone():
        c.close()
        pytest.skip("no data loaded")
    yield c
    c.rollback()  # leave the database as it was
    c.close()


@pytest.fixture
def client(conn):
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def test_topic_rules():
    assert live.topic("outage", "Thousands without power") == "outage"
    assert live.topic("downed_line", "") == "damage"
    assert live.topic("other", "Georgia Power starts transmission line rebuild") == "work"
    assert live.topic("other", "City council meets") == "other"


def test_news_pins_group_copies_and_keep_worst_topic():
    geo = {"type": "Point", "coordinates": [-81.1, 32.1]}
    ts = datetime(2024, 9, 27, tzinfo=timezone.utc)
    row = lambda title, kind, url: {"geometry": geo, "title": title, "kind": kind, "url": url, "source": "x.com", "quote": "q", "published": None,
                                    "verified": False, "ts": ts, "near_name": "Kraft", "near_mi": 1.2}
    pins = live.news_pins([row("Lines down in Savannah", "downed_line", "a"), row("Lines down in Savannah", "downed_line", "b"),
                           row("Crews start rebuild project", "other", "c")])
    assert len(pins) == 1  # same place, one pin
    p = pins[0]["properties"]
    assert p["count"] == 2 and p["topic"] == "damage" and p["articles"][0]["copies"] == 2  # syndicated copies collapse


def test_frame_now_is_live(client):
    d = client.get("/api/live/frame").json()
    assert d["scenario"] == "none" and d["mode"] == "live" and d["is_live"]
    start, end = (datetime.fromisoformat(x) for x in d["range"])
    assert end - start == timedelta(days=live.HISTORY_DAYS)
    assert all(f["properties"]["phase"] for f in d["active_phases"]["features"])


def test_frame_scenario_time(client):
    d = client.get("/api/live/frame", params={"scenario": "helene", "at": (LANDFALL + timedelta(hours=12)).isoformat()}).json()
    assert d["mode"] == "replay" and d["storm_active"] and not d["is_live"]
    assert d["range"] == [REPLAY[0].isoformat(), REPLAY[1].isoformat()]
    assert d["incidents"]["features"] and all("age_h" in f["properties"] for f in d["incidents"]["features"])
    assert client.get("/api/live/frame", params={"scenario": "nope"}).status_code == 400


def test_news_far_from_sites_gets_no_pin(conn):
    t = datetime.now(timezone.utc) - timedelta(hours=1)
    src = lambda url: json.dumps([{"type": "news", "name": "x.com", "url": url, "title": "Power out", "ts": t.isoformat()}])
    conn.execute("""INSERT INTO incident (ts, mode, kind, geom, where_text, precision, confidence, verified, needs_confirmation, sources)
                    VALUES (%s, 'live', 'outage', ST_GeogFromText('POINT(-70 40)'), 'Atlantic Ocean', 'town', 0.3, false, true, %s)""",
                 (t, src("https://far.example/1")))  # nowhere near any grid site
    near = conn.execute("SELECT ST_X(ST_PointOnSurface(geom::geometry)) AS x, ST_Y(ST_PointOnSurface(geom::geometry)) AS y FROM job WHERE horizon = 'long' LIMIT 1").fetchone()
    conn.execute("""INSERT INTO incident (ts, mode, kind, geom, where_text, precision, confidence, verified, needs_confirmation, sources)
                    VALUES (%s, 'live', 'outage', ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, 'Near a site', 'town', 0.3, false, true, %s)""",
                 (t, near["x"], near["y"], src("https://near.example/1")))
    urls = {a["url"] for f in live.frame(conn)["news"]["features"] for a in f["properties"]["articles"]}
    assert "https://near.example/1" in urls and "https://far.example/1" not in urls
