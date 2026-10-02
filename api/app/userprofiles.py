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
