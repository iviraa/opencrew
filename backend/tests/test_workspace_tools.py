"""Workspace tools, offline: argument handling, the brief diff, due reminders, bulk filters and the ownership guard."""
from datetime import datetime, timedelta, timezone

import pytest

from app.crewly import proactive, workspace_tools as w

CTX = {"company": "gpc", "token": "t"}


class FakeRest:
    """Stands in for Supabase REST: remembers writes per table and answers reads from what was written."""

    def __init__(self, seed=None):
        self.tables = {k: list(v) for k, v in (seed or {}).items()}
        self.calls = []

    def __call__(self, ctx, method, table, **kw):
        self.calls.append((method, table, kw))
        rows = self.tables.setdefault(table, [])
        if method == "POST":
            row = {"id": len(rows) + 1, "created_at": "2026-09-27T10:00:00+00:00", **kw["json"]}
            rows.append(row)
            return [row]
        if method == "PATCH":
            want = int(kw["params"]["id"].split(".")[1])
            hit = [r for r in rows if r["id"] == want]
            for r in hit:
                r.update(kw["json"])
            return hit
        if kw.get("params", {}).get("done_at") == "is.null":
            return [r for r in rows if not r.get("done_at")]
        return list(rows)


@pytest.fixture
def fake(monkeypatch):
    f = FakeRest()
    monkeypatch.setattr(w, "rest", f)
    return f


def test_add_note_rejects_bad_targets(fake):
    with pytest.raises(ValueError):
        w.add_note(CTX, None, "planet", "1", "hi")
    with pytest.raises(ValueError):
        w.add_note(CTX, None, "overlap", "", "hi")
    assert w.add_note(CTX, None, "overlap", "#18", "   ")[0] == {"error": "nothing to note"}


def test_add_note_stores_and_logs_overlap_notes(fake):
    out, actions = w.add_note(CTX, None, "overlap", "#18", "Duke  prefers  spring")
    assert out["count"] == 1 and out["notes"][0]["text"] == "Duke prefers spring" and out["target"]["label"] == "overlap #18"
    assert [c[1] for c in fake.calls if c[0] == "POST"] == ["note", "overlap_event"]
    assert actions[0]["type"] == "note"


def test_reminder_due_parsing():
    assert w._due("2027-03-01", None).isoformat() == "2027-03-01T09:00:00+00:00"
    assert w._due("2027-03-01T14:30", None).hour == 14
    soon = w._due(None, 7)
    assert timedelta(days=6, hours=23) < soon - datetime.now(timezone.utc) <= timedelta(days=7)
    with pytest.raises(ValueError):
        w._due("next tuesday", None)
    with pytest.raises(ValueError):
        w._due(None, -1)


def test_set_reminder_and_done(fake):
    out, _ = w.set_reminder(CTX, None, "follow up with Duke", in_days=3, target_kind="overlap", target_id="#18")
    assert out["saved"] and out["reminder"]["target_id"] == "18" and out["count"] == 1
    done, _ = w.done_reminder(CTX, None, 1)
    assert done["done"] == 1 and done["count"] == 0  # done ones drop out of the open list


def test_due_reminders_become_bell_actions():
    rows = [{"id": 5, "text": "Call Duke", "due_at": "2026-09-01T09:00:00+00:00", "target_kind": "overlap", "target_id": "18"},
            {"id": 6, "text": "Check plan", "due_at": "2026-09-01T09:00:00+00:00", "target_kind": "plan", "target_id": None},
            {"id": 7, "text": "Ping TVA", "due_at": "2026-09-01T09:00:00+00:00", "target_kind": None, "target_id": None}]
    out = w.due_reminders("gpc", lambda table, params: rows)
    assert [o["dedup_key"] for o in out] == ["reminder:5", "reminder:6", "reminder:7"]
    assert out[0]["action"] == {"type": "open_overlap", "id": 18}
    assert out[1]["action"] == {"type": "plan", "horizon": "quarter"}
    assert out[2]["action"]["type"] == "chat" and "Ping TVA" in out[2]["action"]["prompt"]


def test_proactive_marks_reminders_notified(monkeypatch):
    seen = []

    def fake_rest(path, method="GET", **kw):
        seen.append((method, path, kw.get("params")))
        if method == "GET":
            return [{"id": 9, "text": "Call Duke", "due_at": "2026-09-01T09:00:00+00:00", "target_kind": None, "target_id": None}]
        return None

    monkeypatch.setattr(proactive, "_rest", fake_rest)
    out = proactive.due_reminders("gpc")
    assert out[0]["dedup_key"] == "reminder:9" and "id" not in out[0]
    assert any(m == "PATCH" and p == "reminder" and params["id"] == "eq.9" for m, p, params in seen)


def test_brief_diff():
    assert w.brief_diff([1, 2, 3], [2, 3, 4]) == {"added": [1], "dropped": [4]}
    assert w.brief_diff([], []) == {"added": [], "dropped": []}


def test_finding_matches_filters():
    f = {"id": 3, "kind": "compose", "params": {"changes": [{"kind": "shift_window", "params": {"opportunity_id": 18, "months": 3}}]}}
    assert w.finding_matches(f, {"opportunity_id": "#18"})
    assert not w.finding_matches(f, {"opportunity_id": "1"})  # 1 must not match 18
    assert w.finding_matches(f, {"kind": "compose", "ids": [3]})
    assert not w.finding_matches(f, {"ids": [4]})


def test_plan_bulk_filter():
    items = [{"id": "18", "partner": "desc", "verdict": "strong"}, {"id": "20", "partner": "duke", "verdict": "possible"}]
    assert [i["id"] for i in items if w._matches(i, {"partner": "Dominion"}, "gpc")] == ["18"]
    assert [i["id"] for i in items if w._matches(i, {"verdict": "possible"}, "gpc")] == ["20"]
    assert [i["id"] for i in items if w._matches(i, {"ids": ["#20"]}, "gpc")] == ["20"]


def test_set_status_guards_ownership_and_values(fake, monkeypatch):
    monkeypatch.setattr(w, "_mine", lambda conn, ctx, oid: None)
    assert "not one of our overlaps" in w.set_status(CTX, None, 999999, "sent")[0]["error"]
    assert "status must be" in w.set_status(CTX, None, 18, "shipped")[0]["error"]


def test_tools_register_with_schemas():
    tools = w.workspace_tools(CTX)
    assert {"add_note", "set_reminder", "set_status", "pipeline", "company_profile", "weekly_brief", "overlap_history", "save_view", "open_view",
            "plan_bulk", "findings_bulk"} <= set(tools)
    for fn, desc, props, req in tools.values():
        assert callable(fn) and desc and isinstance(props, dict) and set(req) <= set(props)
