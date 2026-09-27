"""Editing a saved plan: moves are re-priced, totals are saved, edits are logged and undoable, bad input is refused."""
import psycopg
import pytest

from app.db import DATABASE_URL, connect
from app.planner import api, edits, store, tools

try:
    with psycopg.connect(DATABASE_URL, connect_timeout=3) as c:
        JOBS = c.execute("SELECT count(*) FROM job").fetchone()[0]
except Exception:
    JOBS = 0
needs_db = pytest.mark.skipif(not JOBS, reason="database not reachable or empty")
CTX = {"company": "desc"}


@pytest.fixture
def conn():
    with connect() as c:
        yield c
        c.rollback()


def test_months_parse():
    assert str(edits._d("2025-04")) == "2025-04-01"
    with pytest.raises(ValueError):
        edits._d("April")


@needs_db
def test_move_reprices_and_logs(conn):
    plan = api.rebuild(conn, "desc", "year")
    it = dict(plan["items"][0])  # apply edits the plan in place
    row, done = edits.apply(conn, plan, [{"action": "move", "item_id": it["id"], "shift_months": -1}])
    moved = next(i for i in row["items"] if i["id"] == it["id"])
    assert moved["target_edited"] and moved["target_start"] != it["target_start"]
    assert row["totals"]["edits"][-1]["effect"]["weather_cost"] is not None and row["totals"]["built"]["weather_cost"]
    assert store.get(conn, row["id"], "desc")["totals"].get("edits")  # saved, not only returned


@needs_db
def test_skip_by_partner_changes_savings_and_undo_restores(conn):
    plan = api.rebuild(conn, "desc", "year")
    partner = plan["items"][0]["partner_name"]
    out, _ = tools.edit_plan(CTX, conn, [{"action": "skip", "partner": partner}], "year")
    assert out["now"]["savings_usd"] != out["before_your_edits"]["savings_usd"]
    out, _ = tools.edit_plan(CTX, conn, [{"action": "undo"}], "year")
    assert out["now"]["savings_usd"] == out["before_your_edits"]["savings_usd"]


@needs_db
def test_bad_edits_are_refused_and_change_nothing(conn):
    plan = api.rebuild(conn, "desc", "year")
    for change in ({"action": "move", "item_id": "999999", "shift_months": 1}, {"action": "move", "item_id": plan["items"][0]["id"], "start": "2031-01", "end": "2031-03"},
                   {"action": "explode", "item_id": plan["items"][0]["id"]}, {"action": "skip", "partner": "Atlantis Power"}, {"action": "undo"}):
        out, ui = tools.edit_plan(CTX, conn, [change], "year")
        assert "error" in out and not ui, change
    assert not store.get(conn, plan["id"], "desc")["totals"].get("edits")
