"""A Klipper printer's own config (read through Moonraker, see printhost.read_klipper) turned into the "New printer" form.

Only the values a slicer needs are taken (the bed, the nozzle, the speeds, retraction, the start and end macros) and each
comes with where it was read, so the user can check it. What a config cannot say for itself becomes a note: a toolchanger's
travel is bigger than its bed, a macro that takes no temperatures leaves the heating to the slicer. A macro's own code is
read for the names of its parameters and never passed on.
"""

from __future__ import annotations

import re
from typing import Any

# Kinematics whose bed is the range of the x and y steppers; a delta's is a circle of its print radius.
_RECTANGULAR = frozenset(
    {
        "cartesian",
        "corexy",
        "corexz",
        "hybrid_corexy",
        "hybrid_corexz",
        "limited_cartesian",
        "limited_corexy",
        "limited_corexz",
    }
)
# A bed mesh that covers less than this share of an axis's travel makes the travel look bigger than the bed.
_MESH_COVERAGE = 0.85

_START_MACROS = ("start_print", "print_start")
_END_MACROS = ("end_print", "print_end")
# What a macro's parameters are called, by what the slicer fills in for them: (the names, the slicer's placeholder), in the
# order the start line gives them.
_PARAMETER_GROUPS = (
    (("BED_TEMP", "BED", "BED_TEMPERATURE", "TEMP_BED", "BED_TEMP_INITIAL"), "[bed_temperature_initial_layer_single]"),
    (
        (
            "EXTRUDER_TEMP",
            "EXTRUDER",
            "EXTRUDER_TEMPERATURE",
            "HOTEND_TEMP",
            "HOTEND",
            "NOZZLE_TEMP",
            "NOZZLE",
            "TEMP_EXTRUDER",
        ),
        "[nozzle_temperature_initial_layer]",
    ),
    (("CHAMBER_TEMP", "CHAMBER", "CHAMBER_TEMPERATURE"), "[chamber_temperature]"),
)
_PARAMETER_PATTERN = re.compile(r"""params(?:\.([A-Za-z_]\w*)|\[\s*['"](\w+)['"]\s*\])""")
_EXTRUDER_NAME = re.compile(r"^extruder\d*$")


class KlipperImportError(ValueError):
    """A config this cannot make a printer from (the message says why and is shown to the user)."""


def _clean(value: float) -> int | float:
    value = round(float(value), 3)
    return int(value) if value == int(value) else value


def _number(section: Any, key: str) -> float | None:
    if not isinstance(section, dict):
        return None
    value = section.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _pair(section: Any, key: str) -> tuple[float, float] | None:
    """A "x, y" setting (as a list or as text)."""
    value = section.get(key) if isinstance(section, dict) else None
    parts = value.split(",") if isinstance(value, str) else value
    try:
        first, second = (float(part) for part in parts)  # type: ignore[union-attr]
    except (TypeError, ValueError):
        return None
    return first, second


class _Reading:
    """The form being made, with where each value came from and what to check."""

    def __init__(self, info: dict, settings: dict, objects: list) -> None:
        self.info = info if isinstance(info, dict) else {}
        self.settings = settings
        self.objects = {o for o in objects if isinstance(o, str)}
        self.form: dict[str, Any] = {"gcode_flavor": "klipper", "advanced": {}}
        self.findings: list[dict[str, Any]] = []
        self.notes: list[str] = []

    def set(self, field: str, value: Any, source: str) -> None:
        self.form[field] = value
        self.findings.append({"field": field, "value": value, "source": source})

    def advanced(self, key: str, value: str, source: str) -> None:
        self.form["advanced"][key] = value
        self.findings.append({"field": f"advanced.{key}", "value": value, "source": source})


def _range(reading: _Reading, axis: str) -> tuple[float, float]:
    name = f"stepper_{axis}"
    section = reading.settings.get(name)
    high = _number(section, "position_max")
    if high is None:
        raise KlipperImportError(
            f"The printer's config has no {name} with a position_max, so its bed size cannot be read."
        )
    return _number(section, "position_min") or 0.0, high


def _rectangular_bed(reading: _Reading) -> None:
    (x0, x1), (y0, y1), (_, z1) = (_range(reading, axis) for axis in "xyz")
    width, depth = x1 - x0, y1 - y0
    reading.set("shape", "rectangle", "kinematics " + str(reading.settings["printer"]["kinematics"]))
    reading.set("width", _clean(width), f"stepper_x position {_clean(x0)} to {_clean(x1)}")
    reading.set("depth", _clean(depth), f"stepper_y position {_clean(y0)} to {_clean(y1)}")
    reading.set("height", _clean(z1), f"stepper_z position_max {_clean(z1)}")
    if x0 < 0 and y0 < 0 and abs(x0 + x1) < 0.5 and abs(y0 + y1) < 0.5:
        reading.set("origin_centre", True, "the steppers' positions run from below zero to the same above it")
        reading.form["origin_x"] = reading.form["origin_y"] = 0
    else:
        reading.set("origin_x", _clean(x0), f"stepper_x position_min {_clean(x0)}")
        reading.set("origin_y", _clean(y0), f"stepper_y position_min {_clean(y0)}")
        reading.form["origin_centre"] = False
    _check_mesh(reading, {"X": (width, 0), "Y": (depth, 1)})


def _check_mesh(reading: _Reading, travel: dict[str, tuple[float, int]]) -> None:
    """Klipper's travel includes room a toolchanger parks in: where the bed mesh reaches says where the bed is."""
    mesh = reading.settings.get("bed_mesh")
    low, high = _pair(mesh, "mesh_min"), _pair(mesh, "mesh_max")
    if low is None or high is None:
        return
    for axis, (length, index) in travel.items():
        if high[index] - low[index] < _MESH_COVERAGE * length:
            reading.notes.append(
                f"Klipper lets the toolhead travel {_clean(length)} mm along {axis}, but its bed mesh only covers "
                f"{_clean(low[index])} to {_clean(high[index])}: the printable bed is probably smaller than {_clean(length)} mm. "
                f"Check the {axis} size."
            )


def _delta_bed(reading: _Reading) -> None:
    printer = reading.settings["printer"]
    radius = _number(printer, "print_radius")
    height = _number(reading.settings.get("stepper_a"), "position_endstop")
    if radius is None or height is None:
        raise KlipperImportError(
            "The delta printer's config needs a print_radius and a stepper_a position_endstop to read its bed."
        )
    reading.set("shape", "circle", "kinematics delta")
    reading.set("width", _clean(radius * 2), f"printer print_radius {_clean(radius)} (twice that)")
    reading.set("origin_centre", True, "a delta's bed is centred on its origin")
    reading.set("height", _clean(height), f"stepper_a position_endstop {_clean(height)}")
    reading.notes.append(
        "A delta's height is read from its endstop position: check it against the highest a print can be."
    )


def _bed(reading: _Reading) -> None:
    printer = reading.settings.get("printer")
    kinematics = printer.get("kinematics") if isinstance(printer, dict) else None
    if kinematics in _RECTANGULAR:
        _rectangular_bed(reading)
    elif kinematics == "delta":
        _delta_bed(reading)
    else:
        raise KlipperImportError(
            f"The printer's kinematics are {kinematics}, and a bed cannot be read for those: "
            "make the printer by hand, or start from a similar one in the list."
        )


def _extruders(reading: _Reading) -> None:
    names = sorted((n for n in reading.settings if _EXTRUDER_NAME.match(n)), key=lambda n: int(n[8:] or 0))
    nozzles = [_number(reading.settings[n], "nozzle_diameter") for n in names]
    known = [_clean(n) for n in nozzles if n is not None]
    if known:
        reading.set("nozzle_diameter", known[0], f"{names[0]} nozzle_diameter")
    if len(names) > 1:
        reading.notes.append(
            f"{len(names)} extruders found. The printer form sets one nozzle size ({known[0] if known else 'none read'} mm): "
            "a multi-material printer is better started from a similar printer in the list."
        )
    if len(set(known)) > 1:
        reading.notes.append(
            f"Their nozzles differ ({', '.join(f'{n:g}' for n in known)} mm): the first, {known[0]:g} mm, is used."
        )


def _motion(reading: _Reading) -> None:
    printer = reading.settings.get("printer")
    for field, key in (("max_speed", "max_velocity"), ("max_acceleration", "max_accel")):
        value = _number(printer, key)
        if value is not None:
            reading.set(field, _clean(value), f"printer {key}")


def _retraction(reading: _Reading) -> None:
    section = reading.settings.get("firmware_retraction")
    if section is None:
        return
    reading.set(
        "retraction_length", _clean(_number(section, "retract_length") or 0), "firmware_retraction retract_length"
    )
    reading.set(
        "retraction_speed", _clean(_number(section, "retract_speed") or 20), "firmware_retraction retract_speed"
    )
    reading.advanced(
        "use_firmware_retraction", "1", "the config has firmware_retraction, so the slicer asks for G10/G11"
    )


def _exclude_object(reading: _Reading) -> None:
    if "exclude_object" in reading.objects or "exclude_object" in reading.settings:
        reading.advanced("exclude_object", "1", "the printer has exclude_object, so the slicer marks each object")


def _macro(reading: _Reading, candidates: tuple[str, ...]) -> tuple[str, dict] | None:
    for name in candidates:
        section = reading.settings.get(f"gcode_macro {name}")
        if isinstance(section, dict):
            return name, section
    return None


def _parameters(gcode: object) -> list[str]:
    """The names a macro's code reads from its parameters (`params.BED_TEMP`), in order of first use."""
    found = [(a or b).upper() for a, b in _PARAMETER_PATTERN.findall(gcode if isinstance(gcode, str) else "")]
    return list(dict.fromkeys(found))


def _start_gcode(reading: _Reading) -> None:
    macro = _macro(reading, _START_MACROS)
    if macro is None:
        return
    name, section = macro
    parameters = _parameters(section.get("gcode"))
    arguments = [
        f"{param}={placeholder}"
        for names, placeholder in _PARAMETER_GROUPS
        for param in [next((p for p in parameters if p in names), None)]
        if param
    ]
    known = {p for names, _ in _PARAMETER_GROUPS for p in names}
    unknown = [p for p in parameters if p not in known]
    if unknown:
        reading.notes.append(
            f"The {name} macro also takes {', '.join(unknown)}, which are not filled in: add them to the start G-code if it needs them."
        )
    if not arguments:
        reading.notes.append(
            f"The {name} macro takes no temperatures, so the start G-code is left as the base printer's: "
            "check that it heats the bed and nozzle before the macro is called."
        )
        return
    reading.set("start_gcode", " ".join([name.upper(), *arguments]), f"the {name} macro's parameters")


def _end_gcode(reading: _Reading) -> None:
    macro = _macro(reading, _END_MACROS)
    if macro is not None:
        reading.set("end_gcode", macro[0].upper(), f"the {macro[0]} macro")


def import_from_klipper(info: dict, settings: dict, objects: list) -> dict[str, Any]:
    """The form a Klipper printer's config makes, `{form, findings, notes, klipper}`. Raises KlipperImportError when no
    bed can be read from it."""
    reading = _Reading(info, settings, objects)
    _bed(reading)
    _extruders(reading)
    _motion(reading)
    _retraction(reading)
    _exclude_object(reading)
    _start_gcode(reading)
    _end_gcode(reading)
    hostname = reading.info.get("hostname")
    reading.form["name"] = hostname if isinstance(hostname, str) and hostname else "Klipper printer"
    return {
        "form": reading.form,
        "findings": reading.findings,
        "notes": reading.notes,
        "klipper": {
            "hostname": hostname,
            "version": reading.info.get("software_version"),
            "state": reading.info.get("state"),
        },
    }
