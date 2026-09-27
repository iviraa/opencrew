import hashlib
import struct
import time
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient

from app.bounties import api as bapi, chain
from app.db import connect, get_conn
from app.main import app


def keypair():
    k = Ed25519PrivateKey.generate()
    return k, chain.b58encode(k.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


def account_bytes(sponsor, bounty_id, reviewers, approvals=0, status=1, contributor=None, submission=None, deadline=None):
    raw = lambda w: chain.b58decode(w)  # noqa: E731
    data = chain.ACCOUNT_DISCRIMINATOR + raw(sponsor) + struct.pack("<QQq", bounty_id, 500_000_000, deadline or int(time.time()) + 86400)
    data += b"\1" * 32 + b"\2" * 32 + struct.pack("<I", len(reviewers)) + b"".join(raw(r) for r in reviewers)
    data += bytes([1, approvals]) + (submission or b"\0" * 32) + (raw(contributor) if contributor else b"\0" * 32)
    return data + bytes([status]) + struct.pack("<qqq", 1_800_000_000, 1_800_000_100, 0) + b"\xff"


def test_base58_round_trip():
    assert chain.b58encode(b"\0" * 32) == "1" * 32  # the system program id
    for raw in (b"\0\0\1\2", hashlib.sha256(b"x").digest(), b"\xff" * 64):
        assert chain.b58decode(chain.b58encode(raw)) == raw
    assert chain.is_wallet("11111111111111111111111111111111")
    assert not chain.is_wallet("not-a-wallet!") and not chain.is_wallet("abc")


def test_commitment_is_canonical():
    assert chain.commitment({"a": 1, "b": "é"}) == chain.commitment({"b": "é", "a": 1})
    assert chain.commitment({"a": 1}) != chain.commitment({"a": 2})


def test_wallet_signature():
    k, wallet = keypair()
    sig = chain.b58encode(k.sign(b"hello"))
    assert chain.verify_wallet_signature(wallet, "hello", sig)
    assert not chain.verify_wallet_signature(wallet, "hellO", sig)
    assert not chain.verify_wallet_signature(keypair()[1], "hello", sig)


def test_decode_bounty_account():
    _, sponsor = keypair()
    reviewers = [keypair()[1] for _ in range(3)]
    _, contributor = keypair()
    s = chain.decode_bounty(account_bytes(sponsor, 42, reviewers, approvals=0b101, status=2, contributor=contributor, submission=b"\x07" * 32))
    assert s["sponsor"] == sponsor and s["bounty_id"] == 42 and s["reward_lamports"] == 500_000_000
    assert s["reviewers"] == reviewers and s["threshold"] == 1
    assert s["approved_by"] == [reviewers[0], reviewers[2]]
    assert s["status"] == "paid" and s["contributor"] == contributor and s["submission_commitment"] == "07" * 32
    with pytest.raises(ValueError):
        chain.decode_bounty(b"\0" * 200)


@pytest.fixture
def client():
    """Every request shares one connection that is rolled back afterwards, so the database is left untouched."""
    try:
        conn = connect()
    except Exception:
        pytest.skip("database unreachable")

    def shared():
        yield conn

    app.dependency_overrides[get_conn] = shared
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_conn, None)
        conn.rollback()
        conn.close()


@pytest.fixture
def world(client, monkeypatch):
    """A sponsor, two reviewers, and a fake devnet that holds whatever account bytes the test sets."""
    sponsor_key, sponsor = keypair()
    revs = [keypair() for _ in range(2)]
    chain_state = {}
    monkeypatch.setattr(chain, "confirmed_tx_touching", lambda sig, addr: addr in chain_state)
    monkeypatch.setattr(chain, "fetch_bounty", lambda addr: chain.decode_bounty(chain_state[addr]) if addr in chain_state else None)
    return {"client": client, "sponsor": sponsor, "reviewers": revs, "chain": chain_state}


def new_bounty(w, threshold=1):
    body = {"title": "Downed line photos, Aiken County", "description": "Photos of downed distribution lines after the storm.",
            "region": "Aiken County, SC", "rules": "Timestamped photo, no faces, no private property interiors.",
            "reward_sol": 0.5, "deadline": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
            "sponsor": w["sponsor"], "reviewers": [r[1] for r in w["reviewers"]], "threshold": threshold}
    r = w["client"].post("/api/bounties", json=body)
    assert r.status_code == 200, r.text
    return r.json()


SIG = chain.b58encode(b"\x05" * 64)
PDA = chain.b58encode(b"\x09" * 32)


def fund(w, bid, **acct):
    w["chain"][PDA] = account_bytes(w["sponsor"], bid, [r[1] for r in w["reviewers"]], **acct)
    return w["client"].post(f"/api/bounties/{bid}/sync", json={"signature": SIG, "kind": "create", "pda": PDA})


def review_headers(bid, key, wallet, issued=None):
    issued = issued or int(time.time())
    sig = chain.b58encode(key.sign(bapi.review_message(bid, wallet, issued).encode()))
    return {"X-Bounty-Wallet": wallet, "X-Bounty-Issued": str(issued), "X-Bounty-Signature": sig}


def test_draft_is_private_until_funded_on_chain(world):
    c = world["client"]
    made = new_bounty(world)
    bid = made["id"]
    assert made["chain_args"]["reward_lamports"] == 500_000_000
    assert len(made["chain_args"]["rules_commitment"]) == 64
    assert c.get(f"/api/bounties/{bid}").status_code == 404
    assert bid not in [b["id"] for b in c.get("/api/bounties").json()]

    r = fund(world, bid)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "funded" and r.json()["pda"] == PDA
    assert bid in [b["id"] for b in c.get("/api/bounties").json()]
    # retrying the same signature is harmless
    assert c.post(f"/api/bounties/{bid}/sync", json={"signature": SIG, "kind": "create"}).status_code == 200
    assert len(c.get(f"/api/bounties/{bid}/transactions").json()) == 1


def test_sync_rejects_someone_elses_account(world):
    bid = new_bounty(world)["id"]
    world["chain"][PDA] = account_bytes(keypair()[1], bid, [r[1] for r in world["reviewers"]])
    r = world["client"].post(f"/api/bounties/{bid}/sync", json={"signature": SIG, "kind": "create", "pda": PDA})
    assert r.status_code == 400


def test_create_validates_wallets(world):
    c = world["client"]
    base = {"title": "Tree on line", "description": "Photos of trees on lines please.", "region": "Augusta, GA",
            "rules": "Photo with timestamp please.", "reward_sol": 0.1,
            "deadline": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(), "threshold": 1}
    assert c.post("/api/bounties", json={**base, "sponsor": "nope", "reviewers": [world["sponsor"]]}).status_code == 400
    two = [world["sponsor"], world["sponsor"]]
    assert c.post("/api/bounties", json={**base, "sponsor": world["sponsor"], "reviewers": two}).status_code == 400
    past = {**base, "deadline": "2020-01-01T00:00:00Z", "sponsor": world["sponsor"], "reviewers": [world["sponsor"]]}
    assert c.post("/api/bounties", json=past).status_code == 400


def test_submission_is_private_and_deduplicated(world):
    c = world["client"]
    bid = new_bounty(world)["id"]
    _, contributor = keypair()
    form = {"wallet": contributor, "email": "ground@example.com", "summary": "Line down across Pine St after the storm.", "location": "33.5601, -81.7196"}
    files = {"file": ("photo.png", b"\x89PNG fake", "image/png")}

    assert c.post(f"/api/bounties/{bid}/submissions", data=form).status_code == 400  # not funded yet
    fund(world, bid)
    first = c.post(f"/api/bounties/{bid}/submissions", data=form, files=files).json()
    again = c.post(f"/api/bounties/{bid}/submissions", data=form, files=files).json()
    assert len(first["commitment"]) == 64 and not first["duplicate"]
    assert again == {**first, "duplicate": True}
    assert c.post(f"/api/bounties/{bid}/submissions", data={**form, "wallet": "bad"}).status_code == 400
    assert c.post(f"/api/bounties/{bid}/submissions", data={**form, "email": "nope"}).status_code == 400
    html = {"file": ("x.html", b"<script>", "text/html")}
    assert c.post(f"/api/bounties/{bid}/submissions", data=form, files=html).status_code == 415

    public = c.get(f"/api/bounties/{bid}").json()
    assert public["submissions"] == 1
    assert "33.5601" not in str(public) and "Pine St" not in str(public)
    assert "33.5601" not in c.get("/api/bounties").text

    # reviewers only, with a fresh signature from their own wallet
    key, wallet = world["reviewers"][0]
    assert c.get(f"/api/bounties/{bid}/submissions").status_code == 401
    outsider_key, outsider = keypair()
    assert c.get(f"/api/bounties/{bid}/submissions", headers=review_headers(bid, outsider_key, outsider)).status_code == 403
    stale = review_headers(bid, key, wallet, issued=int(time.time()) - 3600)
    assert c.get(f"/api/bounties/{bid}/submissions", headers=stale).status_code == 401
    forged = {**review_headers(bid, key, wallet), "X-Bounty-Signature": review_headers(bid, outsider_key, outsider)["X-Bounty-Signature"]}
    assert c.get(f"/api/bounties/{bid}/submissions", headers=forged).status_code == 401

    rows = c.get(f"/api/bounties/{bid}/submissions", headers=review_headers(bid, key, wallet)).json()
    assert rows[0]["email"] == "ground@example.com" and rows[0]["location"] == "33.5601, -81.7196" and rows[0]["commitment"] == first["commitment"]
    ev = c.get(f"/api/bounties/{bid}/submissions/{first['id']}/evidence", headers=review_headers(bid, key, wallet))
    assert ev.content == b"\x89PNG fake" and ev.headers["x-content-type-options"] == "nosniff"


def test_payout_state_comes_from_chain(world):
    c = world["client"]
    bid = new_bounty(world, threshold=2)["id"]
    fund(world, bid)
    _, contributor = keypair()
    sub = c.post(f"/api/bounties/{bid}/submissions", data={"wallet": contributor, "email": "ground@example.com"}).json()

    world["chain"][PDA] = account_bytes(world["sponsor"], bid, [r[1] for r in world["reviewers"]], approvals=0b11, status=2,
                                        contributor=contributor, submission=bytes.fromhex(sub["commitment"]))
    r = c.post(f"/api/bounties/{bid}/sync", json={"signature": chain.b58encode(b"\x06" * 64), "kind": "approve"}).json()
    assert r["status"] == "paid" and r["contributor"] == contributor and len(r["approved_by"]) == 2
    key, wallet = world["reviewers"][1]
    rows = c.get(f"/api/bounties/{bid}/submissions", headers=review_headers(bid, key, wallet)).json()
    assert rows[0]["approved"]


def test_bounties_router_is_mounted():
    paths = app.openapi()["paths"]
    assert "/api/bounties" in paths and "/api/bounties/{bid}/sync" in paths
