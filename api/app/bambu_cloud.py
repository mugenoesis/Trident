"""EXPERIMENT: signing in to Bambu Cloud through Bambu's own network plug-in, so a printer can stay in cloud mode.

Bambu's plug-in is a closed binary that Orca and Bambu Studio download from Bambu on first use; it is never shipped here. This module
downloads it only when the user asks, builds the link to Bambu's own sign-in page (which the *user's* browser opens: this server never sees
a password), reads the address that browser ends up on, and hands the sign-in to the plug-in through a small helper program
(api/helper/bbl_session.cpp) that calls it the way Orca does. Nothing is kept after a call: the tokens exist only for the length of one
connect.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlsplit

import httpx

RESOURCE_URL = "https://api.bambulab.com/v1/iot-service/api/slicer/resource?slicer/plugins/cloud=02.00.00.00"
SIGN_IN_URL = "https://bambulab.com/sign-in"
# Bambu's sign-in only hands the browser back to localhost (the address Orca's own login window listens on), so it is always this.
LOOPBACK_BASE = "http://localhost:41999"
_LOOPBACK_HOSTS = ("localhost", "127.0.0.1")
TOKEN_FIELDS = ("access_token", "refresh_token", "expires_in", "refresh_expires_in")
NETWORK_LIBRARY = "libbambu_networking.so"
PLUGIN_LIBRARIES = (NETWORK_LIBRARY, "libBambuSource.so", "liblive555.so")
MAX_PLUGIN_BYTES = 64 * 1024 * 1024
HELPER_TIMEOUT_S = 90
_META = "plugin.json"
# The helper masks values it does not show as the name of their type; those are not data.
_MASKED = ("string", "boolean", "number", "object", "array", "null")


class BambuCloudError(Exception):
    """Something that went wrong with the plug-in or the sign-in, in words the user can read."""


# ---- the sign-in ----


def sign_in_url() -> str:
    """The link to Bambu's own sign-in page, built as Orca builds it; the browser ends on a localhost address that carries the sign-in."""
    callback = (
        "https://bambulab.com/sign-in/callback?openBy=studio&from=studio&source=portal&locale=en"
        f"&redirect_url={quote(LOOPBACK_BASE, safe='')}"
    )
    return f"{SIGN_IN_URL}?from=studio&source=portal&to={quote(callback, safe='')}"


def parse_sign_in(address: str) -> dict[str, str]:
    """The tokens in the address the browser ended up on (it starts with http://localhost). Nothing pasted is ever repeated in an error."""
    hint = "Paste the address the browser ended up on after signing in (it starts with http://localhost and carries the sign-in)"
    try:
        parts = urlsplit(address.strip())
    except ValueError as exc:
        raise BambuCloudError(hint) from exc
    if parts.scheme not in ("http", "https") or parts.hostname not in _LOOPBACK_HOSTS:
        raise BambuCloudError(hint)
    fields = dict(parse_qsl(parts.fragment)) | dict(parse_qsl(parts.query))
    if not (fields.get("access_token") and fields.get("refresh_token")):
        raise BambuCloudError(hint)
    return {name: fields.get(name, "") for name in TOKEN_FIELDS}


# ---- the plug-in ----


def plugin_status(folder: Path) -> dict[str, Any]:
    meta = folder / _META
    if not (folder / NETWORK_LIBRARY).is_file() or not meta.is_file():
        return {"installed": False}
    return {"installed": True, **json.loads(meta.read_text())}


def _extract(archive: bytes, folder: Path) -> None:
    """Only the three libraries are unpacked, under names chosen here: nothing in the archive picks a path."""
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            wanted = {Path(n).name: n for n in zipped.namelist() if Path(n).name in PLUGIN_LIBRARIES}
            if NETWORK_LIBRARY not in wanted:
                raise BambuCloudError(f"The download has no {NETWORK_LIBRARY}; it is not the plug-in")
            folder.mkdir(parents=True, exist_ok=True)
            for name, member in wanted.items():
                (folder / name).write_bytes(zipped.read(member))
    except zipfile.BadZipFile as exc:
        raise BambuCloudError("The download from Bambu is not a zip file") from exc


async def _linux_plugin_entry(client: httpx.AsyncClient) -> dict[str, Any]:
    reply = await client.get(RESOURCE_URL, headers={"X-BBL-OS-Type": "linux"})
    reply.raise_for_status()
    for resource in reply.json().get("resources", []):
        if resource.get("type") == "slicer/plugins/cloud" and resource.get("url"):
            return resource
    raise BambuCloudError("Bambu lists no Linux plug-in right now")


async def install_plugin(folder: Path, *, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Download Bambu's Linux network plug-in from the address Bambu's own service names, and unpack its libraries into `folder`."""
    own = client is None
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=120.0), follow_redirects=True)
    try:
        entry = await _linux_plugin_entry(http)
        reply = await http.get(entry["url"])
        reply.raise_for_status()
    except (httpx.HTTPError, ValueError) as exc:
        raise BambuCloudError(f"Couldn't get the plug-in from Bambu: {exc}") from exc
    finally:
        if own:
            await http.aclose()
    archive = reply.content
    if len(archive) > MAX_PLUGIN_BYTES:
        raise BambuCloudError("The plug-in download is larger than expected; not unpacking it")
    _extract(archive, folder)
    meta = {"version": entry.get("version"), "sha256": hashlib.sha256(archive).hexdigest(), "url": entry["url"]}
    (folder / _META).write_text(json.dumps(meta))
    return {"installed": True, **meta}


# ---- handing the sign-in to the plug-in ----


async def run_session(
    plugin_dir: Path, config_dir: Path, cert_dir: Path, helper: Path, tokens: dict[str, str]
) -> list[dict[str, Any]]:
    """Give the sign-in to Bambu's plug-in through the helper program, and return the steps it reports.

    The tokens go to the helper on stdin only, and a step that would repeat one is dropped: no token leaves this function. A helper that
    crashes still leaves the steps it printed before."""
    if not await asyncio.to_thread(helper.is_file):
        raise BambuCloudError("The helper program for Bambu's plug-in is not in this image")
    payload = json.dumps(
        {
            "plugin_dir": str(plugin_dir),
            "config_dir": str(config_dir),
            "cert_dir": str(cert_dir),
            **{name: tokens.get(name, "") for name in TOKEN_FIELDS},
        }
    )
    proc = await asyncio.create_subprocess_exec(
        str(helper), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(payload.encode()), HELPER_TIMEOUT_S)
    except TimeoutError as exc:
        proc.kill()
        raise BambuCloudError("The plug-in did not answer in time") from exc
    secrets = [value for name, value in tokens.items() if name.endswith("_token") and value]
    steps: list[dict[str, Any]] = []
    for line in out.decode(errors="replace").splitlines():
        if any(secret in line for secret in secrets):
            continue
        try:
            steps.append(json.loads(line))
        except ValueError:
            continue
    if proc.returncode:
        steps.append({"step": "helper_exit", "value": proc.returncode})
    return steps


def _printers(info: Any) -> list[dict[str, Any]]:
    devices = info.get("devices") if isinstance(info, dict) else None
    found = []
    for device in devices if isinstance(devices, list) else []:
        if not isinstance(device, dict):
            continue
        model = device.get("dev_product_name") or device.get("dev_model_name")
        name = device.get("dev_name")
        online = device.get("dev_online")
        found.append(
            {
                "model": model if isinstance(model, str) and model not in _MASKED else "Unknown",
                "name": name if isinstance(name, str) and name not in _MASKED else None,
                "online": online if isinstance(online, bool) else None,
            }
        )
    return found


def _problem(by_step: dict[str, Any]) -> str:
    """Why the plug-in did not end up signed in, in words, from the steps it reported."""
    if "error" in by_step:
        return f"The plug-in program reported: {by_step['error']}"
    if "helper_exit" in by_step:
        return f"The plug-in program stopped unexpectedly (exit code {by_step['helper_exit']})"
    profile = by_step.get("get_my_profile")
    if isinstance(profile, dict) and profile.get("http_code") != 200:
        return f"Bambu's plug-in could not reach Bambu's servers (code {profile.get('http_code')})"
    if "is_user_login" in by_step:
        return "The plug-in did not accept the sign-in; sign in again and paste the new address"
    return "The plug-in gave no answer"


def summarize(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """What the page shows: whether the plug-in is signed in, as whom, which printers it lists, or why not."""
    by_step: dict[str, Any] = {
        str(step["step"]): step.get("value") for step in steps if isinstance(step, dict) and "step" in step
    }
    signed_in = by_step.get("is_user_login") is True
    user = by_step.get("user_name")
    return {
        "signed_in": signed_in,
        "user": user if signed_in and isinstance(user, str) and user else None,
        "printers": _printers(by_step.get("get_user_print_info")) if signed_in else [],
        "problem": None if signed_in else _problem(by_step),
    }
