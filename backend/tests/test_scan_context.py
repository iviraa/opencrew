"""The discovery scan's one round trip: company-scoped, ordered, and consistent with the overlaps endpoint."""
import os

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import current_user

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs the planner database")


@pytest.fixture
def client():
    main.app.dependency_overrides[current_user] = lambda: {"id": "u", "company": "gpc", "other": "desc", "username": "georgia", "token": "t"}
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()


def test_scan_context_is_scoped_and_ordered(client):
    d = client.get("/api/app/scan_context").json()
    ours = {f["properties"]["id"] for f in d["ours"]["features"]}
    partners = {f["properties"]["id"] for f in d["partners"]["features"]}
    others = d["others"]["features"]
    assert all(f["properties"]["org_id"] == "gpc" for f in d["ours"]["features"])
    assert all(f["properties"]["org_id"] != "gpc" for f in others), "our own sites never show as other utilities"
    assert not ({f["properties"]["id"] for f in others} & (ours | partners)), "partner sites are drawn once, in color"
    dist = [f["properties"]["distance_km"] for f in others]
    assert dist == sorted(dist) and len(others) <= 1500
    ends = {o["job_a"] for o in d["overlaps"]} | {o["job_b"] for o in d["overlaps"]}
    assert ends <= ours | partners, "every overlap end is on the map"
    assert len(d["overlaps"]) == len(client.get("/api/app/overlaps").json()["overlaps"])
    assert len(d["center"]) == 2 and d["radius_km"] == 400


def test_scan_context_rejects_bad_center(client):
    assert client.get("/api/app/scan_context", params={"center": "abc"}).status_code == 422
    assert client.get("/api/app/scan_context", params={"radius_km": 5}).status_code == 422
