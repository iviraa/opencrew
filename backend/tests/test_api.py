import json

import psycopg
import pytest
from rapidfuzz import fuzz, process

from app.db import DATABASE_URL, ROOT, connect

try:
    with psycopg.connect(DATABASE_URL, connect_timeout=3) as c:
        JOBS = c.execute("SELECT count(*) FROM job").fetchone()[0]
except Exception:  # no server or no schema yet
    JOBS = 0
if not JOBS:
    pytest.skip("database not reachable or empty; run scripts.build_all first", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402

from app.engine.overlap import recompute  # noqa: E402
from app.engine.phases import build_phases  # noqa: E402
from app.main import app  # noqa: E402
from scripts.validate import sheet  # noqa: E402

UPLOADS = ROOT / "data/raw/uploads"


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    for key in ("GEMINI_API_KEY", "RESEND_API_KEY", "GOOGLE_PLACES_KEY"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def opps(client):
    return client.get("/api/opportunities").json()


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] and r.json()["jobs"] > 0


def test_opportunities_sorted_by_score(opps):
    scores = [o["score"] for o in opps]
    assert scores and scores == sorted(scores, reverse=True)


def test_organizer_pairs_present(client, opps):
    jobs = [f["properties"] for f in client.get("/api/jobs").json()["features"]]
    ids = {}
    for p in sheet("projects"):
        org = "desc" if p["project_id"].startswith("DESC") else "gpc"
        hit = process.extractOne(p["project_name"], {j["id"]: j["name"] for j in jobs if j["org_id"] == org}, scorer=fuzz.token_sort_ratio)
        ids[p["project_id"]] = hit[2] if hit and hit[1] >= 80 else None
    pairs = {(o["job_a"], o["job_b"]): o for o in opps}
    for row in sheet("overlaps"):
        a, b = ids[row["project_id_a"]], ids[row["project_id_b"]]
        opp = pairs.get(tuple(sorted((a, b))))
        assert opp, f"{row['overlap_id']} missing"
        assert abs(opp["center_distance_m"] / 1609.344 - row["distance_mi"]) < 0.01
        assert opp["time_gap_days"] == row["time_gap (day)"]


def test_detail_has_shareable_and_savings(client, opps):
    d = client.get(f"/api/opportunities/{opps[0]['id']}").json()
    assert d["shareable"] and d["savings"]["low"] <= d["savings"]["high"]
    assert d["a"]["id"] == d["job_a"] and d["b"]["id"] == d["job_b"]


def test_savings_overrides(client, opps):
    crew = next(o for o in opps if o["tier"] == "crew")
    base = client.post(f"/api/opportunities/{crew['id']}/savings", json={}).json()
    cheap = client.post(f"/api/opportunities/{crew['id']}/savings", json={"assumptions": {"mobilization_usd": {"low": 1000, "high": 2000}}}).json()
    assert (cheap["low"], cheap["high"]) == (1000, 2000) and cheap != base


def test_status_rejects_unknown(client, opps):
    assert client.patch(f"/api/opportunities/{opps[0]['id']}/status", json={"status": "bogus"}).status_code == 400


def test_outreach_needs_approval(client, opps):
    opp = opps[0]
    contact = client.get(f"/api/opportunities/{opp['id']}/contacts").json()[0]
    draft = client.post("/api/outreach", json={"opportunity_id": opp["id"], "contact_id": contact["id"]})
    assert draft.status_code == 200 and draft.json()["state"] == "draft"
    oid = draft.json()["id"]
    try:
        early = client.post(f"/api/outreach/{oid}/send")
        assert early.status_code == 409 and "approved" in early.json()["detail"]
        assert client.post(f"/api/outreach/{oid}/approve", json={"approved_by": "  "}).status_code == 400
        ok = client.post(f"/api/outreach/{oid}/approve", json={"approved_by": "tester"})
        assert ok.status_code == 200 and ok.json()["state"] == "approved"
        sent = client.post(f"/api/outreach/{oid}/send")
        assert sent.status_code == 409 and ("demo inboxes" in sent.json()["detail"] or "not configured" in sent.json()["detail"])
    finally:
        with connect() as conn:  # leave the database as we found it
            conn.execute("DELETE FROM outreach WHERE id = %s", (oid,))
            conn.execute("UPDATE opportunity SET status = %s WHERE id = %s", (opp["status"], opp["id"]))


def test_ingest_rejects_non_pdf(client):
    before = set(UPLOADS.iterdir()) if UPLOADS.exists() else set()
    try:
        r = client.post("/api/ingest", files={"file": ("x.pdf", b"not a pdf", "application/pdf")})
        assert r.status_code == 422 and "not a PDF" in r.json()["detail"]
    finally:
        for f in set(UPLOADS.iterdir()) - before:  # drop the test upload
            f.unlink()


@pytest.mark.parametrize("url", ["http://127.0.0.1:8000/api/health", "http://localhost/x.pdf", "file:///etc/passwd"])
def test_ingest_rejects_private_urls(client, url):
    assert client.post("/api/ingest", data={"url": url}).status_code == 400


def test_manual_placement_leaves_review(client):
    with connect() as conn:
        row = conn.execute("SELECT * FROM job_review WHERE raw ? 'id' ORDER BY id LIMIT 1").fetchone()
    assert row
    job_id = row["raw"]["id"]
    try:
        r = client.post(f"/api/review/{row['id']}/place", json={"lon": -81.0, "lat": 33.5})
        assert r.status_code == 200 and r.json()["job_id"] == job_id
        assert row["id"] not in [i["id"] for i in client.get("/api/review").json()]
        placed = [f for f in client.get("/api/jobs").json()["features"] if f["id"] == job_id]
        assert placed and placed[0]["properties"]["geom_quality"] == "manual"
    finally:
        with connect() as conn:  # put the project back in review
            conn.execute("DELETE FROM job WHERE id = %s", (job_id,))
            conn.execute("INSERT INTO job_review (id, org_id, raw, reason, source_doc_id, source_page) VALUES (%s, %s, %s, %s, %s, %s) "
                         "ON CONFLICT (id) DO NOTHING", (row["id"], row["org_id"], json.dumps(row["raw"]), row["reason"], row["source_doc_id"], row["source_page"]))
            build_phases(conn)
            recompute(conn, "long")
            recompute(conn, "near")


def test_storm_frame_after_landfall(client):
    f = client.get("/api/storm/frame", params={"at": "2024-09-27T15:10:00Z"}).json()
    assert len(f["reports"]["features"]) > 0 and len(f["staging"]["features"]) >= 1
    assert f["track"]["features"] and f["cone"]["features"]


def test_procurement_shared_spare(client):
    groups = client.get("/api/procurement").json()
    spare = [g for g in groups if "Summerville" in g["desc"]["name"] and "Spare" in g["desc"]["name"]]
    assert spare and all(x["reason"] == "shared spare pool" for x in spare[0]["gpc"])


def test_crewly_offline_without_key(client):
    r = client.post("/api/crewly", json={"messages": [{"role": "user", "text": "hi"}]})
    assert r.status_code == 200 and "offline" in r.json()["reply"]
