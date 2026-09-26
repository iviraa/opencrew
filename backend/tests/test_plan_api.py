import psycopg
import pytest

from app.db import DATABASE_URL

try:
    with psycopg.connect(DATABASE_URL, connect_timeout=3) as c:
        JOBS = c.execute("SELECT count(*) FROM job").fetchone()[0]
except Exception:  # no server or no schema yet
    JOBS = 0
if not JOBS:
    pytest.skip("database not reachable or empty; run scripts.build_all first", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402

from app.crewly.tools import TOOLS  # noqa: E402
from app.db import connect  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def solved(client):
    r = client.post("/api/plan/solve", json={"constraints": {"max_slip_months": 6}})
    assert r.status_code == 200
    return r.json()


def test_coordinated_never_worse_and_nobody_late(solved):
    assert solved["status"] in ("optimal", "feasible")
    assert solved["coordinated"]["cost_k"] <= solved["baseline"]["cost_k"]
    assert solved["coordinated"]["mobilizations"] <= solved["baseline"]["mobilizations"]
    assert solved["headline"]["late_projects"] == 0
    assert all(r["slip"] <= r["slip_limit"] for r in solved["schedule"])
    assert {p["phase"] for r in solved["schedule"] for p in r["phases"]} == {"survey & permitting", "clearing", "construction", "energization"}


def test_latest_and_explain(client, solved):
    assert client.get("/api/plan").json()["plan_id"] == solved["plan_id"]
    d = next(d for d in solved["decisions"] if d["eligible"])
    e = client.get(f"/api/plan/explain?opportunity_id={d['opportunity_id']}").json()
    assert e["decisions"][0]["sentence"] and "Ask why" not in e["decisions"][0]["sentence"]  # counterfactual filled in
    assert client.get("/api/plan/explain").status_code == 400


def test_constraints_validate_and_echo(client):
    ok = client.post("/api/plan/constraints", json={"constraints": {"blackouts": [{"site": "Okatie", "months": [6, 7, 8]}],
                                                                    "slip_overrides": {"Jasper – Okatie": 2}}}).json()
    assert ok["valid"] and ok["constraints"]["blackouts"][0]["phase_kind"] == "energization"
    assert any("Jun, Jul, Aug" in n for n in ok["notes"]) and list(ok["constraints"]["slip_overrides"].values()) == [2]
    bad = client.post("/api/plan/constraints", json={"constraints": {"blackouts": [{"site": "Nowhere", "months": [13]}]}}).json()
    assert not bad["valid"] and len(bad["errors"]) == 2
    assert client.post("/api/plan/solve", json={"constraints": {"crew_counts": {"nobody": {"2025": 1}}}}).status_code == 422


def test_crewly_proposes_but_does_not_solve(client, solved):
    with connect() as conn:
        before = conn.execute("SELECT max(id) AS n FROM joint_plan").fetchone()["n"]
        out, actions = TOOLS["propose_constraints"][0](conn, blackout={"site": "Okatie", "months": [6, 7, 8]})
        after = conn.execute("SELECT max(id) AS n FROM joint_plan").fetchone()["n"]
    assert before == after  # proposing never runs the solver
    assert actions[0]["type"] == "pending_constraints" and out["rules"]
