"""Source refresh: drift validation on synthetic workbooks, the diff, the rollback invariant, promote history and bells, loop isolation."""
import io
import re
import zipfile
from types import SimpleNamespace

import pandas as pd
import psycopg
import pytest

from app.db import DATABASE_URL, ROOT
from app.refresh import drift, promote, stage
from app.refresh.sources import SOURCES, Source, discover, fetch, newest


def book(rows, sheet="Data", header=0, path=None):
    """A small xlsx in memory (or on disk) with the given rows and sheet name; header>0 pads title rows like the planners do."""
    buf = path or io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame(rows).to_excel(w, sheet_name=sheet, index=False, startrow=header)
    if path is None:
        buf.seek(0)
    return buf


FAKE = Source("fake", "FAKE", "fake planner", "fake", "https://x.test/list.xlsx", [], None, "Data", 0,
              ["Id", "Name", "ISD", "Status"], "Id", "ISD", 7)
ROWS = [{"Id": f"f{i}", "Name": f"Line {i}", "ISD": "2027-06-01", "Status": "Planned"} for i in range(20)]


def test_validate_passes_a_well_formed_file():
    v = drift.validate(book(ROWS), FAKE, baseline_rows=18)
    assert v["ok"] and v["row_count"] == 20 and v["id_fill"] == 1.0 and v["date_parse"] == 1.0


def test_validate_refuses_missing_columns_wrong_sheet_and_empty_ids():
    v = drift.validate(book([{k: v for k, v in r.items() if k != "ISD"} for r in ROWS]), FAKE)
    assert not v["ok"] and v["missing_columns"] == ["ISD"] and "columns changed" in v["message"]
    v = drift.validate(book(ROWS, sheet="Sheet1"), FAKE)
    assert not v["ok"] and "expected sheet" in v["message"]
    v = drift.validate(book([{**r, "Id": None} for r in ROWS]), FAKE)
    assert not v["ok"] and "no rows with an id" in v["message"]


def test_validate_refuses_dates_that_stopped_parsing_and_row_count_jumps():
    v = drift.validate(book([{**r, "ISD": "Q3 next year"} for r in ROWS]), FAKE)
    assert not v["ok"] and "in-service dates parse" in v["message"] and v["sample_issues"]
    v = drift.validate(book(ROWS), FAKE, baseline_rows=200)
    assert not v["ok"] and "far from" in v["message"]
    v = drift.validate(io.BytesIO(b"<html>maintenance</html>"), FAKE)
    assert not v["ok"] and "could not open" in v["message"]


def test_validate_reads_regex_sheets_and_columns_and_us_dates():
    src = Source("rx", "RX", "rx", "rx", "u", [], None, re.compile(r"^Planned\d+$"), 0, ["Id", re.compile(r"^ISD .* ed$")], "Id",
                 re.compile(r"^ISD .* ed$"), 7)
    rows = [{"Id": i, "ISD July 2026 ed": "6/1/2027"} for i in range(5)]
    v = drift.validate(book(rows, sheet="Planned0713"), src)
    assert v["ok"] and v["sheets"] == ["Planned0713"] and v["date_parse"] == 1.0


def test_every_real_source_still_validates_the_file_we_loaded():
    for key, src in SOURCES.items():
        path = ROOT / __import__("importlib").import_module(f"app.ingest.national.{src.module}").FILE
        if not path.exists():
            pytest.skip(f"{key} file not downloaded")
        v = drift.validate(path, src)
        assert v["ok"], (key, v["message"])


def test_diff_finds_added_removed_and_changed_fields():
    old = {"a": {"id": "a", "org_id": "o", "name": "A", "status": "planned", "voltage_kv": 138, "cost_usd": 1e6, "in_service": "2027-06-01", "start": "2026-01-01", "end": "2027-06-01"},
           "b": {"id": "b", "org_id": "o", "name": "B", "status": "planned", "voltage_kv": 69, "cost_usd": None, "in_service": "2027-01-01", "start": "2026-01-01", "end": "2027-01-01"}}
    new = {"a": {**old["a"], "in_service": "2028-06-01", "end": "2028-06-01"}, "c": {**old["b"], "id": "c", "name": "C"}}
    d = stage.diff(old, new, {"a", "c"})
    assert d["added"] == ["c"] and d["removed"] == ["b"] and [x["id"] for x in d["changed"]] == ["a"]
    assert d["changed"][0]["changes"] == {"in_service": ["2027-06-01", "2028-06-01"], "end": ["2027-06-01", "2028-06-01"]}
    assert stage.review_share(d) == 1.0 and "1 new, 1 changed, 1 gone out of 2" in stage.summary(d)


def test_discovery_picks_the_newest_edition_and_falls_back_to_the_manifest_url():
    spp = SOURCES["spp"]
    html = ('<a href="/Documents/56611/2025 SPP Transmission Expansion Plan Report.zip">2025</a>'
            '<a href="/Documents/76727/2026 SPP Transmission Expansion (STEP) Plan.zip">2026</a>'
            '<a href="/Documents/80001/2027 SPP Transmission Expansion (STEP) Plan.zip">2027</a>')
    url, edition, how = discover(spp, get=lambda u: SimpleNamespace(status_code=200, text=html))
    assert url == "https://www.spp.org/Documents/80001/2027%20SPP%20Transmission%20Expansion%20(STEP)%20Plan.zip" and edition == "2027" and how == "index"
    url, edition, how = discover(spp, get=lambda u: SimpleNamespace(status_code=503, text=""))
    assert url == spp.manifest_url and how == "discovery_failed"
    caiso = SOURCES["caiso"]
    live = {"https://www.caiso.com/documents/approved-projects-transmission-planning-process-jul-2026.xlsx",
            "https://www.caiso.com/documents/approved-projects-transmission-planning-process-sep-2026.xlsx"}
    url, edition, how = discover(caiso, head=lambda u: SimpleNamespace(status_code=200 if u in live else 404))
    assert url.endswith("sep-2026.xlsx") and edition == "sep-2026" and how == "probe"  # the newest month that answers wins
    url, edition, how = discover(caiso, head=lambda u: SimpleNamespace(status_code=404))
    assert url == caiso.manifest_url and how == "discovery_failed"
    assert newest(["https://www.ercot.com/files/docs/2026/07/13/a-TPIT-No-Cost.xlsx", "https://www.ercot.com/files/docs/2026/09/01/b-TPIT-No-Cost.xlsx"], SOURCES["ercot"]).endswith("b-TPIT-No-Cost.xlsx")


def test_fetch_unpacks_the_spp_zip_and_refuses_html():
    inner = book(ROWS).getvalue()
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("2027 SPP Transmission Expansion (STEP) Plan/2027 STEP Report Appendix 1.xlsx", inner)
        zf.writestr("2027 SPP Transmission Expansion (STEP) Plan/report.pdf", b"%PDF")
    ok = SimpleNamespace(status_code=200, content=z.getvalue(), raise_for_status=lambda: None)
    assert fetch(SOURCES["spp"], "u", get=lambda u: ok) == inner
    bad = SimpleNamespace(status_code=200, content=b"<html>down</html>", raise_for_status=lambda: None)
    with pytest.raises(RuntimeError, match="not a spreadsheet"):
        fetch(FAKE, "u", get=lambda u: bad)


def test_pjm_export_posts_the_grid_body():
    seen = {}

    def post(u, d):
        seen["url"], seen["data"] = u, d
        return SimpleNamespace(status_code=200, content=book(ROWS).getvalue(), raise_for_status=lambda: None)
    fetch(SOURCES["pjm"], SOURCES["pjm"].manifest_url, post=post)
    assert "CostAllocation" in seen["data"]["jsonModel"] and seen["url"].startswith("https://www.pjm.com")


def test_loop_isolates_a_failing_source():
    calls = []

    def check(key):
        calls.append(key)
        if key == "miso":
            raise RuntimeError("site down")
        return {"id": 1, "status": "unchanged", "edition": "x", "error": None}
    out = promote.refresh_once(["pjm", "miso", "spp"], rest=lambda *a, **k: None, check=check)
    assert calls == ["pjm", "miso", "spp"] and out["miso"]["status"] == "failed" and "site down" in out["miso"]["error"]
    assert out["pjm"]["status"] == "unchanged" and out["spp"]["status"] == "unchanged"


def test_loop_auto_promotes_small_updates_and_holds_big_ones():
    small = {"id": 7, "status": "staged", "edition": "e", "error": None, "sha256": "abc1234567890", "source": "pjm",
             "diff": {"added": ["x"], "changed": [], "removed": [], "old_count": 100, "new_count": 101, "samples": {}}}
    applied = []
    out = promote.refresh_once(["pjm"], rest=lambda *a, **k: None, check=lambda k: small, apply=lambda rid, rest: applied.append(rid) or {**small, "status": "promoted"})
    assert applied == [7] and out["pjm"]["status"] == "promoted"
    big = {**small, "diff": {**small["diff"], "removed": [f"r{i}" for i in range(60)]}}
    bells = []
    out = promote.refresh_once(["pjm"], rest=lambda path, method="GET", **kw: bells.append(kw.get("json")), check=lambda k: big, apply=lambda *a: pytest.fail("must not apply"))
    assert out["pjm"]["status"] == "staged" and out["pjm"]["waiting"]


# the database half: a fake planner loaded into the real schema, staged (rolled back) and then promoted
try:
    with psycopg.connect(DATABASE_URL, connect_timeout=3) as c:
        HAVE_DB = c.execute("SELECT count(*) FROM job").fetchone()[0] > 0
except Exception:
    HAVE_DB = False
needs_db = pytest.mark.skipif(not HAVE_DB, reason="database not reachable or empty")

ORG = "test-refresh-org"


def fake_loader(rows):
    """A loader shaped like the real ones: registers the org and a source_doc for the given file, upserts jobs at a fixed spot."""
    def load(conn, src, rel_path):
        from app.ingest.national.common import register_org, register_source
        register_org(conn, ORG, "Refresh Test Utility", "Refresh Test", "SC", "FAKE", ORG)
        doc = register_source(conn, ORG, "fake list", "https://x.test", rel_path, "FAKE", "test")
        for r in rows:
            conn.execute("""INSERT INTO job (id, org_id, name, horizon, job_type, voltage_kv, geom, geom_quality, work_window, in_service, cost_usd, source_doc_id,
                                             extraction, confidence, resources, state, planner, status, window_basis)
                            VALUES (%(id)s, %(org)s, %(name)s, 'long', 'line', 138, ST_GeogFromText('POINT(-80.5 33.5)'), 'matched_point',
                                    tstzrange(%(start)s, %(end)s), %(end)s, %(cost)s, %(doc)s, 'parser', 0.9, ARRAY['crews'], 'SC', 'FAKE', %(status)s, 'test')
                            ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, work_window = EXCLUDED.work_window, in_service = EXCLUDED.in_service,
                              cost_usd = EXCLUDED.cost_usd, source_doc_id = EXCLUDED.source_doc_id, status = EXCLUDED.status""",
                         {**r, "org": ORG, "doc": doc})
        return {"SC": {"org": ORG, "placed": len(rows), "review": 0}}, [doc]
    return load


@pytest.fixture
def fake_source(tmp_path, monkeypatch):
    """A source whose loader module is a stub with a FILE under data/, cleaned from the database afterwards."""
    folder = ROOT / "data" / "raw" / "national" / "_test_refresh"
    folder.mkdir(parents=True, exist_ok=True)
    canonical = folder / "list.xlsx"
    book(ROWS, path=canonical)
    src = Source("fake", "FAKE", "fake planner", "fake", "https://x.test/list.xlsx", [], None, "Data", 0, ["Id", "Name", "ISD", "Status"], "Id", "ISD", 7)
    monkeypatch.setitem(SOURCES, "fake", src)
    import importlib
    from app.refresh import sources
    real = sources.src_file
    monkeypatch.setattr(sources, "src_file", lambda s: "data/raw/national/_test_refresh/list.xlsx" if s.key == "fake" else real(s))
    monkeypatch.setattr(promote, "src_file", sources.src_file)
    from app.db import connect
    with connect() as c:
        stage.ensure(c)
        c.execute("DELETE FROM job WHERE org_id = %s", (ORG,))
    yield src, canonical
    with connect() as c:
        c.execute("DELETE FROM job WHERE org_id = %s", (ORG,))
        c.execute("DELETE FROM job_review WHERE org_id = %s", (ORG,))
        c.execute("DELETE FROM source_doc WHERE org_id = %s", (ORG,))
        c.execute("DELETE FROM org WHERE id = %s", (ORG,))
        c.execute("DELETE FROM source_refresh WHERE source = 'fake'")
    for p in folder.glob("**/*"):
        if p.is_file():
            p.unlink()


def jobs(start="2026-01-01", end="2027-06-01", n=20, cost=1e6, status="planned"):
    return [{"id": f"fake-{i}", "name": f"Line {i}", "start": start, "end": end, "cost": cost, "status": status} for i in range(n)]


@needs_db
def test_stage_rolls_back_the_trial_load_and_keeps_only_the_diff(fake_source, monkeypatch):
    src, canonical = fake_source
    from app.db import connect
    with connect() as c:  # the live load: 20 projects from the canonical file
        fake_loader(jobs())(c, src, "data/raw/national/_test_refresh/list.xlsx")
        before = c.execute("SELECT count(*) AS n FROM job WHERE org_id = %s", (ORG,)).fetchone()["n"]
    new_rows = ROWS[2:] + [{"Id": "f99", "Name": "Line 99", "ISD": "2028-01-01", "Status": "Planned"}]
    body = book(new_rows).getvalue()
    monkeypatch.setattr(stage, "load_staged", lambda conn, s, rel: fake_loader(jobs(n=18, end="2027-09-01")[:18] + [{"id": "fake-99", "name": "Line 99", "start": "2026-01-01", "end": "2028-01-01", "cost": 2e6, "status": "planned"}])(conn, s, rel))
    ok = SimpleNamespace(status_code=200, content=body, raise_for_status=lambda: None)
    row = stage.check("fake", get=lambda u: ok)
    assert row["status"] == "staged", row
    d = row["diff"]
    assert d["added"] == ["fake-99"] and d["removed"] == ["fake-18", "fake-19"] and len(d["changed"]) == 18
    assert d["changed"][0]["changes"]["end"] == ["2027-06-01", "2027-09-01"]
    with connect() as c:  # nothing of the trial reached the tables
        after = c.execute("SELECT count(*) AS n FROM job WHERE org_id = %s", (ORG,)).fetchone()["n"]
        assert after == before == 20
        assert c.execute("SELECT count(*) AS n FROM job WHERE id = 'fake-99'").fetchone()["n"] == 0
        assert c.execute("SELECT upper(work_window)::date::text AS e FROM job WHERE id = 'fake-0'").fetchone()["e"] == "2027-06-01"
        assert c.execute("SELECT count(*) AS n FROM source_doc WHERE sha256 = %s", (row["sha256"],)).fetchone()["n"] == 0
        saved = c.execute("SELECT status, staged_path FROM source_refresh WHERE id = %s", (row["id"],)).fetchone()
    assert saved["status"] == "staged" and (ROOT / saved["staged_path"]).exists()
    again = stage.check("fake", get=lambda u: ok)  # the same edition is not re-judged
    assert again["id"] == row["id"]


@needs_db
def test_stage_rejects_a_drifted_file_before_touching_the_database(fake_source, monkeypatch):
    src, _ = fake_source
    called = []
    monkeypatch.setattr(stage, "load_staged", lambda *a: called.append(1))
    body = book([{"Id": r["Id"], "Name": r["Name"], "Status": r["Status"]} for r in ROWS]).getvalue()
    row = stage.check("fake", get=lambda u: SimpleNamespace(status_code=200, content=body, raise_for_status=lambda: None))
    assert row["status"] == "rejected" and "ISD" in row["error"] and not called
    row = stage.check("fake", get=lambda u: SimpleNamespace(status_code=200, content=(ROOT / "data/raw/national/_test_refresh/list.xlsx").read_bytes(), raise_for_status=lambda: None))
    assert row["status"] == "unchanged"


@needs_db
def test_promote_keeps_history_drops_the_gone_and_rings_the_bell(fake_source, monkeypatch):
    src, canonical = fake_source
    from app.db import connect
    rel = "data/raw/national/_test_refresh/list.xlsx"
    with connect() as c:
        fake_loader(jobs())(c, src, rel)
    new_rows = ROWS[2:]
    body = book(new_rows).getvalue()
    edition = fake_loader(jobs(n=18, end="2027-09-01"))
    monkeypatch.setattr(stage, "load_staged", edition)
    row = stage.check("fake", get=lambda u: SimpleNamespace(status_code=200, content=body, raise_for_status=lambda: None))
    assert row["status"] == "staged"
    bells = []
    monkeypatch.setattr(promote, "companies", lambda: {ORG: {"id": ORG}})
    out = promote.promote(row["id"], rest=lambda path, method="GET", **kw: bells.append((path, kw.get("json"))), loader=edition)
    assert out["status"] == "promoted"
    with connect() as c:
        assert c.execute("SELECT count(*) AS n FROM job WHERE org_id = %s AND horizon = 'long'", (ORG,)).fetchone()["n"] == 18
        assert c.execute("SELECT upper(work_window)::date::text AS e FROM job WHERE id = 'fake-0'").fetchone()["e"] == "2027-09-01"
        hist = c.execute("SELECT job_id, upper(work_window)::date::text AS e FROM job_version WHERE job_id = 'fake-0'").fetchall()
        assert [h["e"] for h in hist] == ["2027-06-01"]  # the earlier window is kept
        assert c.execute("SELECT count(*) AS n FROM job_version WHERE job_id IN ('fake-18', 'fake-19')").fetchone()["n"] == 0
        phases = c.execute("SELECT count(*) AS n, min(upper(work_window))::date::text AS first FROM job WHERE parent_job_id = 'fake-0'").fetchone()
        assert phases["n"] > 0 and phases["first"] > "2026-01-01"  # the near-term phases were rebuilt from the new window
        st = c.execute("SELECT status, promoted_at FROM source_refresh WHERE id = %s", (row["id"],)).fetchone()
        assert st["status"] == "promoted" and st["promoted_at"]
        assert c.execute("SELECT count(*) AS n FROM source_doc WHERE sha256 = %s", (row["sha256"],)).fetchone()["n"] == 1
    assert canonical.read_bytes() == body and canonical.with_suffix(".xlsx.prev").exists()  # the loader's file is the new edition now
    assert bells and bells[0][0] == "notification"
    b = bells[0][1]
    assert b["company_id"] == ORG and b["dedup_key"] == f"refresh:fake:{row['sha256'][:10]}" and b["kind"] == "suggestion"
    assert "18 changed, 2 gone" in b["body"] and b["action"]["type"] == "chat"
    with pytest.raises(ValueError, match="only a staged"):
        promote.promote(row["id"])
