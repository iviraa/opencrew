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

from app.config import MILE_M  # noqa: E402
from app.crewly import act_tools as act, agent  # noqa: E402
from app.crewly.app_tools import app_system, app_tools  # noqa: E402

GPC = {"id": "u1", "company": "gpc", "username": "georgia", "token": "tok-gpc"}
DESC = {"id": "u2", "company": "desc", "username": "dominion", "token": "tok-desc"}


@pytest.fixture
def conn():
    with connect() as c:
        yield c
        c.rollback()


class FakeRest:
    """Stands in for Supabase REST: canned rows per table, and a log of every call."""
    def __init__(self, tables=None):
        self.tables, self.calls = tables or {}, []

    def __call__(self, ctx, method, table, **kw):
        self.calls.append((ctx["token"], method, table, kw))
        if method == "POST":
            return [{"id": 99, **kw["json"]}]
        rows = self.tables.get(table, [])
        return rows(kw.get("params", {})) if callable(rows) else rows


def call(ctx, conn, name, **args):
    return app_tools(ctx)[name][0](conn, **args)


def best(conn, company="gpc"):
    return conn.execute(f"""SELECT op.id FROM opportunity op JOIN job ja ON ja.id = op.job_a JOIN job jb ON jb.id = op.job_b
                            WHERE op.horizon = 'long' AND '{company}' IN (ja.org_id, jb.org_id) AND op.savings_high > 0
                            ORDER BY op.score DESC, op.distance_m""").fetchall()


def test_act_tools_are_declared():
    tools = app_tools(GPC)
    for name in ("propose_request", "propose_answer", "start_goal", "goal_status"):
        fn, desc, props, required = tools[name]
        assert callable(fn) and desc and set(required) <= set(props), name


def test_propose_request_only_shows_a_confirm(conn, monkeypatch):
    fake = FakeRest({"collab_request": []})
    monkeypatch.setattr(act, "rest", fake)
    oid = best(conn)[0]["id"]
    out, ui = call(GPC, conn, "propose_request", opportunity_id=oid)
    assert out["ready_to_confirm"] and out["sent"] is False
    assert ui == [{"type": "confirm", "action": "send_request", "opportunity_id": oid, "to_company": "desc", "note": out["note"],
                   "label": f"Send Dominion SC a request for #{oid}", "title": f"{out['ours']} × {out['theirs']}"}]
    assert out["ours"] in out["note"] and out["theirs"] in out["note"]  # drafted when the user gave no note
    assert all(m == "GET" for _, m, _, _ in fake.calls) and fake.calls[0][0] == "tok-gpc"  # reads only, as the user
    out, ui = call(GPC, conn, "propose_request", opportunity_id=oid, note="  Share a yard?  ")
    assert out["note"] == "Share a yard?" and ui[0]["note"] == "Share a yard?"


def test_propose_request_refuses_handled_or_foreign_overlaps(conn, monkeypatch):
    oid = best(conn)[0]["id"]
    monkeypatch.setattr(act, "rest", FakeRest({"collab_request": [{"id": 5, "opportunity_id": oid, "status": "pending", "from_company": "desc"}]}))
    out, ui = call(GPC, conn, "propose_request", opportunity_id=oid)
    assert out["blocked"] and "Dominion Energy SC already have a pending request" in out["reason"] and ui == []
    out, ui = call(GPC, conn, "propose_request", opportunity_id=-1)
    assert "error" in out and ui == []


def test_propose_answer_needs_an_incoming_pending_request(conn, monkeypatch):
    row = {"id": 7, "opportunity_id": 18, "from_company": "desc", "to_company": "gpc", "status": "pending", "summary": {"title": "A × B"}, "note": "hi"}
    monkeypatch.setattr(act, "rest", FakeRest({"collab_request": [row]}))
    out, ui = call(GPC, conn, "propose_answer", request_id=7, decision="approved", feedback="works for us")
    assert out["ready_to_confirm"] and ui[0]["action"] == "respond" and ui[0]["decision"] == "approved"
    assert ui[0]["label"] == "Approve Dominion SC's request for #18" and ui[0]["feedback"] == "works for us"
    out, ui = call(DESC, conn, "propose_answer", request_id=7, decision="approved")
    assert "not sent to us" in out["error"] and ui == []  # the sender can't answer its own request
    out, _ = call(GPC, conn, "propose_answer", request_id=7, decision="maybe")
    assert "decision" in out["error"]
    monkeypatch.setattr(act, "rest", FakeRest({"collab_request": [{**row, "status": "approved"}]}))
    out, ui = call(GPC, conn, "propose_answer", request_id=7, decision="declined")
    assert out["blocked"] and ui == []


def test_start_goal_skips_handled_overlaps_and_saves_drafts(conn, monkeypatch):
    ranked = [r["id"] for r in best(conn)]
    fake = FakeRest({"collab_request": [{"id": 1, "opportunity_id": ranked[0], "status": "approved", "from_company": "gpc"}]})
    monkeypatch.setattr(act, "rest", fake)
    out, ui = call(GPC, conn, "start_goal", goal="Line up our top 3 [e2e-act]", count=3)
    assert out["drafted"] == 3 and out["task_id"] == 99 and out["sent"] is False
    ids = [o["id"] for o in out["overlaps"]]
    assert ids == ranked[1:4]  # best first, the approved one left out
    posted = [c for c in fake.calls if c[1] == "POST"][0]
    assert posted[0] == "tok-gpc" and posted[2] == "agent_task"
    steps = posted[3]["json"]["steps"]
    assert all(s["request_id"] is None and not s["skipped"] and s["note"] for s in steps)
    assert ui == [{"type": "goal", "id": 99}, {"type": "show_overlaps", "ids": ids}]


def test_draft_note_numbers_come_from_the_row(conn):
    oid = best(conn)[0]["id"]
    from app.crewly.app_tools import mine_sql
    o = conn.execute(mine_sql("gpc") + " AND op.id = %s", (oid,)).fetchone()
    note = act.draft_note(GPC, o)
    assert f"{o['distance_m'] / MILE_M:.1f} miles apart" in note and note.startswith("Hi from Georgia Power!")


def test_goal_status_reads_state_from_requests(conn, monkeypatch):
    task = {"id": 3, "goal": "top 4", "status": "active", "steps": [
        {"opportunity_id": 1, "title": "A × B", "note": "n", "request_id": None, "skipped": False},
        {"opportunity_id": 2, "title": "C × D", "note": "n", "request_id": 11, "skipped": False},
        {"opportunity_id": 3, "title": "E × F", "note": "n", "request_id": 12, "skipped": False},
        {"opportunity_id": 4, "title": "G × H", "note": "n", "request_id": None, "skipped": True}]}
    reqs = [{"id": 11, "status": "approved", "feedback": "yes"}, {"id": 12, "status": "pending", "feedback": None}]
    monkeypatch.setattr(act, "rest", FakeRest({"agent_task": [task], "collab_request": reqs}))
    out, ui = call(GPC, conn, "goal_status")
    assert [s["state"] for s in out["steps"]] == ["draft", "approved", "pending", "skipped"]
    assert out["counts"] == {"draft": 1, "pending": 1, "approved": 1, "declined": 0, "skipped": 1}
    assert out["steps"][1]["feedback"] == "yes" and ui == [{"type": "goal", "id": 3}]
    monkeypatch.setattr(act, "rest", FakeRest({"agent_task": []}))
    out, ui = call(GPC, conn, "goal_status")
    assert "error" in out and ui == []


def test_system_prompt_says_nothing_is_sent_without_a_tap():
    s = app_system(GPC)
    assert "propose_request" in s and "never say it was sent" in s and "start_goal" in s


def _resp(text=None, calls=None):
    calls = [SimpleNamespace(name=n, args=a) for n, a in (calls or [])]
    return SimpleNamespace(text=text, function_calls=calls, candidates=[SimpleNamespace(content=SimpleNamespace(role="model", parts=[]))])


def test_agent_loop_passes_the_confirm_through(conn, monkeypatch):
    oid = best(conn)[0]["id"]
    monkeypatch.setattr(act, "rest", FakeRest({"collab_request": []}))
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setattr(agent, "types", SimpleNamespace(**{k: getattr(agent.types, k) for k in dir(agent.types) if not k.startswith("_")}))
    monkeypatch.setattr(agent.types, "Content", lambda role, parts: SimpleNamespace(role=role, parts=parts))
    replies = iter([_resp(calls=[("propose_request", {"opportunity_id": oid})]), _resp(text="Tap Confirm to send it.")])
    monkeypatch.setattr(agent, "gemini", lambda _call: next(replies))
    out = agent.run(conn, [{"role": "user", "text": f"ask them about #{oid}"}], app_system(GPC), app_tools(GPC))
    assert out["reply"] == "Tap Confirm to send it."
    assert [a["type"] for a in out["ui_actions"]] == ["confirm"] and out["ui_actions"][0]["opportunity_id"] == oid
