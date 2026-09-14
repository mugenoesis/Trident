"""Session auth: password hashing + signed session cookies.

Deliberately dependency-free (stdlib hashlib/hmac/secrets only), matching
this project's existing minimal-deps style (raw sqlite3, no ORM,
regex-fallback settings parsing) -- no passlib/bcrypt, no itsdangerous or
Starlette SessionMiddleware.

require_user() is the FastAPI dependency every user-owned endpoint uses:
  - "unset"/"single" mode: always resolves to one implicit local user, no
    cookie involved -- there's nothing to log into.
  - "multi" mode: reads a signed session cookie, 401s if missing/invalid.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException, Request

from .userstore import User, store as user_store

SESSION_COOKIE_NAME = "orca_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

_PBKDF2_ITERATIONS = 310_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), _PBKDF2_ITERATIONS
    ).hex()
    return f"{_PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        iterations_s, salt, digest = stored.split("$")
        salt_bytes = bytes.fromhex(salt)
        digest_bytes = bytes.fromhex(digest)
    except (ValueError, AttributeError):
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt_bytes, int(iterations_s))
    return hmac.compare_digest(candidate, digest_bytes)


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def create_session_cookie(user_id: str) -> str:
    expires = int(time.time()) + SESSION_MAX_AGE
    payload = f"{user_id}.{expires}"
    return f"{payload}.{_sign(user_store.get_secret_key(), payload)}"


def verify_session_cookie(value: str) -> str | None:
    parts = value.split(".")
    if len(parts) != 3:
        return None
    user_id, expires_s, sig = parts
    payload = f"{user_id}.{expires_s}"
    if not hmac.compare_digest(sig, _sign(user_store.get_secret_key(), payload)):
        return None
    if not expires_s.isdigit() or int(expires_s) < time.time():
        return None
    return user_id


def require_user(request: Request) -> User:
    if user_store.get_auth_mode() != "multi":
        return user_store.get_or_create_local_user()
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user_id = verify_session_cookie(token) if token else None
    user = user_store.get_user(user_id) if user_id else None
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
