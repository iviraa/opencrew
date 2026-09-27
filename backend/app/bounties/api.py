"""/api/bounties: public bounty records, private evidence, and chain sync. Solana is only reached from here.

The chain is the source of truth for money and approvals; these tables hold what cannot go on-chain
(text, evidence) and a cached copy of the account state that `/sync` refreshes after each transaction.
"""
import hashlib
import re
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.bounties import chain
from app.db import get_conn

router = APIRouter(prefix="/api/bounties")

TABLE_SQL = """
CREATE SCHEMA IF NOT EXISTS bounty;
CREATE TABLE IF NOT EXISTS bounty.bounty (
  id BIGSERIAL PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL, region TEXT NOT NULL, rules TEXT NOT NULL,
  reward_lamports BIGINT NOT NULL, deadline TIMESTAMPTZ NOT NULL, sponsor TEXT NOT NULL, reviewers TEXT[] NOT NULL,
  threshold SMALLINT NOT NULL, rules_commitment TEXT NOT NULL, region_commitment TEXT NOT NULL,
  pda TEXT UNIQUE, status TEXT NOT NULL DEFAULT 'draft', approved_by TEXT[] NOT NULL DEFAULT '{}',
  contributor TEXT, submission_commitment TEXT, funded_at TIMESTAMPTZ, settled_at TIMESTAMPTZ,
  synced_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS bounty.submission (
  id BIGSERIAL PRIMARY KEY, bounty_id BIGINT NOT NULL REFERENCES bounty.bounty(id), wallet TEXT NOT NULL,
  summary TEXT NOT NULL, details TEXT, location TEXT, file_name TEXT, file_type TEXT, file_sha256 TEXT, evidence BYTEA,
  commitment TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE (bounty_id, commitment)
);
CREATE TABLE IF NOT EXISTS bounty.tx (
  signature TEXT PRIMARY KEY, bounty_id BIGINT NOT NULL REFERENCES bounty.bounty(id), kind TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE bounty.submission ADD COLUMN IF NOT EXISTS email TEXT"""

MAX_EVIDENCE_BYTES = 5 * 1024 * 1024
EVIDENCE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "application/pdf", "text/plain"}
REVIEW_TOKEN_TTL_S = 600
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TX_KINDS = {"create", "approve", "refund"}
PUBLIC_COLS = """id, title, description, region, rules, reward_lamports, deadline, sponsor, reviewers, threshold,
  rules_commitment, region_commitment, pda, status, approved_by, contributor, submission_commitment,
  funded_at, settled_at, created_at"""


def ensure(conn):
    conn.execute(TABLE_SQL)


def _ts(unix):
    return datetime.fromtimestamp(unix, timezone.utc) if unix else None


def public(row, submissions=0):
    """The only shape of a bounty that leaves the server without reviewer auth."""
    out = dict(row)
    out["reward_sol"] = row["reward_lamports"] / chain.LAMPORTS_PER_SOL
    out["expired"] = row["status"] == "funded" and row["deadline"] < datetime.now(timezone.utc)
    out["submissions"] = submissions
    out["explorer"] = chain.explorer("address", row["pda"]) if row["pda"] else None
    return out


def _load(conn, bid):
    row = conn.execute(f"SELECT {PUBLIC_COLS} FROM bounty.bounty WHERE id = %s", (bid,)).fetchone()
    if not row:
        raise HTTPException(404, "no such bounty")
    return row


def _count(conn, bid):
    return conn.execute("SELECT count(*) AS n FROM bounty.submission WHERE bounty_id = %s", (bid,)).fetchone()["n"]


def refresh(conn, row, pda=None):
    """Copy the on-chain account into the row. Raises 400 when the account is missing or is not this bounty."""
    pda = row["pda"] or pda
    state = chain.fetch_bounty(pda) if pda else None
    if not state or state["sponsor"] != row["sponsor"] or state["bounty_id"] != row["id"]:
        raise HTTPException(400, "bounty account not found on devnet for this sponsor and id")
    conn.execute(
        """UPDATE bounty.bounty SET pda = %s, status = %s, approved_by = %s, contributor = %s, submission_commitment = %s,
           reward_lamports = %s, deadline = %s, funded_at = %s, settled_at = %s, synced_at = now() WHERE id = %s""",
        (pda, state["status"], state["approved_by"], state["contributor"], state["submission_commitment"],
         state["reward_lamports"], _ts(state["deadline"]), _ts(state["funded_at"]), _ts(state["settled_at"]), row["id"]))
    return _load(conn, row["id"])


class NewBounty(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=10, max_length=2000)
    region: str = Field(min_length=2, max_length=120, description="broad region only, never an exact address")
    rules: str = Field(min_length=10, max_length=2000)
    reward_sol: float = Field(gt=0, le=100)
    deadline: datetime
    sponsor: str
    reviewers: list[str] = Field(min_length=1, max_length=3)
    threshold: int = Field(ge=1, le=3)


class Sync(BaseModel):
    signature: str
    kind: str
    pda: str | None = None


@router.get("/config")
def config():
    return {"cluster": chain.CLUSTER, "rpc_url": chain.RPC_URL, "program_id": chain.PROGRAM_ID, "ready": bool(chain.PROGRAM_ID)}


@router.get("")
def list_bounties(conn=Depends(get_conn)):
    ensure(conn)
    rows = conn.execute(
        f"""SELECT {PUBLIC_COLS}, (SELECT count(*) FROM bounty.submission s WHERE s.bounty_id = b.id) AS n
            FROM bounty.bounty b WHERE status <> 'draft' ORDER BY created_at DESC""").fetchall()
    return [public({k: v for k, v in r.items() if k != "n"}, r["n"]) for r in rows]


@router.post("")
def create_bounty(body: NewBounty, conn=Depends(get_conn)):
    """A draft plus the exact arguments the sponsor's wallet passes to create_bounty. Public once /sync sees the account."""
    ensure(conn)
    wallets = [body.sponsor, *body.reviewers]
    if not all(chain.is_wallet(w) for w in wallets):
        raise HTTPException(400, "sponsor and reviewers must be Solana wallet addresses")
    if len(set(body.reviewers)) != len(body.reviewers) or body.threshold > len(body.reviewers):
        raise HTTPException(400, "reviewers must be distinct and threshold at most their count")
    deadline = body.deadline if body.deadline.tzinfo else body.deadline.replace(tzinfo=timezone.utc)
    if deadline <= datetime.now(timezone.utc):
        raise HTTPException(400, "deadline must be in the future")
    lamports = round(body.reward_sol * chain.LAMPORTS_PER_SOL)
    unix = int(deadline.timestamp())
    rules_c = chain.commitment({"title": body.title, "description": body.description, "rules": body.rules,
                                "reward_lamports": lamports, "deadline": unix}).hex()
    region_c = chain.commitment({"region": body.region}).hex()
    row = conn.execute(
        """INSERT INTO bounty.bounty (title, description, region, rules, reward_lamports, deadline, sponsor, reviewers,
             threshold, rules_commitment, region_commitment) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (body.title, body.description, body.region, body.rules, lamports, _ts(unix), body.sponsor, body.reviewers,
         body.threshold, rules_c, region_c)).fetchone()
    return {"id": row["id"], "chain_args": {"bounty_id": row["id"], "reward_lamports": lamports, "deadline": unix,
            "rules_commitment": rules_c, "region_commitment": region_c, "reviewers": body.reviewers, "threshold": body.threshold}}


@router.get("/{bid}")
def get_bounty(bid: int, conn=Depends(get_conn)):
    ensure(conn)
    row = _load(conn, bid)
    if row["status"] == "draft":
        raise HTTPException(404, "no such bounty")
    if row["status"] in ("created", "funded"):  # settled accounts cannot change, so skip the RPC for them
        try:
            row = refresh(conn, row)
        except Exception:
            pass  # devnet unreachable: serve the cached copy
    return public(row, _count(conn, bid))


@router.post("/{bid}/sync")
def sync(bid: int, body: Sync, conn=Depends(get_conn)):
    """Record a confirmed transaction and refresh from the chain. Safe to retry: signatures are unique."""
    ensure(conn)
    if body.kind not in TX_KINDS or not chain.is_signature(body.signature):
        raise HTTPException(400, "bad signature or kind")
    row = _load(conn, bid)
    pda = row["pda"] or body.pda
    if not pda or not chain.is_wallet(pda):
        raise HTTPException(400, "bounty account address required on first sync")
    for attempt in range(6):  # a just-confirmed transaction can take a moment to appear in getTransaction
        if chain.confirmed_tx_touching(body.signature, pda):
            break
        time.sleep(1)
    else:
        raise HTTPException(400, "transaction not confirmed on devnet for this bounty")
    row = refresh(conn, row, pda)
    conn.execute("INSERT INTO bounty.tx (signature, bounty_id, kind) VALUES (%s, %s, %s) ON CONFLICT (signature) DO NOTHING",
                 (body.signature, bid, body.kind))
    return public(row, _count(conn, bid))


@router.get("/{bid}/transactions")
def transactions(bid: int, conn=Depends(get_conn)):
    ensure(conn)
    rows = conn.execute("SELECT signature, kind, created_at FROM bounty.tx WHERE bounty_id = %s ORDER BY created_at", (bid,)).fetchall()
    return [{**r, "explorer": chain.explorer("tx", r["signature"])} for r in rows]


@router.post("/{bid}/submissions")
async def submit(bid: int, wallet: str = Form(...), email: str = Form(..., max_length=254), summary: str = Form("", max_length=2000),
                 details: str = Form("", max_length=5000), location: str = Form("", max_length=300),
                 file: UploadFile | None = File(None), conn=Depends(get_conn)):
    """A claim (payout address + email, optionally evidence). It stays here; only its SHA-256 commitment may reach the chain."""
    wallet, email = wallet.strip(), email.strip().lower()
    ensure(conn)
    row = _load(conn, bid)
    if row["status"] != "funded" or row["deadline"] < datetime.now(timezone.utc):
        raise HTTPException(400, "bounty is not open for submissions")
    if not chain.is_wallet(wallet):
        raise HTTPException(400, "wallet must be a Solana address")
    if not EMAIL.match(email):
        raise HTTPException(400, "enter a valid email address")
    if file and file.filename and file.content_type not in EVIDENCE_TYPES:
        raise HTTPException(415, "evidence must be a photo (jpeg, png, webp, heic), pdf, or text file")
    blob = await file.read(MAX_EVIDENCE_BYTES + 1) if file and file.filename else None
    if blob is not None and len(blob) > MAX_EVIDENCE_BYTES:
        raise HTTPException(413, "evidence file is larger than 5 MB")
    file_sha = hashlib.sha256(blob).hexdigest() if blob is not None else None
    c = chain.commitment({"bounty": bid, "wallet": wallet, "email": email, "summary": summary, "details": details,
                          "location": location, "file_sha256": file_sha}).hex()
    got = conn.execute(
        """INSERT INTO bounty.submission (bounty_id, wallet, email, summary, details, location, file_name, file_type, file_sha256, evidence, commitment)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (bounty_id, commitment) DO NOTHING RETURNING id""",
        (bid, wallet, email, summary, details or None, location or None, file.filename if blob is not None else None,
         file.content_type if blob is not None else None, file_sha, blob, c)).fetchone()
    if got:
        return {"id": got["id"], "commitment": c, "duplicate": False}
    same = conn.execute("SELECT id FROM bounty.submission WHERE bounty_id = %s AND commitment = %s", (bid, c)).fetchone()
    return {"id": same["id"], "commitment": c, "duplicate": True}


def review_message(bid: int, wallet: str, issued: int) -> str:
    return f"Crewly bounty review access. bounty={bid} wallet={wallet} issued={issued}"


def reviewer(bid: int, conn=Depends(get_conn), x_bounty_wallet: str = Header(""), x_bounty_issued: int = Header(0),
             x_bounty_signature: str = Header("")):
    """A reviewer proves wallet ownership by signing `review_message`; the signature is good for ten minutes."""
    ensure(conn)
    row = _load(conn, bid)
    if abs(time.time() - x_bounty_issued) > REVIEW_TOKEN_TTL_S:
        raise HTTPException(401, "review signature expired, sign again")
    if x_bounty_wallet not in row["reviewers"]:
        raise HTTPException(403, "this wallet is not a reviewer for this bounty")
    if not chain.verify_wallet_signature(x_bounty_wallet, review_message(bid, x_bounty_wallet, x_bounty_issued), x_bounty_signature):
        raise HTTPException(401, "bad wallet signature")
    return row


@router.get("/{bid}/submissions")
def submissions(bid: int, row=Depends(reviewer), conn=Depends(get_conn)):
    rows = conn.execute(
        """SELECT id, wallet, email, summary, details, location, file_name, file_type, file_sha256, commitment, created_at
           FROM bounty.submission WHERE bounty_id = %s ORDER BY created_at""", (bid,)).fetchall()
    return [{**r, "approved": r["commitment"] == row["submission_commitment"]} for r in rows]


@router.get("/{bid}/submissions/{sid}/evidence")
def evidence(bid: int, sid: int, row=Depends(reviewer), conn=Depends(get_conn)):
    r = conn.execute("SELECT evidence, file_type FROM bounty.submission WHERE id = %s AND bounty_id = %s", (sid, bid)).fetchone()
    if not r or r["evidence"] is None:
        raise HTTPException(404, "no evidence file")
    return Response(bytes(r["evidence"]), media_type=r["file_type"] or "application/octet-stream",
                    headers={"Cache-Control": "no-store", "Content-Disposition": "attachment", "X-Content-Type-Options": "nosniff"})
