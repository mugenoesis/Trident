"""Printer / filament / process presets a user brings themselves.

Mirrors what OrcaSlicer's own File > Import > Import Configs accepts: a
single preset .json, or a zip-style bundle (.zip, .orca_printer,
.orca_filament, .orca_bundle) holding several of them (any folder layout; an
optional bundle_structure.json is metadata and ignored). A preset is a flat
JSON object with a "name", a "version" and an optional "inherits" naming the
(built-in) preset it builds on.

Stored per user, outside the read-only built-in catalog (profiles.py merges
them in as the vendor IMPORTED_VENDOR). Nothing here trusts the upload: names
are checked, sizes capped, and the print-host credential keys are dropped
(this app keeps its own printer connection settings).
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .blocked_settings import PRINTHOST_KEYS
from .config import settings

IMPORTED_VENDOR = "My profiles"

_MAX_FILE_BYTES = 5 * 1024 * 1024
_MAX_ZIP_UNCOMPRESSED = 25 * 1024 * 1024
_MAX_PRESETS_PER_UPLOAD = 200
_KINDS = ("machine", "process", "filament")
# Orca decides a preset's kind from which *_settings_id key it carries.
_KIND_BY_ID_KEY = {
    "printer_settings_id": "machine",
    "print_settings_id": "process",
    "filament_settings_id": "filament",
}
_BUNDLE_SUFFIXES = (".zip", ".orca_printer", ".orca_filament", ".orca_bundle")
_BUNDLE_METADATA = "bundle_structure.json"


@dataclass
class ParsedPreset:
    kind: str
    name: str
    data: dict


@dataclass
class ImportIssue:
    file: str
    name: str | None
    reason: str


def valid_name(name: object) -> bool:
    """A preset name is shown in the UI and used in file names elsewhere, so
    it must be plain text: no path separators, no control characters."""
    return (
        isinstance(name, str)
        and 0 < len(name) <= 120
        and name == name.strip()
        and not name.startswith(".")
        and re.search(r"[\x00-\x1f/\\]", name) is None
        and ".." not in name
    )


def _parse_one(filename: str, raw: bytes) -> tuple[ParsedPreset | None, ImportIssue | None]:
    if len(raw) > _MAX_FILE_BYTES:
        return None, ImportIssue(filename, None, "File is too large for a profile")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, ImportIssue(filename, None, "Not a valid JSON profile")
    if not isinstance(data, dict):
        return None, ImportIssue(filename, None, "Not a profile (expected a JSON object)")
    name = data.get("name")
    if not valid_name(name):
        return None, ImportIssue(filename, name if isinstance(name, str) else None, "Profile has no usable name")
    kind = data.get("type") if data.get("type") in _KINDS else None
    if kind is None:
        kind = next((k for key, k in _KIND_BY_ID_KEY.items() if key in data), None)
    if kind is None:
        return None, ImportIssue(filename, name, "Can't tell whether this is a printer, filament or process profile")
    cleaned = {k: v for k, v in data.items() if k not in PRINTHOST_KEYS}
    cleaned["type"] = kind
    cleaned["from"] = "User"
    cleaned.setdefault("version", "1.0.0.0")
    # An imported leaf is always selectable, whatever the source file said.
    cleaned["instantiation"] = "true"
    return ParsedPreset(kind, name, cleaned), None


def parse_upload(filename: str, raw: bytes) -> tuple[list[ParsedPreset], list[ImportIssue]]:
    """Presets found in one uploaded file, plus what could not be read."""
    lower = filename.lower()
    if not lower.endswith(_BUNDLE_SUFFIXES):
        preset, issue = _parse_one(filename, raw)
        return ([preset] if preset else []), ([issue] if issue else [])
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return [], [ImportIssue(filename, None, "Not a valid bundle (zip) file")]
    presets: list[ParsedPreset] = []
    issues: list[ImportIssue] = []
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if sum(i.file_size for i in infos) > _MAX_ZIP_UNCOMPRESSED:
        return [], [ImportIssue(filename, None, "Bundle is too large")]
    for info in infos:
        base = info.filename.replace("\\", "/").rsplit("/", 1)[-1]
        if base == _BUNDLE_METADATA or not base.lower().endswith(".json"):
            continue
        if len(presets) >= _MAX_PRESETS_PER_UPLOAD:
            issues.append(ImportIssue(filename, None, f"Only the first {_MAX_PRESETS_PER_UPLOAD} profiles were read"))
            break
        preset, issue = _parse_one(f"{filename}/{base}", zf.read(info))
        if preset:
            presets.append(preset)
        if issue:
            issues.append(issue)
    if not presets and not issues:
        issues.append(ImportIssue(filename, None, "No profiles found in this bundle"))
    return presets, issues


class UserProfileStore:
    """Imported presets on disk: <models_dir>/_user_profiles/<user>/<kind>/<sha1(name)>.json.

    Lives in the models volume so it survives a container replacement.
    """

    def _root(self) -> Path:
        return settings.models_dir / "_user_profiles"

    @staticmethod
    def _user_dir_name(user_id: str) -> str:
        return user_id if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", user_id) else hashlib.sha1(user_id.encode()).hexdigest()

    def _path(self, user_id: str, kind: str, name: str) -> Path:
        digest = hashlib.sha1(name.encode()).hexdigest()
        return self._root() / self._user_dir_name(user_id) / kind / f"{digest}.json"

    def save(self, user_id: str, preset: ParsedPreset) -> None:
        path = self._path(user_id, preset.kind, preset.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(preset.data))

    def delete(self, user_id: str, kind: str, name: str) -> bool:
        path = self._path(user_id, kind, name)
        if not path.is_file():
            return False
        path.unlink()
        return True

    def load_all(self, user_id: str) -> dict[tuple[str, str], dict]:
        """(kind, name) -> raw preset data, for one user."""
        out: dict[tuple[str, str], dict] = {}
        base = self._root() / self._user_dir_name(user_id)
        for kind in _KINDS:
            for path in sorted((base / kind).glob("*.json")) if (base / kind).is_dir() else []:
                try:
                    data = json.loads(path.read_text())
                except (OSError, json.JSONDecodeError):
                    continue
                if isinstance(data, dict) and valid_name(data.get("name")):
                    out[(kind, data["name"])] = data
        return out


store = UserProfileStore()


# ---------------------------------------------------------------------------
# Materials made in the app (the "New material" form): a copy of an existing
# filament preset with the settings people actually change overridden. Stored
# like an import (a preset with an `inherits` pointer), so everything else is
# inherited from the base and the material behaves exactly like it.

MATERIAL_TYPES = (
    "PLA", "PLA-CF", "PETG", "PETG-CF", "ABS", "ASA", "PC", "PA", "PA-CF", "PET", "PET-CF",
    "TPU", "PVA", "HIPS", "PP", "PPS", "PEEK", "Other",
)

# Bed temperature keys, one per build plate type (the first-layer twin is kept equal).
PLATE_TEMP_KEYS = (
    "cool_plate_temp", "eng_plate_temp", "hot_plate_temp", "textured_plate_temp",
    "textured_cool_plate_temp", "supertack_plate_temp",
)

# key -> (lowest, highest, whole number?). Every one is a per-extruder list in the preset.
_MATERIAL_NUMBERS: dict[str, tuple[float, float, bool]] = {
    "nozzle_temperature": (0, 500, True),
    "nozzle_temperature_initial_layer": (0, 500, True),
    "nozzle_temperature_range_low": (0, 500, True),
    "nozzle_temperature_range_high": (0, 500, True),
    "filament_flow_ratio": (0.5, 1.5, False),
    "filament_max_volumetric_speed": (0.1, 100, False),
    "filament_density": (0.1, 25, False),
    "filament_diameter": (0.5, 5, False),
    "fan_min_speed": (0, 100, True),
    "fan_max_speed": (0, 100, True),
    **{k: (0, 200, True) for k in PLATE_TEMP_KEYS},
}


class MaterialError(ValueError):
    """A material form value that is not acceptable (the message is shown to the user)."""


def _fmt(value: float, whole: bool) -> str:
    return str(int(round(value))) if whole else format(value, "g")


def _list_like(base: dict, key: str, text: str) -> list[str]:
    """`text` repeated to the length of the base preset's list for `key` (one entry per extruder variant)."""
    current = base.get(key)
    count = len(current) if isinstance(current, list) and current else 1
    return [text] * count


def build_material_overrides(base: dict, form: dict) -> dict:
    """The preset keys a material form sets, validated, in the list-of-strings
    shape presets use. `base` is the resolved preset the material is based on
    (only used for list lengths and which plate keys it has); `form` holds the
    form's own values: name-independent settings only."""
    out: dict = {}
    ftype = str(form.get("filament_type", "")).strip()
    if not ftype or len(ftype) > 20 or re.search(r"[\x00-\x1f\"\\]", ftype):
        raise MaterialError("Choose a material type")
    out["filament_type"] = _list_like(base, "filament_type", ftype)
    vendor = str(form.get("filament_vendor", "") or "").strip()
    if len(vendor) > 60 or re.search(r"[\x00-\x1f\"\\]", vendor):
        raise MaterialError("The brand is not valid")
    out["filament_vendor"] = _list_like(base, "filament_vendor", vendor or "Generic")

    labels = {
        "nozzle_temperature": "Nozzle temperature", "nozzle_temperature_initial_layer": "First layer temperature",
        "nozzle_temperature_range_low": "Lowest nozzle temperature", "nozzle_temperature_range_high": "Highest nozzle temperature",
        "filament_flow_ratio": "Flow ratio", "filament_max_volumetric_speed": "Max volumetric speed",
        "filament_density": "Density", "filament_diameter": "Diameter", "fan_min_speed": "Minimum fan speed",
        "fan_max_speed": "Maximum fan speed",
    }
    values: dict[str, float] = {}
    for key, (lo, hi, whole) in _MATERIAL_NUMBERS.items():
        if key not in form or form[key] is None:
            if key in PLATE_TEMP_KEYS:
                continue  # plate types the form did not offer keep the base value
            raise MaterialError(f"{labels.get(key, key)} is missing")
        try:
            number = float(form[key])
        except (TypeError, ValueError):
            raise MaterialError(f"{labels.get(key, key.replace('_', ' '))} must be a number") from None
        if number != number or number in (float("inf"), float("-inf")) or not lo <= number <= hi:
            raise MaterialError(f"{labels.get(key, key.replace('_', ' '))} must be between {lo:g} and {hi:g}")
        values[key] = number
    if values["nozzle_temperature_range_low"] > values["nozzle_temperature_range_high"]:
        raise MaterialError("The lowest nozzle temperature is above the highest")
    if values["fan_min_speed"] > values["fan_max_speed"]:
        raise MaterialError("The minimum fan speed is above the maximum")
    for key, number in values.items():
        whole = _MATERIAL_NUMBERS[key][2]
        text = _fmt(number, whole)
        out[key] = _list_like(base, key, text)
        if key in PLATE_TEMP_KEYS:
            out[key + "_initial_layer"] = _list_like(base, key + "_initial_layer", text)
    return out


def compatible_printer_names(data: dict) -> list[str]:
    """The printer names a preset is limited to (empty = every printer)."""
    value = data.get("compatible_printers")
    if isinstance(value, str):
        value = [value]
    return [str(v) for v in value or [] if str(v).strip()]


def build_material_preset(name: str, inherits: str, base: dict, form: dict, existing: dict | None = None) -> ParsedPreset:
    """The preset to store: the form's overrides over `existing` (when editing,
    so other keys the preset already had are kept) pointing at `inherits`."""
    if not valid_name(name):
        raise MaterialError("The name is not valid: it must be plain text without slashes")
    data = dict(existing or {})
    data.update(build_material_overrides(base, form))
    printers = form.get("printers")
    if printers is None:
        # Editing without a choice keeps what is stored; a new material is for every printer.
        printers = compatible_printer_names(existing) if existing else []
    printers = list(dict.fromkeys(str(x).strip() for x in printers if str(x).strip()))
    data.update(
        {
            "name": name,
            "type": "filament",
            "from": "User",
            "instantiation": "true",
            "inherits": inherits,
            "version": data.get("version") or "1.0.0.0",
            # Set explicitly: the base's own printer whitelist must not leak into the copy.
            "compatible_printers": printers,
            "compatible_printers_condition": "",
        }
    )
    return ParsedPreset("filament", name, data)


class MaterialConflict(MaterialError):
    """The name is already used (by a built-in material or one of the user's own)."""


class MaterialNotFound(MaterialError):
    """No such material (to edit, or to base a new one on)."""


# ---------------------------------------------------------------------------
# Printers made in the app (the "New printer" form): a machine preset that
# inherits from a printer the user copies, or from one of the slicer's generic
# printers, with the settings people change overridden. Stored like an import.

GENERIC_PRINTER_BASES = {
    "klipper": "MyKlipper 0.4 nozzle",
    "reprapfirmware": "MyRRF 0.4 nozzle",
    "repetier": "MyRepetier 0.4 nozzle",
}
GENERIC_MARLIN_BASE = "MyMarlin 0.4 nozzle"
GENERIC_BELT_BASE = "MyBeltPrinter 0.4 nozzle"
# How long an endless belt is drawn and sized as when the printer has no real limit.
ENDLESS_BELT_LENGTH_MM = 2000.0

# Keys the form sets itself; every other printer key a preset holds is an "advanced" override.
PRINTER_MANAGED_KEYS = frozenset(
    {
        "printable_area", "printable_height", "belt_printer", "belt_printer_infinite_y", "belt_slice_rotation_angle",
        "nozzle_diameter", "nozzle_type", "gcode_flavor", "machine_start_gcode", "machine_end_gcode",
        "machine_max_speed_x", "machine_max_speed_y", "machine_max_acceleration_x", "machine_max_acceleration_y",
        "machine_max_acceleration_extruding", "machine_max_acceleration_travel", "retraction_length",
        "retraction_speed", "deretraction_speed", "z_hop", "auxiliary_fan", "default_print_profile",
        "default_filament_profile",
    }
)
_PRINTER_META_KEYS = frozenset({"name", "type", "from", "instantiation", "inherits", "version"})


class PrinterError(ValueError):
    """A printer form value that is not acceptable (the message is shown to the user)."""


class PrinterConflict(PrinterError):
    """The name is already used (by a built-in printer or one of the user's own)."""


class PrinterNotFound(PrinterError):
    """No such printer (to edit, or to base a new one on)."""


def generic_printer_base(flavour: str | None, belt: bool) -> str:
    """The slicer's generic printer to start from when the user copies none."""
    if belt:
        return GENERIC_BELT_BASE
    return GENERIC_PRINTER_BASES.get((flavour or "marlin").lower(), GENERIC_MARLIN_BASE)


_enum_cache: dict[str, list[str] | None] = {}


def _allowed_values(key: str) -> list[str] | None:
    """The values the slicer accepts for an enumerated setting, or None when it cannot say."""
    if key not in _enum_cache:
        values = None
        try:
            from . import cli_runner  # imported here: cli_runner needs this module

            for item in cli_runner.fetch_help_json() or []:
                if item.get("key") == key:
                    values = item.get("enum_values")
                    break
        except Exception:  # noqa: BLE001 - validation is best effort
            values = None
        _enum_cache[key] = values
    return _enum_cache[key]


def _number(form: dict, key: str, label: str, lo: float, hi: float) -> float | None:
    value = form.get(key)
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise PrinterError(f"{label} must be a number") from None
    if number != number or number in (float("inf"), float("-inf")) or not lo <= number <= hi:
        raise PrinterError(f"{label} must be between {lo:g} and {hi:g}")
    return number


def _text(form: dict, key: str, label: str, limit: int = 50000) -> str | None:
    value = form.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise PrinterError(f"{label} is not valid")
    return value


def _area_points(shape: str, x0: float, y0: float, width: float, depth: float) -> list[str]:
    """printable_area as the "XxY" corner strings presets use; a circle is a many-sided polygon."""
    if shape == "circle":
        import math

        radius = width / 2
        cx, cy = x0 + radius, y0 + radius
        return [
            f"{_fmt(cx + radius * math.cos(2 * math.pi * i / 48), False)}x{_fmt(cy + radius * math.sin(2 * math.pi * i / 48), False)}"
            for i in range(48)
        ]
    x1, y1 = x0 + width, y0 + depth
    return [f"{_fmt(x0, False)}x{_fmt(y0, False)}", f"{_fmt(x1, False)}x{_fmt(y0, False)}", f"{_fmt(x1, False)}x{_fmt(y1, False)}", f"{_fmt(x0, False)}x{_fmt(y1, False)}"]


def _encode_extra(base_value: object, text: str) -> object:
    """An advanced setting's text in the shape the base preset keeps it: a list of strings when the base's
    value is a list (comma separated), otherwise one string."""
    if isinstance(base_value, list):
        return [part.strip() for part in text.split(",")] if text.strip() else []
    return text


def build_printer_overrides(base: dict, form: dict) -> dict:
    """The preset keys a printer form sets, validated, in the shape presets use. `base` is the resolved preset
    the printer is based on (for list lengths and the belt state); a value the form leaves out is inherited."""
    out: dict = {}
    flavour = _text(form, "gcode_flavor", "The G-code flavour", 40)
    if flavour:
        allowed = _allowed_values("gcode_flavor")
        if allowed is not None and flavour not in allowed:
            raise PrinterError("Choose one of the listed G-code flavours")
        out["gcode_flavor"] = flavour
    nozzle_type = _text(form, "nozzle_type", "The nozzle type", 40)
    if nozzle_type:
        allowed = _allowed_values("nozzle_type")
        if allowed is not None and nozzle_type not in allowed:
            raise PrinterError("Choose one of the listed nozzle types")
        out["nozzle_type"] = _list_like(base, "nozzle_type", nozzle_type)

    nozzle = _number(form, "nozzle_diameter", "The nozzle diameter", 0.1, 2.0)
    if nozzle is not None:
        out["nozzle_diameter"] = _list_like(base, "nozzle_diameter", _fmt(nozzle, False))

    # Build plate. A belt printer's length is the belt's: endless (drawn as a long plate, no limit when slicing)
    # or a real length.
    belt = form.get("belt")
    belt = bool(base.get("belt_printer") in ("1", 1, True)) if belt is None else bool(belt)
    shape = form.get("shape") or "rectangle"
    if shape not in ("rectangle", "circle"):
        raise PrinterError("The bed shape must be a rectangle or a circle")
    width = _number(form, "width", "The bed width", 10, 5000)
    depth = _number(form, "depth", "The bed depth", 10, 5000)
    height = _number(form, "height", "The maximum height", 10, 5000)
    if belt:
        endless = form.get("belt_endless", True)
        length = ENDLESS_BELT_LENGTH_MM if endless else _number(form, "belt_length", "The belt length", 10, 100000)
        if length is None:
            raise PrinterError("Give the belt length, or tick Endless belt")
        depth = length
        out["belt_printer"] = "1"
        out["belt_printer_infinite_y"] = "1" if endless else "0"
        angle = _number(form, "belt_angle", "The belt angle", 1, 89)
        if angle is not None:
            out["belt_slice_rotation_angle"] = _fmt(angle, False)
    elif form.get("belt") is not None:
        out["belt_printer"] = "0"
        out["belt_printer_infinite_y"] = "0"
    if width is not None and (depth is not None or shape == "circle"):
        if form.get("origin_centre"):
            span = width if shape == "circle" else depth
            x0, y0 = -width / 2, -(span or 0) / 2
        else:
            x0 = _number(form, "origin_x", "The origin X offset", -5000, 5000) or 0.0
            y0 = _number(form, "origin_y", "The origin Y offset", -5000, 5000) or 0.0
        out["printable_area"] = _area_points(shape, x0, y0, width, depth or width)
    if height is not None:
        out["printable_height"] = _fmt(height, False)

    start = _text(form, "start_gcode", "The start G-code")
    if start is not None:
        if not start.strip():
            raise PrinterError("The start G-code can't be empty")
        out["machine_start_gcode"] = start
    end = _text(form, "end_gcode", "The end G-code")
    if end is not None:
        out["machine_end_gcode"] = end

    speed = _number(form, "max_speed", "The maximum speed", 1, 20000)
    if speed is not None:
        for key in ("machine_max_speed_x", "machine_max_speed_y"):
            out[key] = _list_like(base, key, _fmt(speed, False))
    accel = _number(form, "max_acceleration", "The maximum acceleration", 1, 200000)
    if accel is not None:
        for key in ("machine_max_acceleration_x", "machine_max_acceleration_y", "machine_max_acceleration_extruding", "machine_max_acceleration_travel"):
            out[key] = _list_like(base, key, _fmt(accel, False))
    retract = _number(form, "retraction_length", "The retraction length", 0, 100)
    if retract is not None:
        out["retraction_length"] = _list_like(base, "retraction_length", _fmt(retract, False))
    retract_speed = _number(form, "retraction_speed", "The retraction speed", 1, 1000)
    if retract_speed is not None:
        out["retraction_speed"] = _list_like(base, "retraction_speed", _fmt(retract_speed, False))
        out["deretraction_speed"] = _list_like(base, "deretraction_speed", _fmt(retract_speed, False))
    z_hop = _number(form, "z_hop", "The Z hop", 0, 50)
    if z_hop is not None:
        out["z_hop"] = _list_like(base, "z_hop", _fmt(z_hop, False))
    if form.get("auxiliary_fan") is not None:
        out["auxiliary_fan"] = "1" if form["auxiliary_fan"] else "0"

    process = _text(form, "default_process", "The default process", 200)
    if process:
        out["default_print_profile"] = process
    material = _text(form, "default_material", "The default material", 200)
    if material:
        out["default_filament_profile"] = [material]
    return out


def build_printer_preset(
    name: str, inherits: str, base: dict, form: dict, existing: dict | None = None
) -> ParsedPreset:
    """The preset to store: the form's overrides (and its advanced settings) over `existing` when editing, pointing
    at `inherits`. Advanced settings the form no longer lists are dropped; settings that are not printer
    settings, kept from an import, are left alone."""
    from .printer_keys import PRINTER_KEYS

    if not valid_name(name):
        raise PrinterError("The name is not valid: it must be plain text without slashes")
    advanced = form.get("advanced") or {}
    if not isinstance(advanced, dict) or len(advanced) > 400:
        raise PrinterError("The advanced settings are not valid")
    extra_allowed = PRINTER_KEYS - PRINTER_MANAGED_KEYS - _PRINTER_META_KEYS
    for key, value in advanced.items():
        if key not in extra_allowed:
            raise PrinterError(f"'{key}' is not a printer setting that can be added here")
        if not isinstance(value, str) or len(value) > 50000 or "\x00" in value:
            raise PrinterError(f"The value of '{key}' is not valid")
    data = {k: v for k, v in (existing or {}).items() if k not in extra_allowed}
    data.update(build_printer_overrides(base, form))
    for key, value in advanced.items():
        data[key] = _encode_extra(base.get(key), value)
    data.update(
        {
            "name": name,
            "type": "machine",
            "from": "User",
            "instantiation": "true",
            "inherits": inherits,
            "version": data.get("version") or "1.0.0.0",
        }
    )
    return ParsedPreset("machine", name, data)


def build_export(user_id: str, items: list[tuple[str, str]]) -> tuple[bytes, str]:
    """A zip of the user's own presets, in the layout desktop OrcaSlicer reads (bundle_structure.json and a
    folder per kind), and the file name to offer: .orca_printer for one printer, .orca_filament for one
    material, .orca_bundle otherwise."""
    if not items:
        raise PrinterError("Choose something to export")
    stored = store.load_all(user_id)
    folders = {"machine": "printer", "filament": "filament", "process": "process"}
    buffer = io.BytesIO()
    names: dict[str, list[str]] = {"machine": [], "filament": [], "process": []}
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for kind, name in dict.fromkeys(items):
            data = stored.get((kind, name))
            if data is None:
                raise PrinterNotFound(f"'{name}' is not one of your profiles")
            safe = re.sub(r"[^\w .@()+-]", "_", name)
            zf.writestr(f"{folders[kind]}/{safe}.json", json.dumps(data, indent=4))
            names[kind].append(name)
        zf.writestr(
            _BUNDLE_METADATA,
            json.dumps(
                {
                    "bundle_id": str(uuid.uuid4()),
                    "bundle_type": "Trident export",
                    "version": "1.0.0.0",
                    "printer_preset_name": names["machine"],
                    "filament_preset_name": names["filament"],
                    "process_preset_name": names["process"],
                },
                indent=4,
            ),
        )
    only = [(k, n) for k, ns in names.items() for n in ns]
    if len(only) == 1 and only[0][0] == "machine":
        suffix, stem = ".orca_printer", only[0][1]
    elif len(only) == 1 and only[0][0] == "filament":
        suffix, stem = ".orca_filament", only[0][1]
    else:
        suffix, stem = ".orca_bundle", "trident-profiles"
    return buffer.getvalue(), re.sub(r"[^\w .@()+-]", "_", stem) + suffix
