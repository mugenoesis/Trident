"""Resin printers the user made (vendor "My printers"): a machine preset like the catalogue's, kept per user in the models volume.

<root>/<user>/<sha1(name)>.json holds {"preset": the slicer's machine preset, "form": the values the user entered, to edit them again}.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .config import settings

VENDOR = "My printers"


def _user_dir_name(user_id: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", user_id):
        return user_id
    return hashlib.sha1(user_id.encode(), usedforsecurity=False).hexdigest()


class UserResinPrinters:
    def __init__(self, root: Path | None = None):
        self._root = root

    def _user_dir(self, user_id: str) -> Path:
        root = self._root if self._root is not None else settings.models_dir / "_user_resin_printers"
        return root / _user_dir_name(user_id)

    def _file(self, user_id: str, name: str) -> Path:
        return self._user_dir(user_id) / f"{hashlib.sha1(name.encode(), usedforsecurity=False).hexdigest()}.json"

    def _read(self, user_id: str, name: str) -> dict[str, Any] | None:
        try:
            data = json.loads(self._file(user_id, name).read_text())
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def preset(self, user_id: str, name: str) -> dict[str, Any] | None:
        data = self._read(user_id, name)
        return data.get("preset") if data else None

    def form(self, user_id: str, name: str) -> dict[str, Any] | None:
        data = self._read(user_id, name)
        return data.get("form") if data else None

    def exists(self, user_id: str, name: str) -> bool:
        return self._file(user_id, name).is_file()

    def list(self, user_id: str) -> list[dict[str, Any]]:
        """The user's printers as catalogue entries (name, vendor, model, format, supported, nonsquare_pixels)."""
        directory = self._user_dir(user_id)
        out = []
        for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
            try:
                data = json.loads(path.read_text())
                preset, form = data["preset"], data["form"]
            except (OSError, ValueError, KeyError, TypeError):
                continue
            out.append(
                {
                    "name": preset["name"],
                    "vendor": VENDOR,
                    "model": preset["name"],
                    "format": preset["sla_archive_format"],
                    "supported": True,  # only formats the slicer writes are accepted when a printer is saved
                    "nonsquare_pixels": bool(form.get("rectangular_pixels")),
                }
            )
        return out

    def save(self, user_id: str, name: str, preset: dict[str, Any], form: dict[str, Any]) -> None:
        directory = self._user_dir(user_id)
        directory.mkdir(parents=True, exist_ok=True)
        self._file(user_id, name).write_text(json.dumps({"preset": preset, "form": form}))

    def delete(self, user_id: str, name: str) -> bool:
        path = self._file(user_id, name)
        if not path.is_file():
            return False
        path.unlink()
        return True


user_resin_printers = UserResinPrinters()


def _flag(value: bool) -> str:
    return "1" if value else "0"


def build_preset(form: dict[str, Any], base: dict[str, Any] | None) -> dict[str, Any]:
    """The slicer's machine preset for the values of the form, on top of the copied printer's preset (or a bare one)."""
    preset = dict(base) if base else {"display_orientation": "landscape"}
    for key in ("from", "inherits", "printer_settings_id", "printer_model", "name"):
        preset.pop(key, None)
    preset.update(
        {
            "type": "machine",
            "from": "user",
            "name": form["name"],
            "printer_settings_id": form["name"],
            "printer_model": form["name"],
            "printer_technology": "SLA",
            "display_width": f"{form['display_width_mm']:g}",
            "display_height": f"{form['display_height_mm']:g}",
            "display_pixels_x": str(form["pixels_x"]),
            "display_pixels_y": str(form["pixels_y"]),
            "printable_height": f"{form['build_height_mm']:g}",
            "sla_archive_format": form["format"],
        }
    )
    if form.get("mirror_x") is not None:
        preset["display_mirror_x"] = _flag(form["mirror_x"])
    if form.get("mirror_y") is not None:
        preset["display_mirror_y"] = _flag(form["mirror_y"])
    preset.setdefault("display_mirror_x", "0")
    preset.setdefault("display_mirror_y", "0")
    return preset
