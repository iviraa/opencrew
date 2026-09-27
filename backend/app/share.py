"""Signed, expiring links that show a report, finding or plan to someone without a login, and the files Crewly exports."""
import base64
import hashlib
import hmac
import os
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response

from app.auth import current_user
from app.db import get_conn

KINDS = ("report", "finding", "plan")
TABLE_SQL = """
CREATE TABLE IF NOT EXISTS share (
  id         SERIAL PRIMARY KEY,
  token_hash TEXT NOT NULL UNIQUE,
  kind       TEXT NOT NULL,
  ref_id     TEXT NOT NULL,
  company_id TEXT NOT NULL,
  title      TEXT,
  expires_at TIMESTAMPTZ NOT NULL,
  revoked    BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS export (
  id         SERIAL PRIMARY KEY,
  company_id TEXT NOT NULL,
  kind       TEXT NOT NULL,
  format     TEXT NOT NULL,
  filename   TEXT NOT NULL,
  media_type TEXT NOT NULL,
  bytes      BYTEA NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def secret():
    return (os.environ.get("SHARE_SECRET") or os.environ.get("SUPABASE_SECRET_KEY") or "crewly-dev").encode()


def _b64(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign(kind, ref_id, company, expires_at):
    """token = payload.signature; the payload says what it opens and until when, the signature says we issued it."""
    payload = f"{kind}:{ref_id}:{company}:{int(expires_at)}".encode()
    sig = hmac.new(secret(), payload, hashlib.sha256).digest()[:20]
    return f"{_b64(payload)}.{_b64(sig)}"


def verify(token, now=None):
    """The payload fields for a valid, unexpired token, else None."""
    try:
        p64, s64 = token.split(".", 1)
        payload, sig = _unb64(p64), _unb64(s64)
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(hmac.new(secret(), payload, hashlib.sha256).digest()[:20], sig):
        return None
    try:
        kind, ref_id, company, exp = payload.decode().split(":", 3)
    except ValueError:
        return None
    if kind not in KINDS or int(exp) < (now or time.time()):
        return None
    return {"kind": kind, "ref_id": ref_id, "company": company, "expires_at": int(exp)}


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create(conn, company, kind, ref_id, title, expires_days=7):
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    days = max(1, min(int(expires_days or 7), 90))
    exp = time.time() + days * 86400
    token = sign(kind, str(ref_id), company, exp)
    conn.execute(TABLE_SQL)
    row = conn.execute("INSERT INTO share (token_hash, kind, ref_id, company_id, title, expires_at) VALUES (%s, %s, %s, %s, %s, to_timestamp(%s)) RETURNING id, expires_at",
                       (token_hash(token), kind, str(ref_id), company, title, exp)).fetchone()
    return {"id": row["id"], "token": token, "path": f"/share/{token}", "kind": kind, "ref_id": str(ref_id), "title": title, "expires_at": row["expires_at"].isoformat(), "days": days}


def render(conn, claims):
    """The same HTML the logged-in report route shows, for the object a token names; None when it is gone or not shareable."""
    from app.crewly import reports
    kind, ref, company = claims["kind"], claims["ref_id"], claims["company"]
    if kind == "report":
        row = reports.get(conn, ref, company) if ref.isdigit() else None
        return row and row["html"]
    try:
        return reports.render(conn, company, "finding" if kind == "finding" else "plan", ref if kind == "finding" else (ref or None), f"{reports.name(company)} · shared by crewly")
    except ValueError:
        return None


router = APIRouter()
NOT_HERE = "<!doctype html><meta charset='utf-8'><title>crewly</title><body style='font:15px sans-serif;margin:48px auto;max-width:520px'><h2>This link is not available</h2><p>It may have expired or been revoked by the utility that shared it.</p></body>"


@router.get("/share/{token}", response_class=HTMLResponse, include_in_schema=False)
def open_share(token: str, conn=Depends(get_conn)):
    claims = verify(token)
    if not claims:
        return HTMLResponse(NOT_HERE, status_code=404)
    conn.execute(TABLE_SQL)
    row = conn.execute("SELECT revoked FROM share WHERE token_hash = %s", (token_hash(token),)).fetchone()
    if not row or row["revoked"]:
        return HTMLResponse(NOT_HERE, status_code=404)
    html = render(conn, claims)
    if not html:
        return HTMLResponse(NOT_HERE, status_code=404)
    return HTMLResponse(html, headers={"X-Robots-Tag": "noindex", "Cache-Control": "no-store"})


@router.get("/api/app/shares")
def list_shares(user=Depends(current_user), conn=Depends(get_conn)):
    conn.execute(TABLE_SQL)
    return conn.execute("SELECT id, kind, ref_id, title, expires_at, revoked, created_at FROM share WHERE company_id = %s ORDER BY id DESC LIMIT 50", (user["company"],)).fetchall()


@router.delete("/api/app/share/{share_id}")
def revoke_share(share_id: int, user=Depends(current_user), conn=Depends(get_conn)):
    conn.execute(TABLE_SQL)
    row = conn.execute("UPDATE share SET revoked = TRUE WHERE id = %s AND company_id = %s RETURNING id", (share_id, user["company"])).fetchone()
    if not row:
        raise HTTPException(404, "share not found")
    return {"id": share_id, "revoked": True}


@router.get("/api/app/export/{export_id}")
def download_export(export_id: int, user=Depends(current_user), conn=Depends(get_conn)):
    conn.execute(TABLE_SQL)
    row = conn.execute("SELECT filename, media_type, bytes FROM export WHERE id = %s AND company_id = %s", (export_id, user["company"])).fetchone()
    if not row:
        raise HTTPException(404, "export not found")
    return Response(bytes(row["bytes"]), media_type=row["media_type"], headers={"Content-Disposition": f'attachment; filename="{row["filename"]}"'})
