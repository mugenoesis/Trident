from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..auth import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE,
    create_session_cookie,
    hash_password,
    require_user,
    verify_password,
    verify_session_cookie,
)
from ..schemas import (
    AuthSetupRequest,
    AuthStatus,
    LoginRequest,
    SwitchToMultiRequest,
    UserCreateRequest,
)
from ..userstore import User, store as user_store

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session(response: Response, user_id: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_cookie(user_id),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )


@router.get("/status", response_model=AuthStatus)
def auth_status(request: Request) -> AuthStatus:
    mode = user_store.get_auth_mode()
    if mode != "multi":
        # Nothing to log into yet, but make sure the implicit row exists so
        # anything that stamps user_id="local" has a real row to point at.
        user_store.get_or_create_local_user()
        return AuthStatus(mode=mode, logged_in=True, username=None)

    token = request.cookies.get(SESSION_COOKIE_NAME)
    user_id = verify_session_cookie(token) if token else None
    user = user_store.get_user(user_id) if user_id else None
    return AuthStatus(mode="multi", logged_in=user is not None, username=user.username if user else None)


@router.post("/setup", response_model=AuthStatus)
def setup(body: AuthSetupRequest, response: Response) -> AuthStatus:
    if user_store.get_auth_mode() != "unset":
        raise HTTPException(status_code=409, detail="Already set up")

    if body.mode == "single":
        user_store.get_or_create_local_user()
        user_store.set_auth_mode("single")
        return AuthStatus(mode="single", logged_in=True, username=None)

    if body.mode != "multi":
        raise HTTPException(status_code=400, detail="mode must be 'single' or 'multi'")
    if not body.username or not body.password:
        raise HTTPException(status_code=400, detail="username and password are required")

    user = user_store.create_user(username=body.username, password_hash=hash_password(body.password))
    user_store.set_auth_mode("multi")
    _set_session(response, user.id)
    return AuthStatus(mode="multi", logged_in=True, username=user.username)


@router.post("/switch-to-multi", response_model=AuthStatus)
def switch_to_multi(body: SwitchToMultiRequest, response: Response) -> AuthStatus:
    if user_store.get_auth_mode() != "single":
        raise HTTPException(status_code=409, detail="Not in single-user mode")
    if not body.username or not body.password:
        raise HTTPException(status_code=400, detail="username and password are required")

    # Sets credentials directly on the existing local-user row rather than
    # migrating data to a new id -- that row already owns everything
    # created while in single-user mode.
    local = user_store.get_or_create_local_user()
    user_store.set_credentials(local.id, username=body.username, password_hash=hash_password(body.password))
    user_store.set_auth_mode("multi")
    _set_session(response, local.id)
    return AuthStatus(mode="multi", logged_in=True, username=body.username)


@router.post("/login", response_model=AuthStatus)
def login(body: LoginRequest, response: Response) -> AuthStatus:
    if user_store.get_auth_mode() != "multi":
        raise HTTPException(status_code=400, detail="Not in multi-user mode")
    found = user_store.get_user_by_username(body.username)
    if not found or not verify_password(body.password, found[1]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    user, _password_hash = found
    _set_session(response, user.id)
    return AuthStatus(mode="multi", logged_in=True, username=user.username)


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"ok": True}


@router.post("/users", response_model=AuthStatus)
def create_user(body: UserCreateRequest, current: User = Depends(require_user)) -> AuthStatus:
    if user_store.get_auth_mode() != "multi":
        raise HTTPException(status_code=400, detail="Not in multi-user mode")
    if user_store.get_user_by_username(body.username):
        raise HTTPException(status_code=409, detail="Username already taken")
    user_store.create_user(username=body.username, password_hash=hash_password(body.password))
    # Adds a new account; the caller stays logged in as themself.
    return AuthStatus(mode="multi", logged_in=True, username=current.username)
