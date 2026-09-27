import httpx
import pytest
from fastapi.testclient import TestClient

from app import app_api
from app.auth import current_user
from app.comms import api as comms_api, email
from app.crewly import comms_tools, reports
from app.db import connect
from app.llm import unsourced
from app.main import app

GPC = {"id": "u1", "company": "gpc", "username": "georgia", "token": "tok-gpc"}


class FakeRest:
    """Stands in for Supabase: keeps draft rows and answers like PostgREST with return=representation."""

    def __init__(self, rows=None):
        self.rows, self.calls = rows if rows is not None else [], []

    def __call__(self, ctx, method="GET", params=None, json=None, path="draft"):
        self.calls.append((method, path, params, json))
        if method == "POST":
            row = {"id": len(self.rows) + 1, "status": "draft", "sent_at": None, "created_at": "2026-09-27T00:00:00Z", **json}
            self.rows.append(row)
            return [row]
        want = int(params["id"].split(".")[1]) if params and "id" in params else None
        if method == "PATCH":
            out = []
            for r in self.rows:
                if r["id"] == want:
                    r.update(json)
                    out.append(r)
            return out
        return [r for r in self.rows if want is None or r["id"] == want]


@pytest.fixture
def conn():
    with connect() as c:
        yield c
        c.rollback()


@pytest.fixture
def rest(monkeypatch):
    store = FakeRest()
    monkeypatch.setattr(email, "_rest", store)
    return store


def test_draft_numbers_come_from_facts_and_the_opener_carries_none(conn, rest, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")  # provider on, but the model is faked
    monkeypatch.setattr(email, "generate", lambda prompt: "Our teams could save $5,000 by working together.")  # breaks the rule
    d = email.compose(conn, GPC, "Dominion Energy", "#18", "short", "brief")
    f = email.overlap_facts(conn, "gpc", 18)
    assert d["recipient"]["company_id"] == "desc" and d["subject"].startswith("Coordinating")
    assert "$5,000" not in d["body"] and "room to coordinate" in d["body"]  # fallback opener
    facts = f"{f['ours']} {f['theirs']} {f['miles']} {f['overlap_pct']} {f['drive_min']} {f['savings_low']} {f['savings_high']} 30"  # project names carry kV
    assert unsourced(d["body"].replace("crewly", ""), facts) == []  # every number in the body is a fact
    assert d["attachments"][0]["name"] == "brief-overlap-18.md" and "Coordination brief" in d["attachments"][0]["content"]
    card = email.create(GPC, d)
    assert card["id"] == 1 and card["attachments"][0]["size"] > 100 and "content" not in card["attachments"][0]


def test_draft_refuses_the_wrong_partner_and_unknown_people(conn, rest):
    with pytest.raises(ValueError, match="not"):
        email.compose(conn, GPC, "Duke Energy", "#18")  # #18 is with Dominion
    with pytest.raises(ValueError, match="who"):
        email.compose(conn, GPC, "Death Star Power", "#18")
    assert email.compose(conn, GPC, "them", "#18")["recipient"]["company_id"] == "desc"  # loose names follow the overlap's partner
    with pytest.raises(ValueError, match="which utility"):
        email.compose(conn, GPC, "them", "plan")
    assert email.recipient(conn, "someone@example.com", "gpc")["email"] == "someone@example.com"


def test_send_guard_blocks_unknown_addresses_and_missing_keys(conn, rest, monkeypatch):
    monkeypatch.delenv("COMMS_ALLOWED_DOMAINS", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    rest.rows.append({"id": 7, "status": "draft", "recipient": {"email": "x@nowhere.example", "name": "x"}, "subject": "s", "body": "b", "attachments": [], "about": {}, "sent_at": None})
    posted = []
    out = email.send(conn, GPC, 7, post=lambda *a, **k: posted.append(k))
    assert not out["sent"] and "copy the text" in out["note"] and not posted
    monkeypatch.setenv("COMMS_ALLOWED_DOMAINS", "nowhere.example")
    out = email.send(conn, GPC, 7, post=lambda *a, **k: posted.append(k))
    assert not out["sent"] and "RESEND_API_KEY" in out["note"] and not posted


def test_send_goes_out_only_after_the_guard_and_marks_the_draft(conn, rest, monkeypatch):
    monkeypatch.setenv("COMMS_ALLOWED_DOMAINS", "ok.example")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    rest.rows.append({"id": 3, "status": "draft", "recipient": {"email": "p@ok.example", "name": "p"}, "subject": "s", "body": "b",
                      "attachments": [{"name": "a.md", "content_type": "text/markdown", "content": "# hi"}], "about": {}, "sent_at": None})
    posted = []

    def post(url, headers=None, timeout=None, json=None):
        posted.append(json)
        return httpx.Response(200, json={"id": "m1"}, request=httpx.Request("POST", url))

    out = email.send(conn, GPC, 3, post=post)
    assert out["sent"] and out["draft"]["status"] == "sent" and rest.rows[0]["status"] == "sent"
    assert posted[0]["to"] == ["p@ok.example"] and posted[0]["attachments"][0]["filename"] == "a.md"
    assert email.send(conn, GPC, 3, post=post)["note"] == "already sent"


def test_update_never_marks_sent(rest):
    rest.rows.append({"id": 2, "status": "draft", "recipient": {}, "subject": "s", "body": "b", "attachments": [], "about": {}, "sent_at": None})
    row = email.update(GPC, 2, {"status": "sent", "subject": "new", "created_by": "x"})
    assert row["subject"] == "new" and row["status"] == "draft"
    assert email.update(GPC, 2, {"status": "copied"})["status"] == "copied"


def test_agenda_and_memo_reports_carry_the_pair_numbers(conn):
    f = email.overlap_facts(conn, "gpc", 18)
    a = reports.build(conn, "gpc", "agenda", "#18", None, {"when": "Tue 10am"})
    assert "Coordination call" in a["title"] and "Tue 10am" in a["html"] and f"{f['miles']} mi" in a["html"] and "Decisions to make" in a["html"]
    m = reports.build(conn, "gpc", "memo", "18", None, {"audience": "regulator"})
    assert "Cost-sharing memo" in m["title"] and "public service commission" in m["html"] and "Split to agree" in m["html"] and "Sources" in m["html"]
    assert reports.build(conn, "gpc", "memo", "18", ["purpose"], {"audience": "internal"})["sections"] == ["purpose"]
    with pytest.raises(ValueError):
        reports.build(conn, "desc", "agenda", "#6173")  # not dominion's overlap


def test_tools_return_cards(conn, rest, monkeypatch):
    tools = comms_tools.comms_tools(GPC)
    assert set(tools) == {"draft_email", "draft_agenda", "draft_memo"}
    summary, ui = tools["draft_email"][0](conn, to="dominion", about="18")
    assert ui[0]["type"] == "draft" and "nothing has been sent" in summary["next_step"] and ui[0]["draft"]["recipient"]["company_id"] == "desc"
    summary, ui = tools["draft_agenda"][0](conn, about="#18")
    assert ui[0]["type"] == "report" and ui[0]["report"]["kind"] == "agenda"


def test_routes_edit_and_send_with_the_login(rest, monkeypatch):
    rest.rows.append({"id": 5, "status": "draft", "recipient": {"email": None, "name": "Dominion"}, "subject": "s", "body": "b", "attachments": [], "about": {}, "sent_at": None})
    app.dependency_overrides[current_user] = lambda: GPC
    app.dependency_overrides[app_api.get_conn] = lambda: None
    app.dependency_overrides[comms_api.get_conn] = lambda: FakeConn()
    try:
        client = TestClient(app)
        r = client.patch("/api/app/comms/draft/5", json={"subject": "hello", "recipient": {"email": "a@b.example", "name": "Dominion"}})
        assert r.status_code == 200 and r.json()["subject"] == "hello"
        r = client.post("/api/app/comms/send", json={"id": 5})
        assert r.status_code == 200 and r.json()["sent"] is False and "copy the text" in r.json()["note"]
        assert client.patch("/api/app/comms/draft/99", json={"subject": "x"}).status_code == 404
    finally:
        app.dependency_overrides.clear()


class FakeConn:
    def execute(self, *a, **k):
        return self

    def fetchone(self):
        return None
