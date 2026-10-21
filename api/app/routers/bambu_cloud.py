"""EXPERIMENT: the Bambu Cloud sign-in and importing a Bambu account's printers (see app/bambu_cloud.py). Everything but the status is a 404
unless ORCA_API_EXPERIMENTAL_BAMBU_CLOUD is on."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import bambu_cloud, bambu_discovery, bambu_import
from .. import profiles as profiles_module
from ..auth import require_user
from ..config import settings
from ..printerstore import store
from ..userstore import User

router = APIRouter(prefix="/bambu-cloud", tags=["bambu-cloud (experimental)"])


def _plugin_folder() -> Path:
    return settings.orcaslicer_datadir / "bambu-plugin"


def _require_enabled() -> None:
    if not settings.experimental_bambu_cloud:
        raise HTTPException(status_code=404, detail="Not found")


@router.get("")
def status(current: User = Depends(require_user)) -> dict[str, Any]:
    """Whether the experiment is on, and whether Bambu's plug-in is installed (the page shows nothing when it is off)."""
    if not settings.experimental_bambu_cloud:
        return {"enabled": False}
    return {"enabled": True, "plugin": bambu_cloud.plugin_status(_plugin_folder())}


@router.post("/plugin")
async def install_plugin(current: User = Depends(require_user)) -> dict[str, Any]:
    """Download Bambu's network plug-in from Bambu (the user asked for it) and report its version and SHA-256."""
    _require_enabled()
    try:
        return await bambu_cloud.install_plugin(_plugin_folder())
    except bambu_cloud.BambuCloudError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/sign-in-url")
def sign_in_url(current: User = Depends(require_user)) -> dict[str, str]:
    """The link to Bambu's own sign-in page, to open in the user's browser."""
    _require_enabled()
    return {"url": bambu_cloud.sign_in_url()}


class AccountRequest(BaseModel):
    url: str = Field(max_length=4000)
    # The network to look for the printers on; by default the /24 around the address the page was opened from.
    network: str | None = Field(default=None, max_length=64)


def _checked(network: str) -> str:
    """A network the user named, if it may be searched (private and small); a 400 in words if not."""
    try:
        bambu_discovery.hosts_of(network)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return network.strip()


def _network(body: AccountRequest, request: Request) -> str | None:
    if body.network:
        return _checked(body.network)
    return bambu_discovery.network_of(request.url.hostname or "")


@router.post("/account")
async def account(body: AccountRequest, request: Request, current: User = Depends(require_user)) -> dict[str, Any]:
    """Give the address the browser ended up on to Bambu's plug-in, and list the account's printers with where they were found.

    The answer is a plain one even when the plug-in fails (with the reason in it); only an address that is not a sign-in is an error.
    A printer's serial number and access code stay on the server: the answer carries a key to add printers by, and they are kept for a
    few minutes only. The tokens live for this one call."""
    _require_enabled()
    network = _network(body, request)
    try:
        tokens = bambu_cloud.parse_sign_in(body.url)
        steps = await bambu_cloud.run_session(
            _plugin_folder(),
            settings.orcaslicer_datadir / "bambu-session",
            settings.profiles_dir.parent / "cert",
            settings.bambu_helper_path,
            tokens,
        )
    except bambu_cloud.BambuCloudError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = bambu_cloud.summarize(steps)
    devices = bambu_import.private_devices(steps) if result["signed_in"] else []
    serials = {d["serial"] for d in devices if d["serial"]}
    found = await bambu_discovery.find_printers(network, serials) if network and serials else {}
    key = bambu_import.pending.put([{**d, "ip": found.get(d["serial"])} for d in devices]) if devices else None
    catalog = profiles_module.catalog
    printers = [
        {
            "index": index,
            "model": d["model"],
            "name": d["name"],
            "online": d["online"],
            "ip": found.get(d["serial"]),
            "supported": bambu_import.has_profile(d["model"], catalog),
        }
        for index, d in enumerate(devices)
    ]
    return {
        "signed_in": result["signed_in"],
        "user": result["user"],
        "problem": result["problem"],
        "network": network,
        "import_id": key,
        "printers": printers,
    }


class FindRequest(BaseModel):
    import_id: str = Field(min_length=1, max_length=100)
    network: str = Field(min_length=1, max_length=64)


@router.post("/find")
async def find_again(body: FindRequest, current: User = Depends(require_user)) -> dict[str, Any]:
    """Look for the account's printers on another network, from the list the server already holds (no new sign-in is needed).

    The serial numbers to look for come from the server's own list, never from the browser; the answer is each printer's address.
    """
    _require_enabled()
    devices = bambu_import.pending.get(body.import_id)
    if devices is None:
        raise HTTPException(status_code=404, detail="That list has expired; connect to the account again")
    network = _checked(body.network)
    found = await bambu_discovery.find_printers(network, {d["serial"] for d in devices if d["serial"]})
    for device in devices:
        if device["serial"] in found:
            device["ip"] = found[device["serial"]]
    return {"network": network, "printers": [{"index": i, "ip": found.get(d["serial"])} for i, d in enumerate(devices)]}


class ImportItem(BaseModel):
    index: int = Field(ge=0)
    ip: str | None = Field(default=None, max_length=64)


class ImportRequest(BaseModel):
    import_id: str = Field(min_length=1, max_length=100)
    items: list[ImportItem] = Field(min_length=1, max_length=20)


def _picked(items: list[ImportItem], devices: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any], str | None]]:
    """Every chosen printer with its checked address, or a 400 before anything is saved."""
    picked = []
    for item in items:
        if item.index >= len(devices):
            raise HTTPException(status_code=400, detail="That printer is not in the list")
        try:
            ip = bambu_import.clean_ip(item.ip)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        picked.append((item.index, devices[item.index], ip))
    return picked


@router.post("/import")
def import_printers(body: ImportRequest, current: User = Depends(require_user)) -> dict[str, Any]:
    """Save the chosen printers of a just-connected account, each with its serial number, access code, profiles and the given address."""
    _require_enabled()
    devices = bambu_import.pending.get(body.import_id)
    if devices is None:
        raise HTTPException(status_code=404, detail="That list has expired; connect to the account again")
    picked = _picked(body.items, devices)
    saved = {p.device_id for p in store.list_printers(current.id) if p.device_id}
    catalog = profiles_module.catalog
    added: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for index, device, ip in picked:
        if device["serial"] and device["serial"] in saved:
            skipped.append({"index": index, "reason": "Already saved"})
            continue
        fields = bambu_import.printer_request(device, ip, catalog)
        if fields is None:
            skipped.append({"index": index, "reason": f"Trident has no profile for a {device['model']}"})
            continue
        record = store.create_printer(user_id=current.id, **fields)
        saved.add(device["serial"])
        added.append({"index": index, "id": record.id, "name": record.name})
    return {"added": added, "skipped": skipped}
