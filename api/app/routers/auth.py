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
from ..jobstore import store as job_store
from ..printerstore import store as printer_store
from ..schemas import (
    AuthSetupRequest,
    AuthStatus,
    LastSelectionRequest,
    LoginRequest,
    SwitchToMultiRequest,
    UserCreateRequest,
)
from ..userstore import LOCAL_USER_ID, User, store as user_store
from .models import reassign_all_models_to_user

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session(response: Response, user_id: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_cookie(user_id),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )


def _status(mode: str, user: User | None) -> AuthStatus:
    if user is None:
        return AuthStatus(mode=mode, logged_in=False)
    return AuthStatus(
        mode=mode,
        logged_in=True,
        username=user.username,
        last_printer_id=user.last_printer_id,
        last_material_id=user.last_material_id,
        last_settings_profile_id=user.last_settings_profile_id,
    )


@router.get("/status", response_model=AuthStatus)
def auth_status(request: Request) -> AuthStatus:
    mode = user_store.get_auth_mode()
    if mode != "multi":
        # Nothing to log into yet, but make sure the implicit row exists so
        # anything that stamps user_id="local" has a real row to point at.
        user = user_store.get_or_create_local_user()
        return _status(mode, user)

    token = request.cookies.get(SESSION_COOKIE_NAME)
    user_id = verify_session_cookie(token) if token else None
    user = user_store.get_user(user_id) if user_id else None
    return _status("multi", user)


@router.post("/setup", response_model=AuthStatus)
def setup(body: AuthSetupRequest, response: Response) -> AuthStatus:
    if user_store.get_auth_mode() != "unset":
        raise HTTPException(status_code=409, detail="Already set up")

    if body.mode == "single":
        user = user_store.get_or_create_local_user()
        user_store.set_auth_mode("single")
        return _status("single", user)

    if body.mode != "multi":
        raise HTTPException(status_code=400, detail="mode must be 'single' or 'multi'")
    if not body.username or not body.password:
        raise HTTPException(status_code=400, detail="username and password are required")

    user = user_store.create_user(username=body.username, password_hash=hash_password(body.password))
    user_store.set_auth_mode("multi")
    _set_session(response, user.id)
    return _status("multi", user)


@router.post("/switch-to-multi", response_model=AuthStatus)
def switch_to_multi(body: SwitchToMultiRequest, response: Response) -> AuthStatus:
    if user_store.get_auth_mode() != "single":
        raise HTTPException(status_code=409, detail="Not in single-user mode")
    if not body.username or not body.password:
        raise HTTPException(status_code=400, detail="username and password are required")

    # Sets credentials directly on the existing local-user row rather than
    # migrating data to a new id -- that row already owns everything
    # created while in single-user mode (including its last_printer_id/
    # last_material_id/last_settings_profile_id, which carry over unchanged
    # since it's the same row).
    local = user_store.get_or_create_local_user()
    user_store.set_credentials(local.id, username=body.username, password_hash=hash_password(body.password))
    user_store.set_auth_mode("multi")
    _set_session(response, local.id)
    updated = user_store.get_user(local.id)
    assert updated is not None
    return _status("multi", updated)


@router.post("/login", response_model=AuthStatus)
def login(body: LoginRequest, response: Response) -> AuthStatus:
    if user_store.get_auth_mode() != "multi":
        raise HTTPException(status_code=400, detail="Not in multi-user mode")
    found = user_store.get_user_by_username(body.username)
    if not found or not verify_password(body.password, found[1]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    user, _password_hash = found
    _set_session(response, user.id)
    return _status("multi", user)


@router.post("/switch-to-single", response_model=AuthStatus)
def switch_to_single(response: Response, current: User = Depends(require_user)) -> AuthStatus:
    """The reverse of switch-to-multi: destructive in that every account's
    identity (and password) is gone afterward, but no data is lost -- every
    job/model/printer/material-profile, regardless of which account owned
    it, is merged onto the single implicit local user (which is exactly
    what single-user mode already looks like, since it never filters by
    owner). Any logged-in user can trigger this -- there's no admin role
    in multi-user mode, everyone's equal."""
    if user_store.get_auth_mode() != "multi":
        raise HTTPException(status_code=409, detail="Not in multi-user mode")

    job_store.reassign_all_to_user(LOCAL_USER_ID)
    printer_store.reassign_all_to_user(LOCAL_USER_ID)
    reassign_all_models_to_user(LOCAL_USER_ID)
    user_store.collapse_to_single_user()

    response.delete_cookie(SESSION_COOKIE_NAME)
    local = user_store.get_user(LOCAL_USER_ID)
    return _status("single", local)


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"ok": True}


@router.put("/last-selection", response_model=AuthStatus)
def update_last_selection(body: LastSelectionRequest, current: User = Depends(require_user)) -> AuthStatus:
    """Remembers the printer/material/settings profile last selected, so
    App.tsx can restore them as the default next time this account opens
    the site."""
    user_store.set_last_selection(
        current.id,
        printer_id=body.printer_id,
        material_id=body.material_id,
        settings_profile_id=body.settings_profile_id,
    )
    updated = user_store.get_user(current.id)
    assert updated is not None
    return _status(user_store.get_auth_mode(), updated)


@router.post("/users", response_model=AuthStatus)
def create_user(body: UserCreateRequest, current: User = Depends(require_user)) -> AuthStatus:
    if user_store.get_auth_mode() != "multi":
        raise HTTPException(status_code=400, detail="Not in multi-user mode")
    if user_store.get_user_by_username(body.username):
        raise HTTPException(status_code=409, detail="Username already taken")
    user_store.create_user(username=body.username, password_hash=hash_password(body.password))
    # Adds a new account; the caller stays logged in as themself.
    return _status("multi", current)
