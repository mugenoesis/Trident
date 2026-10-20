"""A Bambu printer's status report (what it publishes on MQTT in LAN / Developer mode) made into what the printer page shows.

The report is the `print` object of the printer's `push_status` messages. An X1 sends all of it every time; a P1 or an A1 sends only what changed
(after the whole of it once, when asked), so `merge_report` lays an update over what is known. The fields come out in the same shape as for a Klipper
printer (klipper_status.py), so the one page shows both. Bambu's protocol is documented by its users, not by Bambu: a field that is missing is
treated as unknown, never as an error.
"""

from __future__ import annotations

import posixpath
from collections.abc import Mapping
from typing import Any

# The printers that have a real chamber sensor, by what their serial numbers start with (the others report a chamber figure that is not a measurement).
_CHAMBER_SERIALS = ("00M", "03W", "094")  # X1 Carbon, X1E, H2D

_STATES = {
    "IDLE": "standby",
    "PREPARE": "printing",
    "RUNNING": "printing",
    "PAUSE": "paused",
    "FINISH": "complete",
    "FAILED": "error",
}


def merge_report(known: Mapping[str, Any], update: Mapping[str, Any]) -> dict[str, Any]:
    """What is known of a printer with an update laid over it (a P1 or A1 sends only the values that changed). Neither argument is changed."""
    return {**known, **update}


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _code(value: int, groups: int = 2) -> str:
    """A code as Bambu's wiki writes it: 8 hex digits in groups of four, joined by underscores (an HMS code is two of them)."""
    digits = f"{value:08X}"
    return "_".join(digits[i : i + 4] for i in range(0, 8, 4)) if groups == 2 else digits


def _message(report: Mapping[str, Any]) -> str:
    hms = report.get("hms")
    if isinstance(hms, list) and hms and isinstance(hms[0], Mapping):
        attr, code = _number(hms[0].get("attr")), _number(hms[0].get("code"))
        if attr is not None and code is not None:
            return f"The printer reported HMS {_code(int(attr))}_{_code(int(code))}"
    error = _number(report.get("print_error"))
    return f"The printer reported error {_code(int(error))}" if error else ""


def _temperature(name: str, kind: str, current: object, target: object) -> dict[str, Any] | None:
    now = _number(current)
    if now is None:
        return None
    goal = _number(target)
    return {"name": name, "kind": kind, "current": round(now, 1), "target": None if goal is None else round(goal, 1)}


def _temperatures(report: Mapping[str, Any], serial: str) -> list[dict[str, Any]]:
    out = [
        _temperature("Nozzle", "nozzle", report.get("nozzle_temper"), report.get("nozzle_target_temper")),
        _temperature("Bed", "bed", report.get("bed_temper"), report.get("bed_target_temper")),
    ]
    if serial.startswith(_CHAMBER_SERIALS):
        out.append(_temperature("Chamber", "chamber", report.get("chamber_temper"), None))
    return [t for t in out if t]


def _file(report: Mapping[str, Any]) -> str | None:
    name = report.get("subtask_name")
    if isinstance(name, str) and name:
        return name
    path = report.get("gcode_file")
    return posixpath.basename(path) or None if isinstance(path, str) else None


def status_from_bambu(report: Mapping[str, Any], serial: str = "") -> dict[str, Any]:
    """What the printer page shows for a Bambu status report (see the module's note); an empty report is an idle printer. `serial` is the
    printer's serial number, which says whether it has a chamber sensor."""
    raw = report.get("gcode_state")
    state = _STATES.get(str(raw), str(raw).lower()) if raw else "standby"
    idle = state == "standby"

    percent = _number(report.get("mc_percent"))
    progress = None if idle or percent is None else round(min(max(percent, 0), 100) / 100, 4)
    minutes = _number(report.get("mc_remaining_time"))
    remaining = round(minutes * 60) if state == "printing" and minutes is not None else None
    layer, layers = _number(report.get("layer_num")), _number(report.get("total_layer_num"))

    return {
        "state": state,
        "state_message": _message(report),
        "file": None if idle else _file(report),
        "progress": progress,
        "layer": (
            {"current": int(layer), "total": int(layers)}
            if not idle and layer is not None and layers and layers > 0
            else None
        ),
        "elapsed_s": None,
        "remaining_s": remaining,
        "temperatures": _temperatures(report, serial),
        "can": {"pause": state == "printing", "resume": state == "paused", "cancel": state in ("printing", "paused")},
    }
