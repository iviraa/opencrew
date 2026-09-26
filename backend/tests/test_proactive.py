from datetime import datetime, timedelta, timezone

import httpx
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

from app.crewly import proactive as p  # noqa: E402

NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
ACTIONS = {"open_request", "open_overlap", "weather", "chat"}


@pytest.fixture
def conn():
    with connect() as c:
        yield c
        c.rollback()


def opp(conn, where):
    return conn.execute(p.mine_sql("gpc") + f" AND {where} ORDER BY op.score DESC LIMIT 1").fetchone()


def req(i, opp_id, frm="desc", to="gpc", status="pending", age=timedelta(hours=1)):
    return {"id": i, "opportunity_id": opp_id, "from_company": frm, "to_company": to, "status": status,
            "created_at": (NOW - age).isoformat()}


def test_take_on_a_close_overlap_leans_approve_with_numbers_from_the_db(conn):
    o = opp(conn, "op.savings_high > 0 AND op.drive_min <= 45 AND op.time_overlap > 0")
    [s] = p.request_takes(conn, "gpc", [req(7, o["id"])])
    assert s["dedup_key"] == "req-take:7" and s["action"] == {"type": "open_request", "id": 7}
    assert f"save {p._usd(o['savings_low'])} to {p._usd(o['savings_high'])}" in s["body"]
    assert f"{round(o['drive_min'])} min drive" in s["body"] and "leans approve" in s["body"]
    assert len(s["title"]) <= 80


def test_take_explains_when_there_is_nothing_to_save_yet(conn):
    o = opp(conn, "op.savings_high = 0")
    [s] = p.request_takes(conn, "gpc", [req(8, o["id"])])
    assert "no shared savings yet" in s["body"] and "leans approve" not in s["body"]


def test_takes_skip_answered_and_outgoing_requests(conn):
    o = opp(conn, "op.savings_high > 0")
    assert p.request_takes(conn, "gpc", [req(1, o["id"], status="approved"), req(2, o["id"], frm="gpc", to="desc")]) == []


def test_follow_up_only_for_our_old_pending_goal_steps():
    reqs = [req(1, 18, "gpc", "desc", age=timedelta(days=3)), req(2, 15, "gpc", "desc", age=timedelta(hours=5)),
            req(3, 38, "gpc", "desc", "approved", timedelta(days=5)), req(4, 37, "desc", "gpc", age=timedelta(days=5))]
    tasks = [{"goal": "Top 3 overlaps", "steps": [{"request_id": i} for i in (1, 2, 3, 4, 99)]}]
    [s] = p.follow_ups("gpc", reqs, tasks, now=NOW)
    assert s["dedup_key"] == "followup:1" and s["action"] == {"type": "open_request", "id": 1}
    assert "#18" in s["title"] and "Dominion" in s["title"]


def test_cold_overlaps_skip_ones_already_asked_and_key_is_order_free(conn):
    [s] = p.cold_overlaps(conn, "gpc", [])
    top = conn.execute(p.mine_sql("gpc") + " AND op.savings_high > 0 ORDER BY op.score DESC, op.distance_m").fetchall()
    assert s["action"] == {"type": "chat", "prompt": "Line up collaboration on our top 3 overlaps"}
    assert f"#{top[0]['id']}" in s["body"] and s["title"].startswith(f"{len(top)} strong")
    [after] = p.cold_overlaps(conn, "gpc", [req(1, top[0]["id"])])
    assert f"#{top[0]['id']}" not in after["body"] and after["dedup_key"] != s["dedup_key"]


def test_weather_groups_active_sites_per_hazard(conn):
    out = p.weather_risks(conn, "gpc", scenario="helene")
    assert out and len({s["dedup_key"] for s in out}) == len(out)
    for s in out:
        assert s["dedup_key"].startswith("wx:") and len(s["title"]) <= 80 and "active site" in s["title"]
        assert s["action"]["type"] in ("open_overlap", "weather")


def test_every_suggestion_is_well_formed(conn):
    o = opp(conn, "op.savings_high > 0")
    reqs = [req(5, o["id"]), req(6, o["id"], "gpc", "desc", age=timedelta(days=4))]
    for s in p.suggestions(conn, "gpc", reqs, [{"goal": "g", "steps": [{"request_id": 6}]}], now=NOW):
        assert set(s) == {"dedup_key", "title", "body", "action"} and s["action"]["type"] in ACTIONS
        assert 0 < len(s["title"]) <= 80 and "—" not in s["title"] + s["body"]


class FakeStore:
    """Stands in for Supabase REST: remembers inserted suggestions and answers 409 on a duplicate key."""

    def __init__(self, keys=()):
        self.rows = [{"dedup_key": k} for k in keys]

    def __call__(self, path, method="GET", **kw):
        if method == "PATCH":  # retiring stale suggestions
            self.retired = kw["params"]
            return None
        if method == "POST":
            if any(r["dedup_key"] == kw["json"]["dedup_key"] for r in self.rows):
                raise httpx.HTTPStatusError("dup", request=httpx.Request("POST", "x"), response=httpx.Response(409))
            self.rows.append(kw["json"])
            return [kw["json"]]
        return {"collab_request": [], "agent_task": [], "notification": self.rows}[path]


def test_scan_adds_each_suggestion_once(conn, monkeypatch):
    store = FakeStore()
    monkeypatch.setattr(p, "_rest", store)
    first = p.scan(conn, "gpc")
    assert first["created"] == first["found"] > 0
    assert all(r["kind"] == "suggestion" and r["company_id"] == "gpc" for r in store.rows)
    assert p.scan(conn, "gpc")["created"] == 0


def test_scan_survives_a_race_with_another_scan(conn, monkeypatch):
    found = [s["dedup_key"] for s in p.suggestions(conn, "gpc", [], [])]
    store = FakeStore()
    real_get = store.__call__

    def racing(path, method="GET", **kw):  # another scan already inserted everything, but after we looked
        return [] if path == "notification" and method == "GET" else real_get(path, method, **kw)

    store.rows = [{"dedup_key": k} for k in found]
    monkeypatch.setattr(p, "_rest", racing)
    assert p.scan(conn, "gpc")["created"] == 0


def test_scan_retires_suggestions_that_no_longer_apply(conn, monkeypatch):
    store = FakeStore()
    monkeypatch.setattr(p, "_rest", store)
    found = p.scan(conn, "gpc")["found"]
    assert store.retired["company_id"] == "eq.gpc" and store.retired["dismissed_at"] == "is.null"
    assert store.retired["dedup_key"].startswith("not.in.(") and store.retired["dedup_key"].count('"') == 2 * found  # current ones stay open
