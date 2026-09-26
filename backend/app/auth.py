"""Supabase logins: the browser sends its access token, we check it and read the company from app_metadata."""
import os
import time
from functools import lru_cache

import httpx
import jwt
from fastapi import Header, HTTPException

from app.companies import companies

_seen: dict[str, tuple[float, dict]] = {}  # token -> (expires, claims) for projects that still sign with a shared secret


def supabase_url():
    return os.environ["SUPABASE_URL"].rstrip("/")


@lru_cache
def _jwks():
    return jwt.PyJWKClient(f"{supabase_url()}/auth/v1/.well-known/jwks.json", cache_keys=True, lifespan=3600)


def _claims(token):
    try:
        key = _jwks().get_signing_key_from_jwt(token)
        return jwt.decode(token, key.key, algorithms=["ES256", "RS256"], audience="authenticated")
    except jwt.PyJWKClientError:  # no public key for this token: ask auth directly
        hit = _seen.get(token)
        if hit and hit[0] > time.time():
            return hit[1]
        r = httpx.get(f"{supabase_url()}/auth/v1/user", timeout=10,
                      headers={"apikey": os.environ["SUPABASE_PUBLISHABLE_KEY"], "Authorization": f"Bearer {token}"})
        if r.status_code != 200:
            raise jwt.InvalidTokenError("session expired")
        u = r.json()
        claims = {"sub": u["id"], "app_metadata": u.get("app_metadata") or {}, "user_metadata": u.get("user_metadata") or {}}
        _seen[token] = (time.time() + 60, claims)
        return claims


def current_user(authorization: str | None = Header(None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "log in first")
    token = authorization[7:]
    try:
        claims = _claims(token)
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"please log in again ({e})")
    company = (claims.get("app_metadata") or {}).get("company_id")
    if company not in companies() and company not in companies(fresh=True):  # a utility added since the last refresh
        raise HTTPException(403, "this login is not linked to a company")
    return {"id": claims["sub"], "company": company,
            "username": (claims.get("user_metadata") or {}).get("username"), "token": token}
