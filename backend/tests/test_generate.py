"""Charts, tables and reports crewly hands over, plus the top-N fix. Pure helpers offline; datasets against the database when it is up."""
from datetime import date

import psycopg
import pytest

from app.crewly import charts, generate_tools, reports
from app.db import DATABASE_URL, connect

try:
    with psycopg.connect(DATABASE_URL, connect_timeout=3) as c:
        JOBS = c.execute("SELECT count(*) FROM job").fetchone()[0]
except Exception:
    JOBS = 0

GPC = {"id": "u1", "company": "gpc", "username": "georgia", "token": "tok"}
needs_db = pytest.mark.skipif(not JOBS, reason="database not reachable or empty")


@pytest.fixture
def conn():
    with connect() as c:
        yield c
        c.rollback()


# ---------- offline ----------

def test_years_default_to_today_and_order():
    y = date.today().year
    assert charts.years_of({}) == (y, y + 2)
    assert charts.years_of({"years": [2030, 2027]}) == (2027, 2030)
    assert charts.years_of({"years": ["x"]}) == (y, y + 2)


def test_month_labels_cover_every_month():
    labels = charts.month_labels(2027, 2028)
    assert len(labels) == 24 and labels[0] == "Jan 2027" and labels[-1] == "Dec 2028"


def test_csv_has_header_and_rows():
    out = charts.to_csv([{"a": 1, "b": "x,y"}, {"a": 2, "b": "z"}])
    assert out.splitlines()[0] == "a,b" and '"x,y"' in out and out.count("\n") >= 2


def test_unknown_dataset_is_refused():
    with pytest.raises(ValueError):
        charts.make(None, "gpc", "nope", {})


def test_report_page_escapes_and_prints():
    html = reports.page("T <x>", "sub", reports.table(["c"], [["<b>"]]) + reports.chip("strong"))
    assert "&lt;x&gt;" in html and "&lt;b&gt;" in html and "window.print()" in html and 'class="chip strong"' in html


def test_report_kinds_and_default_sections():
    assert set(reports.KINDS) == {"feasibility", "cost_analysis", "hazard_exposure", "plan", "pack", "finding"}
    with pytest.raises(ValueError):
        reports.build(None, "gpc", "nope")


class FakeConn:
    """Answers the ownership check show_overlaps makes with a fixed set of our overlap ids."""
    def __init__(self, ours):
        self.ours = ours

    def execute(self, sql, params=None):
        ids = params[0] if params else []
        rows = [{"id": i} for i in ids if i in self.ours]
        return type("R", (), {"fetchall": lambda s: rows, "fetchone": lambda s: rows[0] if rows else None})()


def test_show_overlaps_keeps_only_ours_in_order():
    out, ui = generate_tools.show_overlaps(GPC, FakeConn({18, 15}), ["#15", 18, 99], title="Top 2")
    assert out == {"shown": [15, 18], "not_ours": [99]}
    assert ui == [{"type": "show_overlaps", "ids": [15, 18], "title": "Top 2"}]


def test_show_overlaps_can_show_nothing():
    out, ui = generate_tools.show_overlaps(GPC, FakeConn(set()), [])
    assert out["shown"] == [] and ui[0]["ids"] == []


def test_tools_are_declared():
    tools = generate_tools.generate_tools(GPC)
    assert set(tools) == {"show_overlaps", "make_chart", "get_data", "make_report"}
    for fn, desc, props, required in tools.values():
        assert callable(fn) and desc and set(required) <= set(props)
    assert "limit=N" in generate_tools.PROMPT


# ---------- against the database ----------

@needs_db
def test_top_n_limit_is_honored(conn):
    from app.crewly.app_tools import my_overlaps
    out, ui = my_overlaps(GPC, conn, limit=2)
    assert out["count"] == 2 and len(out["overlaps"]) == 2 and len(ui[0]["ids"]) == 2


@needs_db
@pytest.mark.parametrize("dataset,options", [
    ("overlaps_by_month", {"years": [2026, 2027]}), ("hazard_days_by_month", {"id": "#18"}), ("savings_by_partner", {"top": 3}),
    ("projects_by_year", {"years": [2026, 2030]}), ("cost_by_category", {"id": "18"}), ("news_by_impact", {"days": 90}),
])
def test_chart_datasets_build(conn, dataset, options):
    chart, rows = charts.make(conn, "gpc", dataset, options)
    assert chart["dataset"] == dataset and chart["kind"] in charts.KINDS and chart["x"] and chart["series"]
    assert all(len(s["values"]) == len(chart["x"]) for s in chart["series"])
    assert len(rows) == len(chart["x"])


@needs_db
def test_hazard_chart_stacks_and_caps_top(conn):
    chart, _ = charts.make(conn, "gpc", "hazard_days_by_month", {"id": "18"})
    assert chart["kind"] == "stacked" and chart["x"][0] == "Jan"
    chart, rows = charts.make(conn, "gpc", "savings_by_partner", {"top": 1})
    assert len(chart["x"]) == 1 and len(rows) == 1


@needs_db
def test_tables_filter_and_cap(conn):
    t = charts.table(conn, "gpc", "overlaps", {"years": [2027, 2027], "top": 5}, GPC)
    assert t["count"] <= 5 and t["columns"][0] == "overlap"
    t = charts.table(conn, "gpc", "hazard_exposure", {"id": "#18", "period": "month", "month": 8}, GPC)
    assert t["count"] > 0 and "affected_days_high" in t["columns"]
    with pytest.raises(ValueError):
        charts.table(conn, "gpc", "hazard_exposure", {}, GPC)


@needs_db
def test_reports_carry_the_numbers(conn):
    r = reports.build(conn, "gpc", "cost_analysis", "#18", ["savings"])
    assert r["sections"] == ["savings"] and "Coordinating saves" in r["html"] and "$" in r["html"]
    got = reports.get(conn, r["id"], "gpc")
    assert got and got["title"] == r["title"]
    assert reports.get(conn, r["id"], "desc") is None  # another company cannot open it
    with pytest.raises(ValueError):
        reports.build(conn, "gpc", "feasibility")  # needs an id
