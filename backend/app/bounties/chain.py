"""The on-chain side: base58, commitments, wallet signatures, and reading bounty accounts over devnet RPC."""
import base64
import hashlib
import json
import os
import struct

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

CLUSTER = "devnet"  # mainnet is out of scope; everything below assumes devnet
RPC_URL = os.environ.get("SOLANA_RPC_URL", "https://api.devnet.solana.com")
PROGRAM_ID = os.environ.get("SOLANA_PROGRAM_ID") or "4jcrRV3ab8boiXDF6YHdmRu9YwMLzonjuAK9pFSyFZPF"  # solana/Anchor.toml
LAMPORTS_PER_SOL = 1_000_000_000
STATUSES = ["created", "funded", "paid", "refunded"]  # BountyStatus enum order in the program
ACCOUNT_DISCRIMINATOR = hashlib.sha256(b"account:Bounty").digest()[:8]

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(raw: bytes) -> str:
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + out


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        i = _B58.find(ch)
        if i < 0:
            raise ValueError("not base58")
        n = n * 58 + i
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\0" * (len(s) - len(s.lstrip("1"))) + body


def is_wallet(s) -> bool:
    try:
        return isinstance(s, str) and len(b58decode(s)) == 32
    except ValueError:
        return False


def is_signature(s) -> bool:
    try:
        return isinstance(s, str) and len(b58decode(s)) == 64
    except ValueError:
        return False


def commitment(obj) -> bytes:
    """SHA-256 over canonical JSON, the only form of private data that goes on-chain."""
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).digest()


def verify_wallet_signature(wallet: str, message: str, signature_b58: str) -> bool:
    """True when `wallet` signed `message` (the wallet-standard signMessage output)."""
    try:
        Ed25519PublicKey.from_public_bytes(b58decode(wallet)).verify(b58decode(signature_b58), message.encode())
        return True
    except (ValueError, InvalidSignature):
        return False


def decode_bounty(data: bytes) -> dict:
    """Decode the Anchor `Bounty` account (layout in solana/programs/crewly_bounty/src/lib.rs)."""
    if data[:8] != ACCOUNT_DISCRIMINATOR:
        raise ValueError("not a Bounty account")
    o = 8

    def take(n):
        nonlocal o
        o += n
        return data[o - n:o]

    sponsor = b58encode(take(32))
    bounty_id, reward, deadline = struct.unpack("<QQq", take(24))
    rules, region = take(32).hex(), take(32).hex()
    (n,) = struct.unpack("<I", take(4))
    reviewers = [b58encode(take(32)) for _ in range(n)]
    threshold, approvals = take(1)[0], take(1)[0]
    submission = take(32)
    contributor = take(32)
    status = STATUSES[take(1)[0]]
    created_at, funded_at, settled_at = struct.unpack("<qqq", take(24))
    return {
        "sponsor": sponsor, "bounty_id": bounty_id, "reward_lamports": reward, "deadline": deadline,
        "rules_commitment": rules, "region_commitment": region, "reviewers": reviewers, "threshold": threshold,
        "approved_by": [r for i, r in enumerate(reviewers) if approvals >> i & 1],
        "submission_commitment": submission.hex() if any(submission) else None,
        "contributor": b58encode(contributor) if any(contributor) else None,
        "status": status, "created_at": created_at, "funded_at": funded_at or None, "settled_at": settled_at or None,
    }


def _rpc(method, params):
    r = httpx.post(RPC_URL, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=15)
    r.raise_for_status()
    body = r.json()
    if "error" in body:
        raise RuntimeError(body["error"].get("message", "rpc error"))
    return body["result"]


def fetch_bounty(address: str):
    """The decoded account, or None when it does not exist or is not owned by our program."""
    value = _rpc("getAccountInfo", [address, {"encoding": "base64", "commitment": "confirmed"}])["value"]
    if not value or value["owner"] != PROGRAM_ID:
        return None
    return decode_bounty(base64.b64decode(value["data"][0]))


def confirmed_tx_touching(signature: str, address: str) -> bool:
    """True when the transaction confirmed without error and referenced `address`."""
    tx = _rpc("getTransaction", [signature, {"encoding": "json", "commitment": "confirmed", "maxSupportedTransactionVersion": 0}])
    if not tx or tx["meta"]["err"] is not None:
        return False
    keys = tx["transaction"]["message"]["accountKeys"]
    return address in keys


def explorer(kind: str, value: str) -> str:
    return f"https://explorer.solana.com/{kind}/{value}?cluster={CLUSTER}"
