"""Turning the printers of a Bambu account into saved printers: which catalogue printer a model is, what is saved for it, and the short-lived
list that keeps each printer's serial number and access code on the server (the browser only ever sees model, name, state and address).
"""

from __future__ import annotations

import ipaddress
import secrets
import time
from collections.abc import Callable
from typing import Any

# A catalogue printer is saved with the 0.4 nozzle; its own defaults (process, material, bed) come from the catalogue entry.
NOZZLE = "0.4 nozzle"
VENDOR = "BBL"
DEFAULT_COLOR = "#ffffff"


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _account_entry(device: dict[str, Any]) -> dict[str, Any]:
    online = device.get("dev_online")
    return {
        "serial": _text(device.get("dev_id")) or "",
        "access_code": _text(device.get("dev_access_code")) or "",
        "model": _text(device.get("dev_product_name")) or _text(device.get("dev_model_name")) or "Unknown",
        "name": _text(device.get("dev_name")),
        "online": online if isinstance(online, bool) else None,
    }


def private_devices(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The account's printers with what must stay on the server (serial number, access code), from the helper's `account_devices` step."""
    raw = next((s.get("value") for s in steps if isinstance(s, dict) and s.get("step") == "account_devices"), None)
    return [_account_entry(device) for device in raw if isinstance(device, dict)] if isinstance(raw, list) else []


def _machine(model: str, catalog: Any) -> Any:
    prefix = "" if model.startswith("Bambu Lab ") else "Bambu Lab "
    return catalog.get_by_name("machine", f"{prefix}{model} {NOZZLE}")


def has_profile(model: str, catalog: Any) -> bool:
    """Whether the catalogue has this model, with a default process to slice with."""
    machine = _machine(model, catalog)
    return machine is not None and bool(machine.data.get("default_print_profile"))


def _first(value: Any) -> str | None:
    """A default that the catalogue gives as one name or as a list of them: the first."""
    if isinstance(value, list):
        value = value[0] if value else None
    return value if isinstance(value, str) and value else None


def _bed(data: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    points = []
    for corner in data.get("printable_area") or []:
        try:
            x, y = (float(part) for part in str(corner).split("x"))
        except ValueError:
            continue
        points.append((x, y))
    width = max(x for x, _ in points) - min(x for x, _ in points) if points else None
    depth = max(y for _, y in points) - min(y for _, y in points) if points else None
    try:
        height: float | None = float(data["printable_height"])
    except (KeyError, TypeError, ValueError):
        height = None
    return width, depth, height


def printer_request(device: dict[str, Any], ip: str | None, catalog: Any) -> dict[str, Any] | None:
    """The fields of a saved printer for one account printer, or None when the catalogue has no such model.

    It is saved as monitor only: the account says nothing about Developer Mode, and watching a printer always works."""
    machine = _machine(device["model"], catalog)
    process = _first(machine.data.get("default_print_profile")) if machine is not None else None
    if machine is None or process is None:
        return None
    material = _first(machine.data.get("default_filament_profile"))
    width, depth, height = _bed(machine.data)
    return {
        "name": device.get("name") or device["model"],
        "vendor": VENDOR,
        "machine_profile": machine.name,
        "process_profile": process,
        "filament_profiles": [material] if material else [],
        "filament_colors": [DEFAULT_COLOR] if material else [],
        "bed_width": width,
        "bed_depth": depth,
        "bed_height": height,
        "host_type": "bambu",
        "print_host": ip,
        "printhost_apikey": device.get("access_code") or None,
        "device_id": device.get("serial") or None,
        "monitor_only": True,
    }


def clean_ip(text: str | None) -> str | None:
    """An IPv4 address as typed (surrounding space dropped), None for nothing; anything else is a ValueError."""
    address = (text or "").strip()
    if not address:
        return None
    try:
        ipaddress.IPv4Address(address)
    except ValueError as exc:
        raise ValueError("That is not an IP address (like 192.168.1.58)") from exc
    return address


class PendingAccounts:
    """The printers of a just-connected account, with the serial numbers and access codes the browser never sees, kept for a few minutes.

    A connect puts the list here and gets an unguessable key back; adding printers names that key and the printers to add.
    """

    def __init__(self, ttl_s: float = 600.0, keep: int = 8, clock: Callable[[], float] = time.monotonic):
        self._ttl_s = ttl_s
        self._keep = keep
        self._clock = clock
        self._items: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    def put(self, devices: list[dict[str, Any]]) -> str:
        now = self._clock()
        for key in [k for k, (expires, _) in self._items.items() if expires < now]:
            del self._items[key]
        key = secrets.token_urlsafe(24)
        self._items[key] = (now + self._ttl_s, devices)
        while len(self._items) > self._keep:
            del self._items[next(iter(self._items))]
        return key

    def get(self, key: str) -> list[dict[str, Any]] | None:
        item = self._items.get(key)
        if item is None:
            return None
        if item[0] < self._clock():
            del self._items[key]
            return None
        return item[1]

    def forget(self, key: str) -> None:
        self._items.pop(key, None)


pending = PendingAccounts()
