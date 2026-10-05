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
