"""EXPERIMENT: signing in to Bambu Cloud through Bambu's own network plug-in, so a printer can stay in cloud mode.

Bambu's plug-in is a closed binary that Orca and Bambu Studio download from Bambu on first use; it is never shipped here. This
module downloads it only when the user asks, and builds the link to Bambu's own sign-in page, which the *user's* browser opens: this
server never sees a password. Bambu's page then redirects the browser back to Trident's callback, and the callback records what
arrived by field name and length only (the values stay out of every response and log) until the plug-in's token exchange is wired in.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import re
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlsplit

import httpx

RESOURCE_URL = "https://api.bambulab.com/v1/iot-service/api/slicer/resource?slicer/plugins/cloud=02.00.00.00"
SIGN_IN_URL = "https://bambulab.com/sign-in"
CALLBACK_PATH = "/bambu-cloud/callback"
NETWORK_LIBRARY = "libbambu_networking.so"
PLUGIN_LIBRARIES = (NETWORK_LIBRARY, "libBambuSource.so", "liblive555.so")
MAX_PLUGIN_BYTES = 64 * 1024 * 1024
_META = "plugin.json"
_ORIGIN = re.compile(r"^https?://[A-Za-z0-9.-]+(:\d{1,5})?$")


class BambuCloudError(Exception):
    """Something that went wrong with the plug-in or the sign-in, in words the user can read."""


LOOPBACK_BASE = "http://localhost:41999"
_LOOPBACK_HOSTS = ("localhost", "127.0.0.1")


def sign_in_url(origin: str, *, loopback: bool = False) -> str:
    """The Bambu sign-in link that sends the browser back to `origin` (Trident's own address) once the user is signed in.

    With `loopback` it is the link Orca itself builds, which sends the browser to localhost instead (nothing need listen there).
    """
    if not _ORIGIN.match(origin):
        raise BambuCloudError("That is not a plain web address (http://host:port) for Trident")
    back = LOOPBACK_BASE if loopback else origin + CALLBACK_PATH
    callback = (
        "https://bambulab.com/sign-in/callback?openBy=studio&from=studio&source=portal&locale=en"
        f"&redirect_url={quote(back, safe='')}"
    )
    return f"{SIGN_IN_URL}?from=studio&source=portal&to={quote(callback, safe='')}"


# ---- what Bambu's redirect carries ----


class _Callback:
    """The last redirect from Bambu: what may be shown, and (kept here for the token exchange) the raw values."""

    shown: dict[str, Any] | None = None
    raw: dict[str, str] = {}  # noqa: RUF012 -- replaced whole, never mutated


_callback = _Callback()


def record_callback(path: str, query: dict[str, str]) -> None:
    """Remember a redirect from Bambu: only its field names and lengths can ever be read back (`last_callback`)."""
    extra = [len(part) for part in path.removeprefix(CALLBACK_PATH).split("/") if part]
    _callback.shown = {
        "received_at": time.time(),
        "fields": [{"name": name, "length": len(value)} for name, value in query.items()],
        "extra_path_lengths": extra,
    }
    _callback.raw = dict(query)


def record_pasted(address: str) -> dict[str, Any]:
    """Record an address the browser ended up on (copied from its address bar): only a localhost one, by query and fragment field names."""
    parts = urlsplit(address.strip())
    if parts.scheme not in ("http", "https") or parts.hostname not in _LOOPBACK_HOSTS:
        raise BambuCloudError("Paste the address the browser ended up on: it starts with http://localhost")
    fields = dict(parse_qsl(parts.query)) | dict(parse_qsl(parts.fragment))
    record_callback(parts.path or "/", fields)
    return _callback.shown or {}


def last_callback() -> dict[str, Any] | None:
    return _callback.shown


def forget_callback() -> None:
    _callback.shown, _callback.raw = None, {}


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

HELPER_TIMEOUT_S = 90


async def run_session(plugin_dir: Path, config_dir: Path, cert_dir: Path, helper: Path) -> list[dict[str, Any]]:
    """Give the last pasted sign-in to Bambu's plug-in through the helper program, and return the steps it reports.

    The tokens go to the helper on stdin only, and a step that would repeat one is dropped: no token leaves this function."""
    raw = _callback.raw
    if not (raw.get("access_token") and raw.get("refresh_token")):
        raise BambuCloudError("Paste the address the browser ended up on after signing in first")
    if not helper.is_file():
        raise BambuCloudError("The helper program for Bambu's plug-in is not in this image")
    keys = ("access_token", "refresh_token", "expires_in", "refresh_expires_in")
    payload = json.dumps(
        {"plugin_dir": str(plugin_dir), "config_dir": str(config_dir), "cert_dir": str(cert_dir), **{k: raw.get(k, "") for k in keys}}
    )
    proc = await asyncio.create_subprocess_exec(
        str(helper), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(payload.encode()), HELPER_TIMEOUT_S)
    except TimeoutError as exc:
        proc.kill()
        raise BambuCloudError("The plug-in did not answer in time") from exc
    secrets = [v for k, v in raw.items() if k.endswith("_token") and v]
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
