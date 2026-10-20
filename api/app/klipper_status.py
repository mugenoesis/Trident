"""A Klipper printer's status as Moonraker reports it (the `status` of an objects query) made into what the printer page shows.

Only what the page needs is passed on: the print state and file, progress, layers, the time so far and an estimate of the time left, the
temperatures, and what can be done to the print (pause, resume, cancel).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

# Below this much done, the time left would be a wild guess.
_MIN_PROGRESS_FOR_ESTIMATE = 0.01
_NOZZLE = re.compile(r"^extruder(\d*)$")
_CHAMBER_WORDS = ("chamber", "cavity")
# What Klipper itself says when it is not running prints: its own state wins over the print's.
_NOT_RUNNING = ("startup", "shutdown", "error")


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _section(status: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = status.get(name)
    return value if isinstance(value, Mapping) else {}


def _temperature(name: str, kind: str, values: Mapping[str, Any]) -> dict[str, Any] | None:
    current = _number(values.get("temperature"))
    if current is None:
        return None
    target = _number(values.get("target"))
    return {
        "name": name,
        "kind": kind,
        "current": round(current, 1),
        "target": None if target is None else round(target, 1),
    }


def _nozzles(status: Mapping[str, Any]) -> list[dict[str, Any] | None]:
    keys = sorted((k for k in status if _NOZZLE.match(k)), key=lambda k: int(_NOZZLE.match(k).group(1) or 0))  # type: ignore[union-attr]
    return [
        _temperature(f"Nozzle {i + 1}" if len(keys) > 1 else "Nozzle", "nozzle", _section(status, key))
        for i, key in enumerate(keys)
    ]


def _heaters(status: Mapping[str, Any]) -> list[dict[str, Any] | None]:
    return [
        _temperature(key.split(" ", 1)[1], "heater", _section(status, key))
        for key in sorted(k for k in status if k.startswith("heater_generic "))
    ]


def _sensors(status: Mapping[str, Any]) -> list[dict[str, Any] | None]:
    """The chamber's sensors, then the other temperature sensors."""
    keys = sorted(k for k in status if k.startswith(("temperature_sensor ", "temperature_fan ")))
    chambers = [k for k in keys if any(w in k.lower() for w in _CHAMBER_WORDS)]
    out = [_temperature("Chamber", "chamber", _section(status, key)) for key in chambers]
    out += [_temperature(key.split(" ", 1)[1], "sensor", _section(status, key)) for key in keys if key not in chambers]
    return out


def _temperatures(status: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The nozzles, the bed, other heaters, the chamber and the other sensors, in that order."""
    out = [
        *_nozzles(status),
        _temperature("Bed", "bed", _section(status, "heater_bed")),
        *_heaters(status),
        *_sensors(status),
    ]
    return [t for t in out if t]


def _layers(info: object) -> dict[str, int] | None:
    if not isinstance(info, Mapping):
        return None
    total, current = _number(info.get("total_layer")), _number(info.get("current_layer"))
    if total is None or total <= 0 or current is None:
        return None
    return {"current": int(current), "total": int(total)}


def status_from_klipper(status: Mapping[str, Any]) -> dict[str, Any]:
    """What the printer page shows for a Moonraker status (see the module's note); an empty status is an idle printer."""
    stats = _section(status, "print_stats")
    webhooks = _section(status, "webhooks")
    state = str(stats.get("state") or "standby")
    message = str(stats.get("message") or "")
    if webhooks.get("state") in _NOT_RUNNING:
        state, message = str(webhooks["state"]), str(webhooks.get("state_message") or "")

    file = stats.get("filename") or None
    progress = _number(_section(status, "virtual_sdcard").get("progress"))
    if progress is None:
        progress = _number(_section(status, "display_status").get("progress"))
    progress = round(progress, 4) if file and progress is not None else None

    elapsed = _number(stats.get("print_duration"))
    remaining = None
    if state == "printing" and elapsed and progress and progress >= _MIN_PROGRESS_FOR_ESTIMATE:
        remaining = round(elapsed * (1 - progress) / progress)

    return {
        "state": state,
        "state_message": message,
        "file": file,
        "progress": progress,
        "layer": _layers(stats.get("info")),
        "elapsed_s": None if elapsed is None else round(elapsed),
        "remaining_s": remaining,
        "temperatures": _temperatures(status),
        "can": {"pause": state == "printing", "resume": state == "paused", "cancel": state in ("printing", "paused")},
    }
