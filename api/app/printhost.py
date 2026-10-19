"""Sends a job's sliced G-code straight to a physical printer's own HTTP API.

Wired for the two common self-hosted host types from OrcaSlicer's own
host_type enum (vendor/orcaslicer/src/libslic3r/PrintConfig.cpp) that have
simple, stable upload APIs: Klipper via Moonraker (Mainsail/Fluidd), and
OctoPrint. Entirely our own outbound HTTP call, done server-side so
credentials never round-trip back through the browser -- OrcaSlicer's CLI
mode was never involved in uploading to a print host, so this has nothing
to do with the nocli/blocked_settings machinery.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

import httpx

SUPPORTED_HOST_TYPES = frozenset({"moonraker", "octoprint"})

# printer is a Mapping (sqlite3.Row for a saved printer's stored credentials,
# or a plain dict from a request body for validating an in-progress edit
# before it's even saved) -- both support the [] access used here.
Printer = Mapping[str, Any] | sqlite3.Row


class PrintHostError(Exception):
    """Message is safe to show the user directly."""


def _auth_kwargs(printer: Printer) -> dict[str, Any]:
    if printer["printhost_user"] and printer["printhost_password"]:
        return {"auth": (printer["printhost_user"], printer["printhost_password"])}
    return {}


def _headers(printer: Printer) -> dict[str, str]:
    if printer["printhost_apikey"]:
        return {"X-Api-Key": printer["printhost_apikey"]}
    return {}


def _require_supported(printer: Printer) -> tuple[str, str]:
    host_type = printer["host_type"]
    print_host = printer["print_host"]
    if not print_host:
        raise PrintHostError("This printer has no host address configured")
    if host_type not in SUPPORTED_HOST_TYPES:
        raise PrintHostError(f"Sending to host type {host_type!r} isn't supported yet")
    return host_type, print_host.rstrip("/")


async def send_gcode(
    printer: Printer,
    gcode_path: Path,
    start_print: bool,
    *,
    client: httpx.AsyncClient | None = None,
) -> None:
    """`client` is only ever passed in tests (an httpx.MockTransport-backed
    one) -- production always builds its own, scoped to this one request."""
    host_type, base = _require_supported(printer)

    if host_type == "moonraker":
        url = f"{base}/server/files/upload"
        data = {"root": "gcodes", **({"print": "true"} if start_print else {})}
    else:
        url = f"{base}/api/files/local"
        data = {**({"print": "true"} if start_print else {})}

    owns_client = client is None
    if owns_client:
        # Large gcode files can take a while to transfer -- generous read
        # timeout, short connect timeout so a wrong host/port fails fast.
        client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=120.0))
    try:
        try:
            with gcode_path.open("rb") as f:
                response = await client.post(
                    url,
                    files={"file": (gcode_path.name, f, "text/x.gcode")},
                    data=data,
                    headers=_headers(printer),
                    **_auth_kwargs(printer),
                )
        except httpx.HTTPError as exc:
            raise PrintHostError(f"Couldn't reach the printer: {exc}") from exc
    finally:
        if owns_client:
            await client.aclose()

    if response.status_code >= 400:
        raise PrintHostError(f"Printer host returned {response.status_code}: {response.text[:200]}")


async def test_connection(printer: Printer, *, client: httpx.AsyncClient | None = None) -> str:
    """A cheap read-only ping (no upload) -- returns a short human-readable
    status string on success, or raises PrintHostError."""
    host_type, base = _require_supported(printer)
    url = f"{base}/server/info" if host_type == "moonraker" else f"{base}/api/version"

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=httpx.Timeout(5.0, read=10.0))
    try:
        try:
            response = await client.get(url, headers=_headers(printer), **_auth_kwargs(printer))
        except httpx.HTTPError as exc:
            raise PrintHostError(f"Couldn't reach the printer: {exc}") from exc
    finally:
        if owns_client:
            await client.aclose()

    if response.status_code >= 400:
        raise PrintHostError(f"Printer host returned {response.status_code}: {response.text[:200]}")

    try:
        data = response.json()
    except ValueError:
        return "Connected"

    if host_type == "moonraker":
        state = (data.get("result") or {}).get("klippy_state", "unknown")
        return f"Connected (Klipper state: {state})"
    return str(data.get("text") or data.get("server") or "Connected")


async def _get_json(client: httpx.AsyncClient, url: str, printer: Printer) -> Any:
    """One read-only GET that answers JSON, or a PrintHostError that says what to do."""
    try:
        response = await client.get(url, headers=_headers(printer), **_auth_kwargs(printer))
    except httpx.HTTPError as exc:
        raise PrintHostError(f"Couldn't reach the printer: {exc}") from exc
    if response.status_code in (401, 403):
        raise PrintHostError(
            "The printer refused the request. Check the API key (or the user and password) for Moonraker."
        )
    if response.status_code == 404:
        raise PrintHostError(
            "That address does not look like Moonraker, Klipper's web API (it is usually port 7125 or the Mainsail/Fluidd address)."
        )
    if response.status_code >= 400:
        raise PrintHostError(f"Printer host returned {response.status_code}: {response.text[:200]}")
    try:
        return response.json()
    except ValueError:
        raise PrintHostError("That address answered, but not like Moonraker (Klipper's web API).") from None


def _field(data: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(data, Mapping) or key not in data:
            raise PrintHostError(
                "Moonraker's answer was not in the form expected: is that address Klipper's Moonraker?"
            )
        data = data[key]
    return data


async def read_klipper(printer: Printer, *, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """A Klipper printer's own configuration as Moonraker reports it: `{info, settings, objects}`. Read-only (three GETs);
    nothing on the printer is changed. `client` is only passed in tests."""
    if printer["host_type"] != "moonraker":
        raise PrintHostError("Reading a printer's settings works for Klipper printers (Moonraker) only")
    _, base = _require_supported(printer)

    owns_client = client is None
    if owns_client:
        # The config of a printer with many macros is a few hundred kB: a short connect timeout, a generous read one.
        client = httpx.AsyncClient(timeout=httpx.Timeout(5.0, read=20.0))
    try:
        info = _field(await _get_json(client, f"{base}/printer/info", printer), "result")
        state = info.get("state") if isinstance(info, Mapping) else None
        if state != "ready":
            raise PrintHostError(
                f"Klipper is not ready ({state}): {info.get('state_message', '') if isinstance(info, Mapping) else ''}"
            )
        config = await _get_json(client, f"{base}/printer/objects/query?configfile", printer)
        objects = await _get_json(client, f"{base}/printer/objects/list", printer)
    finally:
        if owns_client:
            await client.aclose()
    return {
        "info": info,
        "settings": _field(config, "result", "status", "configfile", "settings"),
        "objects": _field(objects, "result", "objects"),
    }


# ---- the printer page: live status, pause/resume/cancel, webcams (Klipper through Moonraker) ----

_CONTROLS = ("pause", "resume", "cancel")
_STATUS_OBJECTS = ("webhooks", "print_stats", "virtual_sdcard", "display_status")
_HEATER_OBJECT = re.compile(r"^(extruder\d*|heater_bed|heater_generic .+|temperature_sensor .+|temperature_fan .+)$")
_MAX_SNAPSHOT_BYTES = 5 * 1024 * 1024


class NoSuchCamera(PrintHostError):
    """The printer has no camera with that number."""


def _klipper_base(printer: Printer, what: str) -> str:
    if printer["host_type"] != "moonraker":
        raise PrintHostError(f"{what} works for Klipper printers (Moonraker) only")
    return _require_supported(printer)[1]


@asynccontextmanager
async def _session(client: httpx.AsyncClient | None, read_timeout: float) -> AsyncIterator[httpx.AsyncClient]:
    """The given client (tests), or one scoped to this one piece of work."""
    if client is not None:
        yield client
        return
    own = httpx.AsyncClient(timeout=httpx.Timeout(5.0, read=read_timeout))
    try:
        yield own
    finally:
        await own.aclose()


async def read_status(printer: Printer, *, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """A Klipper printer's live status as Moonraker reports it (the `status` of an objects query): the print, and every heater and temperature
    sensor it has. Read-only: two GETs. `client` is only passed in tests."""
    base = _klipper_base(printer, "A live status")
    async with _session(client, 10.0) as http:
        listed = _field(await _get_json(http, f"{base}/printer/objects/list", printer), "result", "objects")
        wanted = [o for o in listed if isinstance(o, str) and (o in _STATUS_OBJECTS or _HEATER_OBJECT.match(o))]
        query = "&".join(quote(name, safe="") for name in wanted)
        answer = await _get_json(http, f"{base}/printer/objects/query?{query}", printer)
    return _field(answer, "result", "status")


async def print_control(printer: Printer, action: str, *, client: httpx.AsyncClient | None = None) -> None:
    """Pause, resume or cancel the print on a Klipper printer. Nothing else can be asked of it through here."""
    if action not in _CONTROLS:
        raise PrintHostError("Only pause, resume or cancel can be asked of the printer")
    base = _klipper_base(printer, "Controlling a print")
    async with _session(client, 15.0) as http:
        try:
            response = await http.post(
                f"{base}/printer/print/{action}", headers=_headers(printer), **_auth_kwargs(printer)
            )
        except httpx.HTTPError as exc:
            raise PrintHostError(f"Couldn't reach the printer: {exc}") from exc
    if response.status_code >= 400:
        raise PrintHostError(_refusal(response))


def _refusal(response: httpx.Response) -> str:
    """The printer's own words for why it said no, else its status."""
    try:
        message = response.json()["error"]["message"]
        if isinstance(message, str) and message:
            return message[:200]
    except (ValueError, KeyError, TypeError):
        pass
    return f"Printer host returned {response.status_code}: {response.text[:200]}"


async def _cameras(http: httpx.AsyncClient, printer: Printer, base: str) -> list[dict[str, str]]:
    answer = await _get_json(http, f"{base}/server/webcams/list", printer)
    origin = "{0.scheme}://{0.netloc}/".format(urlsplit(base))
    cameras: list[dict[str, str]] = []
    for cam in _field(answer, "result", "webcams"):
        if not isinstance(cam, Mapping) or not cam.get("enabled", True) or not cam.get("snapshot_url"):
            continue
        snapshot = urljoin(origin, str(cam["snapshot_url"]))
        if urlsplit(snapshot).scheme not in ("http", "https"):
            continue
        stream = urljoin(origin, str(cam.get("stream_url") or ""))
        cameras.append(
            {
                "name": str(cam.get("name") or f"Camera {len(cameras) + 1}"),
                "snapshot_url": snapshot,
                "stream_url": stream,
            }
        )
    return cameras


async def webcam_list(printer: Printer, *, client: httpx.AsyncClient | None = None) -> list[dict[str, str]]:
    """The printer's enabled webcams that can give a snapshot: `{name, snapshot_url, stream_url}`, addresses made whole."""
    base = _klipper_base(printer, "A webcam")
    async with _session(client, 10.0) as http:
        return await _cameras(http, printer, base)


async def webcam_snapshot(
    printer: Printer, index: int, *, client: httpx.AsyncClient | None = None
) -> tuple[bytes, str]:
    """One picture from webcam `index` of `webcam_list`, and its type. The printer's credentials go only to the printer's own address."""
    base = _klipper_base(printer, "A webcam")
    async with _session(client, 10.0) as http:
        cameras = await _cameras(http, printer, base)
        if not 0 <= index < len(cameras):
            raise NoSuchCamera(f"There is no camera {index} on this printer")
        url = cameras[index]["snapshot_url"]
        ours = urlsplit(url).netloc == urlsplit(base).netloc
        try:
            response = await http.get(
                url, headers=_headers(printer) if ours else {}, **(_auth_kwargs(printer) if ours else {})
            )
        except httpx.HTTPError as exc:
            raise PrintHostError(f"Couldn't reach the camera: {exc}") from exc
    if response.status_code >= 400:
        raise PrintHostError(f"The camera returned {response.status_code}")
    kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if not kind.startswith("image/"):
        raise PrintHostError("The camera did not answer with a picture")
    if len(response.content) > _MAX_SNAPSHOT_BYTES:
        raise PrintHostError("The camera's picture is too large")
    return response.content, kind
