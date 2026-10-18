"""Importing a resin profile made for another slicer, as the numbers of a row of a resin of the user's own.

A port of the engine's importers (Pseudorca src/libslic3r/ResinMaterial.cpp: resin_material_from_chitubox_cfg and
resin_materials_from_prusaslicer_ini); tests/test_resin_import.py runs them on the engine's own sample files with the engine's expected
numbers, so the two stay in step. Each importer gives {"name", "resin_type" (maybe), "row": {...}}; the printer, the source and the
notes of the row are added when it is saved (resin_user.py).
"""

from __future__ import annotations

import re
from typing import Any


class ImportProblem(ValueError):
    """A file that cannot be imported, with the reason in words the user can act on."""


_NUMBER = re.compile(r"\s*[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _num(text: str | None) -> float | None:
    """The number a text starts with (like C's strtod: "8.0 mm" is 8), or None."""
    match = _NUMBER.match(text) if text else None
    return float(match.group()) if match else None


def _tidy(value: float) -> float | int:
    return int(value) if value == int(value) else value


def _key_values(text: str, sep: str) -> list[tuple[str, str]]:
    """The "key<sep>value" lines of a text (the first separator splits; blank lines and # or ; comments are skipped)."""
    out = []
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if sep not in line or not line or line[0] in "#;":
            continue
        key, _, value = line.partition(sep)
        out.append((key.strip(), value.strip()))
    return out


def from_chitubox_cfg(text: str) -> dict[str, Any]:
    """A Chitubox resin profile (.cfg: "key:value" lines)."""
    kv = dict(_key_values(text, ":"))
    if "normalExposureTime" not in kv or "layerHeight" not in kv:
        raise ImportProblem(
            "This does not look like a Chitubox resin profile (normalExposureTime or layerHeight is missing)."
        )
    layer_height = _num(kv["layerHeight"])
    if layer_height is None:
        raise ImportProblem("The layer height of the profile is not a number.")
    row: dict[str, Any] = {"layer_height": layer_height}
    for key, name, whole in (
        ("normalExposureTime", "exposure_time", False),
        ("bottomLayExposureTime", "initial_exposure_time", False),
        ("bottomLayCount", "bottom_layer_count", True),
        ("normalLayerLiftHeight", "lift_distance", False),
        ("normalLayerLiftSpeed", "lift_speed", False),
        ("normalDropSpeed", "retract_speed", False),
        ("lightOffTime", "delay_before_exposure", False),
        ("normalLightIntensityPWM", "light_pwm", True),
    ):
        value = _num(kv.get(key))
        if value is not None:
            row[name] = int(value) if whole else _tidy(value)
    density = _num(kv.get("resinDensity"))
    if density and density > 0:
        row["material_density"] = density
    price = _num(kv.get("resinPrice"))
    if kv.get("resinUnit", "").endswith("/L") and price and price > 0:
        # a price per litre is a bottle of one litre
        row["bottle_volume"] = 1000
        row["bottle_cost"] = _tidy(price)
    material: dict[str, Any] = {"name": kv.get("currProfile") or "Imported resin", "row": row}
    if kv.get("__resin"):
        material["resin_type"] = kv["__resin"]
    return material


def _ini_sections(text: str) -> tuple[dict[str, dict[str, str]], list[str]]:
    sections: dict[str, dict[str, str]] = {}
    order: list[str] = []
    current = ""
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if line.startswith("[sla_material:") and line.endswith("]"):
            current = line[len("[sla_material:") : -1]
            if current not in sections:
                order.append(current)
            sections.setdefault(current, {})
        elif line.startswith("["):
            current = ""
        elif current:
            pairs = _key_values(line, "=")
            if pairs:
                sections[current][pairs[0][0]] = pairs[0][1]
    return sections, order


def _flatten(sections: dict[str, dict[str, str]], name: str, depth: int = 0) -> dict[str, str]:
    """The values of a section with its parents' underneath (a loop of "inherits" is cut)."""
    section = sections.get(name)
    if section is None or depth > 8:
        return {}
    out: dict[str, str] = {}
    for parent in section.get("inherits", "").split(","):
        if parent.strip():
            out.update(_flatten(sections, parent.strip(), depth + 1))
    out.update(section)
    return out


def _layer_height(values: dict[str, str]) -> float | None:
    condition = values.get("compatible_prints_condition", "")
    at = condition.find("layer_height ==")
    height = _num(condition[at + len("layer_height ==") :]) if at >= 0 else None
    return height if height and height > 0 else _num(values.get("initial_layer_height"))


def _lift_from_notes(notes: str, row: dict[str, Any]) -> None:
    """The Anycubic profiles keep the lift in the notes ("LIFT_DISTANCE=8.0\\nLIFT_SPEED=2.5": mm and mm/s)."""
    pairs = dict(_key_values(notes.replace("\\n", "\n"), "="))
    for key, name, factor in (
        ("LIFT_DISTANCE", "lift_distance", 1),
        ("LIFT_SPEED", "lift_speed", 60),
        ("RETRACT_SPEED", "retract_speed", 60),
        ("DELAY_BEFORE_EXPOSURE", "delay_before_exposure", 1),
    ):
        value = _num(pairs.get(key))
        if value is not None:
            row[name] = _tidy(value * factor)


def _prusa_material(name: str, values: dict[str, str]) -> tuple[dict[str, Any] | None, str]:
    """The material of one section with its inherited values, or (None, why not): "" for a section that is no resin."""
    exposure, bottom = _num(values.get("exposure_time")), _num(values.get("initial_exposure_time"))
    if exposure is None or bottom is None:
        return None, ""
    height = _layer_height(values)
    if height is None:
        return None, f"The layer height of {name!r} could not be found."
    row: dict[str, Any] = {
        "layer_height": height,
        "exposure_time": _tidy(exposure),
        "initial_exposure_time": _tidy(bottom),
    }
    _lift_from_notes(values.get("material_notes", ""), row)
    for key in ("bottle_volume", "bottle_weight", "bottle_cost"):
        value = _num(values.get(key))
        if value and value > 0:
            row[key] = _tidy(value)
    material: dict[str, Any] = {"name": name, "row": row}
    if values.get("material_type"):
        material["resin_type"] = values["material_type"].lower()
    return material, ""


def from_prusaslicer_ini(text: str) -> list[dict[str, Any]]:
    """PrusaSlicer profile text with [sla_material:...] sections: a material for each concrete one (not the "*common*" ones)."""
    sections, order = _ini_sections(text)
    materials: list[dict[str, Any]] = []
    last_problem = ""
    for name in order:
        if not name or name.startswith("*"):
            continue
        material, problem = _prusa_material(name, _flatten(sections, name))
        last_problem = problem or last_problem
        if material:
            materials.append(material)
    if not materials:
        raise ImportProblem(last_problem or "No PrusaSlicer SLA material with an exposure time was found.")
    return materials
