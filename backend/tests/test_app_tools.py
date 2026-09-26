import time
from datetime import datetime, timezone
from types import SimpleNamespace

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

from app import llm  # noqa: E402
from app.crewly import agent  # noqa: E402
from app.crewly.app_tools import app_system, app_tools, busy_years  # noqa: E402

GPC = {"id": "u1", "company": "gpc", "username": "georgia", "token": "tok-gpc"}
DESC = {"id": "u2", "company": "desc", "username": "dominion", "token": "tok-desc"}


@pytest.fixture
def conn():
    with connect() as c:
        yield c
        c.rollback()


def call(ctx, conn, name, **args):
    return app_tools(ctx)[name][0](conn, **args)


def test_every_tool_is_declared_with_a_description():
    for name, (fn, desc, props, required) in app_tools(GPC).items():
        assert callable(fn) and desc and set(required) <= set(props), name


def test_my_overlaps_only_ours_and_plots_them(conn):
    out, ui = call(GPC, conn, "my_overlaps", limit=25)
    assert out["count"] > 0
    assert all("gpc" in o["windows"] for o in out["overlaps"])
    assert ui == [{"type": "show_overlaps", "ids": [o["id"] for o in out["overlaps"]]}]


def test_date_range_keeps_both_projects_building_inside(conn):
    out, _ = call(DESC, conn, "my_overlaps", start_date="2024-01-01", end_date="2024-12-31", limit=25)
    assert out["count"] > 0
    ids = [o["id"] for o in out["overlaps"]]
    rows = conn.execute("""SELECT lower(ja.work_window) AS a0, upper(ja.work_window) AS a1, lower(jb.work_window) AS b0, upper(jb.work_window) AS b1
                           FROM opportunity op JOIN job ja ON ja.id = op.job_a JOIN job jb ON jb.id = op.job_b WHERE op.id = ANY(%s)""", (ids,)).fetchall()
    lo, hi = datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2024, 12, 31, tzinfo=timezone.utc)
    assert all(r["a0"] < hi and r["a1"] > lo and r["b0"] < hi and r["b1"] > lo for r in rows)


def test_empty_range_points_to_busy_years_and_leaves_the_map(conn):
    out, ui = call(GPC, conn, "my_overlaps", start_date="2045-01-01", end_date="2045-12-31")
    assert out["count"] == 0 and ui == []
    assert out["when_overlaps_happen"] == busy_years(conn, "gpc") and out["when_overlaps_happen"]


def test_bad_date_is_a_clear_error(conn):
    with pytest.raises(ValueError, match="dates must look like"):
        call(GPC, conn, "my_overlaps", start_date="next year")


def test_tier_and_region_filters(conn):
    out, _ = call(GPC, conn, "my_overlaps", tier="crew", limit=25)
    assert out["count"] and all(o["tier"] == "crew" for o in out["overlaps"])
    out, _ = call(GPC, conn, "my_overlaps", region="savannah", limit=25)
    assert out["region_known"] is True
    out, _ = call(GPC, conn, "my_overlaps", region="atlantis")
    assert out["region_known"] is False


def test_open_overlap_opens_the_panel(conn):
    oid = conn.execute("SELECT id FROM opportunity WHERE horizon = 'long' LIMIT 1").fetchone()["id"]
    out, ui = call(GPC, conn, "open_overlap", opportunity_id=oid)
    assert "error" not in out and ui == [{"type": "open_overlap", "id": oid}]
    out, ui = call(GPC, conn, "open_overlap", opportunity_id=-1)
    assert "error" in out and ui == []


def test_collab_requests_reads_with_the_users_login(conn, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://supabase.test")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "pk")
    seen = {}
    row = {"id": 7, "opportunity_id": 18, "from_company": "gpc", "to_company": "desc", "summary": {"title": "A × B"}, "note": "hi",
           "status": "approved", "feedback": "works for us", "created_at": "2026-09-26T10:00:00+00:00", "responded_at": "2026-09-26T11:00:00+00:00"}

    def fake_get(url, params, headers, timeout):
        seen.update(url=url, params=params, headers=headers)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: [row])

    monkeypatch.setattr("app.crewly.app_tools.httpx.get", fake_get)
    out, ui = call(GPC, conn, "collab_requests", direction="sent", limit=1)
    assert seen["url"].endswith("/rest/v1/collab_request")
    assert seen["headers"]["Authorization"] == "Bearer tok-gpc"  # row security decides what we see
    assert seen["params"]["from_company"] == "eq.gpc" and seen["params"]["limit"] == "1"
    r = out["requests"][0]
    assert out["we_are"] == "Georgia Power" and r["direction"] == "sent by us" and r["reply_feedback"] == "works for us"
    assert ui == [{"type": "show_overlaps", "ids": [18]}]

    out, _ = call(DESC, conn, "collab_requests", direction="received", status="pending")
    assert seen["params"]["to_company"] == "eq.desc" and seen["params"]["status"] == "eq.pending"
    assert out["requests"][0]["direction"] == "sent to us"


def test_system_prompt_knows_who_is_asking():
    s = app_system(DESC)
    assert "Dominion Energy SC (desc)" in s and "Georgia Power" not in s and datetime.now().strftime("%Y") in s  # partners come per overlap
    assert "neighboring utility" in s


def _fake_gemini(replies):
    """Stand-in for llm.gemini: returns scripted responses, one per model call."""
    it = iter(replies)

    def fake(_call):
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return r
    return fake


def _resp(text=None, calls=None):
    calls = [SimpleNamespace(name=n, args=a) for n, a in (calls or [])]
    return SimpleNamespace(text=text, function_calls=calls, candidates=[SimpleNamespace(content=SimpleNamespace(role="model", parts=[]))])


def test_agent_loop_runs_tools_and_returns_ui_actions(conn, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setattr(agent, "types", SimpleNamespace(**{k: getattr(agent.types, k) for k in dir(agent.types) if not k.startswith("_")}))
    monkeypatch.setattr(agent.types, "Content", lambda role, parts: SimpleNamespace(role=role, parts=parts))
    monkeypatch.setattr(agent, "gemini", _fake_gemini([
        _resp(calls=[("my_overlaps", {"start_date": "2024-01-01", "end_date": "2024-12-31"})]),
        _resp(calls=[("my_overlaps", {"start_date": "2045-01-01", "end_date": "2045-12-31"})]),  # an empty retry adds no map action
        _resp(text="Here are the overlaps building in 2024."),
    ]))
    out = agent.run(conn, [{"role": "user", "text": "what overlaps in 2024?"}], app_system(GPC), app_tools(GPC))
    assert out["reply"].startswith("Here are")
    assert [c["name"] for c in out["tool_calls"]] == ["my_overlaps", "my_overlaps"]
    shows = [a for a in out["ui_actions"] if a["type"] == "show_overlaps"]
    assert len(shows) == 1 and shows[0]["ids"]


def test_quota_out_is_a_friendly_reply(conn, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setattr(agent, "gemini", _fake_gemini([RuntimeError("Gemini is busy right now: 429 RESOURCE_EXHAUSTED quota")]))
    out = agent.run(conn, [{"role": "user", "text": "hi"}], app_system(GPC), app_tools(GPC))
    assert out["offline"] and "quota" in out["reply"] and "429" not in out["reply"]


def test_every_model_spent_raises_quota_error(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    today = time.strftime("%Y-%m-%d", time.gmtime())
    monkeypatch.setattr(llm, "SPENT", {m: today for m in llm.FALLBACKS})
    with pytest.raises(RuntimeError, match="RESOURCE_EXHAUSTED"):
        llm.gemini(lambda client, model: pytest.fail("no model should be tried"))


def test_a_third_utility_shows_up_as_a_partner(conn):
    """Any number of companies: a new utility's overlap with us names it as the partner and can be filtered by name."""
    from app import companies as co
    conn.execute("INSERT INTO org (id, name, kind, state, short, login) VALUES ('zzthird', 'Third Test Power', 'utility', 'NC', 'Third', 'zzthird')")
    job = conn.execute("SELECT id FROM job WHERE org_id = 'desc' LIMIT 1").fetchone()["id"]
    conn.execute("""INSERT INTO job (id, org_id, name, horizon, job_type, geom, geom_quality, work_window, window_basis, in_service, confidence, resources)
                    SELECT 'zzthird-1', 'zzthird', 'Third Line Rebuild', horizon, job_type, geom, geom_quality, work_window, window_basis,
                           in_service, confidence, resources FROM job WHERE id = %s""", (job,))
    oid = conn.execute("""INSERT INTO opportunity (job_a, job_b, horizon, distance_m, center_distance_m, overlap_m, tier, time_overlap, risk,
                                                   vulnerability, score, flags, savings_low, savings_high, status, link)
                          SELECT %s, 'zzthird-1', 'long', 100, 100, 0, 'site', 1, 0.5, 0.5, 9, '{}', 1000, 2000, 'not_contacted', geom
                          FROM job WHERE id = %s RETURNING id""", (job, job)).fetchone()["id"]
    co.companies(conn, fresh=True)
    try:
        out, ui = call(DESC, conn, "my_overlaps", partner_company="Third Test Power", limit=25)
        assert [o["id"] for o in out["overlaps"]] == [oid] and out["overlaps"][0]["partner"] == "Third Test Power"
        assert call(DESC, conn, "my_overlaps", partner_company="nobody at all")[0]["error"].startswith("no utility")
    finally:
        co._cache["at"] = 0  # the next caller reloads without the test org
