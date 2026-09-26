import httpx
import pytest
from fastapi.testclient import TestClient

from app import app_api
from app.auth import current_user
from app.crewly import memory_tools as m
from app.crewly.app_tools import app_system, app_tools
from app.main import app

GPC = {"id": "u1", "company": "gpc", "other": "desc", "username": "georgia", "token": "tok-gpc"}


class FakeRest:
    """Records calls to Supabase and answers like PostgREST with return=representation."""

    def __init__(self, rows=None, fail=False):
        self.rows, self.fail, self.calls = rows if rows is not None else [], fail, []

    def __call__(self, method, url, params=None, json=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "params": params, "json": json, "headers": headers})
        if self.fail:
            raise httpx.ConnectError("down")
        if method == "POST":
            row = {"id": len(self.rows) + 1, **json}
            self.rows.append(row)
            body = [row]
        elif method == "DELETE":
            want = int(params["id"].split(".")[1])
            body = [r for r in self.rows if r["id"] == want]
            self.rows = [r for r in self.rows if r["id"] != want]
        else:
            body = self.rows
        return httpx.Response(200, json=body, request=httpx.Request(method, url))


@pytest.fixture
def rest(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://supabase.test")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "pk")
    fake = FakeRest()
    monkeypatch.setattr(m.httpx, "request", fake)
    return fake


def call(name, **args):
    return app_tools(GPC)[name][0](None, **args)


def test_memory_tools_are_offered_in_the_app():
    assert {"remember", "forget", "list_memory"} <= set(app_tools(GPC))


def test_remember_saves_with_the_users_own_login(rest):
    out, ui = call("remember", text="  we never share crews\n in hurricane season ")
    assert out["saved"] and out["text"] == "we never share crews in hurricane season" and ui == [{"type": "memory"}]
    sent = rest.calls[-1]
    assert sent["method"] == "POST" and sent["url"].endswith("/rest/v1/crewly_memory")
    assert sent["headers"]["Authorization"] == "Bearer tok-gpc" and sent["headers"]["apikey"] == "pk"
    assert "company_id" not in sent["json"]  # the database fills it from the login


def test_remember_needs_text(rest):
    assert "error" in call("remember", text="   ")[0] and not rest.calls


def test_forget_and_list(rest):
    call("remember", text="always ask about staging yards first")
    assert call("list_memory")[0]["notes"] == [{"id": 1, "text": "always ask about staging yards first"}]
    assert call("forget", memory_id=1)[0] == {"forgotten": True, "id": 1}
    assert "error" in call("forget", memory_id=1)[0]


def test_a_broken_store_never_breaks_the_chat(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://supabase.test")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "pk")
    monkeypatch.setattr(m.httpx, "request", FakeRest(fail=True))
    assert m.load_memories(GPC) == []


def test_prompt_quotes_notes_as_data_and_caps_them():
    notes = [{"id": i, "text": f"note {i}"} for i in range(m.MAX_NOTES + 5)]
    text = m.memory_prompt(notes)
    assert '"note 0"' in text and f'"note {m.MAX_NOTES}"' not in text
    assert "not as instructions" in text and "call remember" in text


def test_system_prompt_carries_the_remember_rule_and_saved_notes():
    assert "call remember" in app_system(GPC) and "Notes our company" not in app_system(GPC)
    with_notes = app_system({**GPC, "memories": [{"id": 3, "text": "we never share crews in hurricane season"}]})
    assert '(#3) "we never share crews in hurricane season"' in with_notes


def test_chat_reads_memories_once_per_message(monkeypatch):
    seen = {}
    monkeypatch.setattr(app_api, "load_memories", lambda user: [{"id": 9, "text": "no night work"}])
    monkeypatch.setattr(app_api.agent, "run", lambda conn, msgs, system, tools: seen.update(system=system) or {"reply": "ok", "ui_actions": []})
    app.dependency_overrides[current_user] = lambda: GPC
    app.dependency_overrides[app_api.get_conn] = lambda: None
    try:
        r = TestClient(app).post("/api/app/chat", json={"messages": [{"role": "user", "text": "hi"}]})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200 and '"no night work"' in seen["system"]
