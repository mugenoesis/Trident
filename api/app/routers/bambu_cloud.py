"""EXPERIMENT: the Bambu Cloud sign-in test (see app/bambu_cloud.py). Everything but the status is a 404 unless ORCA_API_EXPERIMENTAL_BAMBU_CLOUD is on."""

from __future__ import annotations

import html
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from .. import bambu_cloud
from ..auth import require_user
from ..config import settings
from ..userstore import User

router = APIRouter(prefix="/bambu-cloud", tags=["bambu-cloud (experimental)"])


def _plugin_folder():
    return settings.orcaslicer_datadir / "bambu-plugin"


def _require_enabled() -> None:
    if not settings.experimental_bambu_cloud:
        raise HTTPException(status_code=404, detail="Not found")


@router.get("")
def status(current: User = Depends(require_user)) -> dict[str, Any]:
    """Whether the experiment is on, and whether Bambu's plug-in is installed (the page shows nothing when it is off)."""
    if not settings.experimental_bambu_cloud:
        return {"enabled": False}
    return {
        "enabled": True,
        "plugin": bambu_cloud.plugin_status(_plugin_folder()),
        "callback": bambu_cloud.last_callback(),
    }


@router.post("/plugin")
async def install_plugin(current: User = Depends(require_user)) -> dict[str, Any]:
    """Download Bambu's network plug-in from Bambu (the user asked for it) and report its version and SHA-256."""
    _require_enabled()
    try:
        return await bambu_cloud.install_plugin(_plugin_folder())
    except bambu_cloud.BambuCloudError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/sign-in-url")
def sign_in_url(origin: str, current: User = Depends(require_user)) -> dict[str, str]:
    """The link to Bambu's sign-in page that sends the browser back here; `origin` is the address the browser uses for Trident."""
    _require_enabled()
    try:
        return {"url": bambu_cloud.sign_in_url(origin)}
    except bambu_cloud.BambuCloudError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/callback", response_class=HTMLResponse)
@router.get("/callback/{rest:path}", response_class=HTMLResponse)
def callback(request: Request, current: User = Depends(require_user), rest: str = "") -> str:
    """Where Bambu's sign-in sends the browser back to. It records what arrived (names and lengths only) and shows the same."""
    _require_enabled()
    bambu_cloud.record_callback(request.url.path, dict(request.query_params))
    seen = bambu_cloud.last_callback() or {"fields": []}
    names = (
        "".join(f"<li>{html.escape(f['name'])} ({f['length']} characters)</li>" for f in seen["fields"])
        or "<li>nothing</li>"
    )
    return f"<h3>Bambu sent the browser back to Trident</h3><p>It carried:</p><ul>{names}</ul><p>You can close this tab.</p>"
