import inspect

import psycopg
import pytest

from app.db import DATABASE_URL, connect

try:
    with psycopg.connect(DATABASE_URL, connect_timeout=3) as c:
        JOBS = c.execute("SELECT count(*) FROM job").fetchone()[0]
except Exception:  # no server or no schema yet
    JOBS = 0
if not JOBS:
    pytest.skip("database not reachable or empty; run scripts.build_all first", allow_module_level=True)

from app.crewly import agent  # noqa: E402
from app.crewly.tools import TOOLS  # noqa: E402
from scripts.crewly_eval import gpc_contact, hooks, jasper  # noqa: E402


@pytest.fixture
def conn(monkeypatch):
    for key in ("GEMINI_API_KEY", "RESEND_API_KEY", "GOOGLE_PLACES_KEY"):
        monkeypatch.delenv(key, raising=False)
    with connect() as c:
        yield c
        c.rollback()  # tools that write (status, drafts) never persist


def call(conn, name, **args):
    return TOOLS[name][0](conn, **args)


def test_declarations_match_functions():
    for name, (fn, desc, props, required) in TOOLS.items():
        params = inspect.signature(fn).parameters
        assert desc and set(required) <= set(props), name
        assert all(p in params for p in props), f"{name} declares params its function lacks"
        assert all(p.default is not inspect.Parameter.empty or p.name in required or p.name == "conn" for p in params.values()), name
    assert len(agent._declarations()) == len(TOOLS)


def test_find_and_explain(conn):
    r, ui = call(conn, "find_overlaps", region="savannah")
    assert r["count"] > 0 and ui[0]["type"] == "filter"
    oid = jasper(conn)
    r, ui = call(conn, "get_opportunity", opportunity_id=oid)
    assert r["tier"] == "site" and r["in_service_gap_days"] == 152 and ui[0]["opportunity_id"] == oid
    assert "error" in call(conn, "get_opportunity", opportunity_id=-1)[0]


def okatie_kraft(conn):
    return conn.execute("""SELECT op.id FROM opportunity op JOIN job a ON a.id = op.job_a JOIN job b ON b.id = op.job_b
                           WHERE op.horizon = 'long' AND a.name LIKE 'Okatie-Bluffton%%' AND b.name LIKE '%%KRAFT%%'""").fetchone()["id"]


def test_savings_what_ifs(conn):
    yard = {"yard_usd": {"low": 500000, "high": 800000}}
    r = call(conn, "estimate_savings", opportunity_id=jasper(conn), assumptions=yard)[0]
    assert r["savings_usd"] == "$0 to $0" and not r["crews_and_yards_shareable"] and r["drive_minutes"] > 45  # 3 mi apart, an hour by road
    mob = {"mobilization_usd": {"low": 100000, "high": 200000}}
    assert call(conn, "estimate_savings", opportunity_id=okatie_kraft(conn), assumptions=mob)[0]["savings_usd"] == "$100,000 to $200,000"
    r, ui = call(conn, "set_assumptions", overrides=mob, opportunity_id=okatie_kraft(conn))
    assert r["opportunities"][0]["new_savings_usd"] == "$100,000 to $200,000" and not r["saved"]
    assert ui[0]["type"] == "assumptions" and ui[0]["values"]["mobilization_usd"] == {"low": 100000.0, "high": 200000.0}
    assert "error" in call(conn, "set_assumptions", overrides={"bogus": {"low": 1, "high": 2}})[0]
    assert "error" in call(conn, "set_assumptions", overrides={"yard_usd": {"low": 9, "high": 1}})[0]


def test_projects(conn):
    assert call(conn, "search_projects", query="thomson second transformer")[0]["matches"][0]["job_id"] == "gpc-14222"
    r, ui = call(conn, "project_details", query="Thomson Primary second transformer")
    assert r["job_id"] == "gpc-14222" and any("2031" in h["window"] for h in r["plan_history"]) and ui[0]["type"] == "fly"
    assert call(conn, "project_details", query="Kathleen Area Improvements")[0]["placed"] is False
    assert "error" in call(conn, "project_details", query="nonexistent zzz project")[0]
    r, _ = call(conn, "compare_projects", a="Jasper Okatie", b="Goshen McIntosh")
    assert r["center_to_center_mi"] == 7.55 and r["tier"] == "site" and r["opportunity_id"]


def test_queues_and_equipment(conn):
    r, ui = call(conn, "review_queue")
    assert r["total"] == sum(c["n"] for c in r["by_utility_and_reason"]) and ui[0]["tab"] == "review"
    r, ui = call(conn, "equipment_matches")
    assert any("Summerville" in g["desc_project"] for g in r["groups"]) and ui[0]["tab"] == "equipment"


def test_status_and_outreach(conn):
    oid = jasper(conn)
    r, ui = call(conn, "set_status", opportunity_id=oid, status="call_scheduled")
    assert r["new_status"] == "call_scheduled" and {a["type"] for a in ui} == {"select", "status"}
    assert "error" in call(conn, "set_status", opportunity_id=oid, status="bogus")[0]
    assert any(c["utility"] == "Georgia Power" for c in call(conn, "find_contacts", opportunity_id=oid)[0]["contacts"])
    r, _ = call(conn, "draft_outreach", opportunity_id=oid, contact_id=gpc_contact(conn))
    assert r["state"] == "draft" and "approve" in r["note"]


def test_views_brief_storm(conn):
    assert call(conn, "switch_view", horizon="near", tier="crew")[1][0] == {"type": "view", "horizon": "near", "tier": "crew", "tab": None}
    assert "error" in call(conn, "switch_view", tab="nope")[0]
    r, ui = call(conn, "timeline_filter", years=[2027, 2025], orgs=["desc"])
    assert r["years"] == [2025, 2027] and ui[0]["type"] == "timeline"
    assert "error" in call(conn, "timeline_filter", orgs=["zzz"])[0]
    r, ui = call(conn, "draft_brief", opportunity_id=hooks(conn))
    assert "Summary" in r["sections"] and ui[0]["type"] == "brief" and ui[0]["markdown"].startswith("# Coordination brief")
    r, ui = call(conn, "storm_status", hours_from_landfall=15)
    assert r["shared_staging_points"] and ui[0]["type"] == "storm"
    assert call(conn, "focus_map", region="augusta")[1][0]["type"] == "fly"


def test_keyless_tools_fail_gracefully(conn):
    assert "GOOGLE_PLACES_KEY" in call(conn, "find_vendors", opportunity_id=jasper(conn))[0]["error"]
    assert "private" in call(conn, "ingest_filing", url="http://127.0.0.1:8000/x.pdf")[0]["error"]
    assert "offline" in agent.run(conn, [{"role": "user", "text": "hi"}])["reply"]
