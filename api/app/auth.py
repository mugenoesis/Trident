"""Session auth: password hashing + signed session cookies.

Deliberately dependency-free (stdlib hashlib/hmac/secrets only), matching
this project's existing minimal-deps style (raw sqlite3, no ORM,
regex-fallback settings parsing) -- no passlib/bcrypt, no itsdangerous or
Starlette SessionMiddleware.

require_user() is the FastAPI dependency every user-owned endpoint uses (API keys: see _key_user):
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

from .userstore import User
from .userstore import store as user_store

SESSION_COOKIE_NAME = "orca_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

_PBKDF2_ITERATIONS = 310_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _PBKDF2_ITERATIONS).hex()
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


def _session_user(request: Request) -> User:
    if user_store.get_auth_mode() != "multi":
        return user_store.get_or_create_local_user()
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user_id = verify_session_cookie(token) if token else None
    user = user_store.get_user(user_id) if user_id else None
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _key_user(request: Request, scopes: tuple[str, ...]) -> User | None:
    """The user an `Authorization: Bearer <key>` header stands for, or None when the request has no such header.

    A key that is sent must be a good one, even when nothing needs a login: a mistyped key should say so rather
    than be ignored. A good key whose access is too small for this endpoint is a 403.
    """
    header = request.headers.get("authorization", "")
    scheme, _, secret = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    found = user_store.resolve_api_key(secret.strip()) if secret.strip() else None
    if found is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    key, user = found
    if key.scope not in scopes:
        raise HTTPException(status_code=403, detail="This API key is not allowed to do that")
    return user


def require_user(request: Request) -> User:
    """A signed-in user (or the implicit one with no login), or the user of a full-access API key."""
    return _key_user(request, ("full",)) or _session_user(request)


def require_upload_user(request: Request) -> User:
    """Like require_user, and also accepts an upload-only API key (the endpoint that key is for) and a resin-tools key."""
    return _key_user(request, ("full", "upload", "resin")) or _session_user(request)


def require_resin_tools_user(request: Request) -> User:
    """Like require_user, and also accepts a resin-tools API key (Holecraft's Hollow and support editing: it may upload a model, hollow it and place supports on it, nothing else)."""
    return _key_user(request, ("full", "resin")) or _session_user(request)


def require_session_user(request: Request) -> User:
    """A signed-in user only (never an API key): for managing API keys themselves."""
    return _session_user(request)
