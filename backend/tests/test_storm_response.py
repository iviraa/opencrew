from datetime import datetime, timedelta

import psycopg
import pytest

from app.db import DATABASE_URL

try:
    with psycopg.connect(DATABASE_URL, connect_timeout=3) as c:
        JOBS = c.execute("SELECT count(*) FROM job WHERE horizon = 'emergency'").fetchone()[0]
except Exception:  # no server or no schema yet
    JOBS = 0
if not JOBS:
    pytest.skip("database not reachable or has no storm data; run scripts.build_all first", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402

from app.crewly.tools import TOOLS  # noqa: E402
from app.db import connect  # noqa: E402
from app.main import app  # noqa: E402
from app.storm import briefing, helene  # noqa: E402


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def brief(client):
    r = client.get("/api/storm/briefing", params={"at": (helene.LANDFALL - timedelta(hours=36)).isoformat()})
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="module")
def plan(client):
    r = client.get("/api/storm/restoration_plan", params={"at": (helene.LANDFALL + timedelta(hours=24)).isoformat()})
    assert r.status_code == 200
    return r.json()


def test_briefing_has_forecast_and_hits(brief):
    s = brief["storm"]
    assert s and s["cone"]["type"] in ("Polygon", "MultiPolygon") and s["advisory"]
    gpc = next(h for h in brief["likely_hit"] if h["org"] == "gpc")
    assert gpc["damaging_winds"] > 0 and gpc["tropical_storm_winds"] >= gpc["damaging_winds"] >= gpc["hurricane_winds"]
    assert brief["headline"].startswith("Helene")


def test_pause_comes_before_winds(brief):
    assert brief["pause"]
    for p in brief["pause"]:
        assert datetime.fromisoformat(p["pause_by"]) < datetime.fromisoformat(p["arrival"])
        assert p["sentence"]


def test_staging_and_crews(brief):
    assert len(brief["staging"]) >= 1 and all(s["sentence"] and s["serves"] for s in brief["staging"])
    assert all(c["crews"] >= 0 for c in brief["crews"])


def test_no_storm_outside_scenario(client):
    assert client.get("/api/storm/briefing", params={"scenario": "none"}).json()["storm"] is None
    early = client.get("/api/storm/briefing", params={"at": (helene.LANDFALL - timedelta(days=10)).isoformat()}).json()
    assert early["storm"] is None


def test_arrival_math():
    adv = briefing.advisory_at(helene.LANDFALL - timedelta(hours=36))
    first = adv["points"][0]
    assert briefing.arrival(adv, first["lon"], first["lat"]) is not None  # the storm center itself is inside its own wind field
    assert briefing.arrival(adv, -60.0, 45.0) is None  # far out in the Atlantic never gets winds


def test_mutual_aid_never_worse(plan):
    a, m = plan["summary"]["alone"], plan["summary"]["mutual_aid"]
    assert m["weighted_wait_hours"] <= a["weighted_wait_hours"] + 1e-9
    assert plan["jobs"] > 0 and plan["headline"]


def test_explanations_and_routes(plan):
    assert plan["explanations"] and all(x["sentence"] for x in plan["explanations"])
    covered = [j["job_id"] for r in plan["routes"] for j in r["jobs"]]
    assert len(covered) == len(set(covered)) == plan["jobs"]  # every repair job gets exactly one crew
    for r in plan["routes"]:
        spans = sorted((datetime.fromisoformat(j["start"]), datetime.fromisoformat(j["end"])) for j in r["jobs"])
        assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))  # a crew does one job at a time
    for x in plan["explanations"]:
        if x["cross_utility"]:
            assert "nearest crew" in x["sentence"] or "no crew" in x["sentence"]


def test_before_damage_has_no_jobs(client):
    r = client.get("/api/storm/restoration_plan", params={"at": (helene.LANDFALL - timedelta(hours=72)).isoformat()}).json()
    assert r["jobs"] == 0 and r["headline"]


def test_crewly_storm_tools(plan):
    with connect() as c:
        b, ui = TOOLS["storm_briefing"][0](c)
        assert b["headline"] and ui[0]["type"] == "storm"
        r, _ = TOOLS["restoration_plan"][0](c)
        assert r["summary"]["mutual_aid"]["weighted_wait_hours"] <= r["summary"]["alone"]["weighted_wait_hours"] + 1e-9
        crew = plan["explanations"][0]["crew"]
        e, _ = TOOLS["explain_assignment"][0](c, crew=crew)
        assert e["assignments"]
        assert "error" in TOOLS["explain_assignment"][0](c, crew="nobody here")[0]
