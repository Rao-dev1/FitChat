"""Who is making this request?

* AUTH_MODE=none (laptop use): everyone is the single local user, exactly like before accounts existed.
* AUTH_MODE=supabase (hosted): the browser sends the Supabase access token; we ask Supabase who it belongs to.
  We never trust anything the browser says about identity except that token.
"""
import hashlib
import logging
import time
from dataclasses import dataclass

import httpx
from fastapi import HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from . import clock
from .config import get_settings

log = logging.getLogger("fitchat.auth")

TOKEN_TTL_S = 60  # re-check a token with Supabase at most once a minute per instance
_cache: dict[str, tuple[float, "AuthUser"]] = {}


@dataclass(frozen=True)
class AuthUser:
    uid: str
    email: str | None
    is_admin: bool


LOCAL_USER = AuthUser("local", None, True)


def admin_emails() -> set[str]:
    return {e.strip().lower() for e in get_settings().admin_emails.split(",") if e.strip()}


def _fetch_user(token: str) -> dict | None:
    """Ask Supabase who this token belongs to. None = invalid/expired. Separate function so tests can stub it."""
    s = get_settings()
    r = httpx.get(f"{s.supabase_url.rstrip('/')}/auth/v1/user", timeout=8,
                  headers={"apikey": s.supabase_anon_key, "Authorization": f"Bearer {token}"})
    if r.status_code == 200:
        return r.json()
    if r.status_code in (400, 401, 403):
        return None
    raise RuntimeError(f"auth service answered {r.status_code}")


def _user_from_token(token: str) -> AuthUser | None:
    key = hashlib.sha256(token.encode()).hexdigest()
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    data = _fetch_user(token)
    if not data or not data.get("id"):
        _cache.pop(key, None)
        return None
    email = (data.get("email") or "").lower() or None
    # Admin only for a CONFIRMED address, so nobody can claim yours by signing up with it first.
    confirmed = bool(data.get("email_confirmed_at") or data.get("confirmed_at"))
    user = AuthUser(str(data["id"]), email, bool(email and confirmed and email in admin_emails()))
    if len(_cache) > 2000:
        _cache.clear()
    _cache[key] = (time.monotonic() + TOKEN_TTL_S, user)
    return user


async def current_user(request: Request) -> AuthUser:
    # async on purpose: values set here (the caller's time zone) are visible to the endpoint that runs next.
    clock.set_tz(request.headers.get("x-tz"))
    s = get_settings()
    if s.auth_mode != "supabase":
        return LOCAL_USER
    if not (s.supabase_url and s.supabase_anon_key):
        raise HTTPException(503, "Sign-in is not configured on this server.")
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not token:
        raise HTTPException(401, "Please sign in.")
    try:
        user = await run_in_threadpool(_user_from_token, token)
    except Exception as e:  # network trouble, Supabase down
        log.error("auth service unavailable: %s", e)
        raise HTTPException(503, "Sign-in service is unavailable right now. Try again in a minute.")
    if user is None:
        raise HTTPException(401, "Your session expired. Please sign in again.")
    return user
