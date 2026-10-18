"""Resins the user made (vendor "My resins"): material files like the built-in ones, kept per user in the models volume.

<root>/<user>/<sha1(name)>.json, in the engine's material format, so the slicer loads one exactly as it loads a built-in resin.
Saving under a name the user already has adds a row for that printer and layer height (or replaces the one that is there).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from .config import settings

VENDOR = "My resins"
SOURCE = "Made in Trident"


def _user_dir_name(user_id: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", user_id):
        return user_id
    return hashlib.sha1(user_id.encode(), usedforsecurity=False).hexdigest()


class UserResins:
    def __init__(self, root: Path | None = None):
        self._root = root

    def _user_dir(self, user_id: str) -> Path:
        root = self._root if self._root is not None else settings.models_dir / "_user_resins"
        return root / _user_dir_name(user_id)

    def path(self, user_id: str, name: str) -> Path | None:
        path = self._user_dir(user_id) / f"{hashlib.sha1(name.encode(), usedforsecurity=False).hexdigest()}.json"
        return path if path.is_file() else None

    def get(self, user_id: str, name: str) -> dict[str, Any] | None:
        path = self.path(user_id, name)
        if path is None:
            return None
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def list(self, user_id: str) -> list[dict[str, Any]]:
        directory = self._user_dir(user_id)
        out = []
        for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
            try:
                data = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and isinstance(data.get("name"), str):
                out.append({k: data.get(k, "") for k in ("name", "vendor", "family", "color", "resin_type")})
        return out

    def save(
        self,
        user_id: str,
        name: str,
        printer: str,
        layer_height: float,
        values: dict[str, float],
        based_on: dict[str, Any] | None,
        *,
        resin_type: str | None = None,
        source: str = SOURCE,
    ) -> dict[str, Any]:
        material = self.get(user_id, name) or {
            "type": "material",
            "name": name,
            "vendor": VENDOR,
            "resin_type": resin_type if resin_type is not None else (based_on or {}).get("resin_type", ""),
            "family": (based_on or {}).get("family", ""),
            "color": (based_on or {}).get("color", ""),
            "settings": [],
        }
        row: dict[str, Any] = {
            "printers": [printer],
            "layer_height": layer_height,
            **values,
            "source": source,
            "retrieved": date.today().isoformat(),
            "notes": f"Started from {based_on['name']}." if based_on else "",
        }
        material["settings"] = [
            r
            for r in material["settings"]
            if not (r.get("printers") == [printer] and abs(float(r.get("layer_height", -1)) - layer_height) < 0.0005)
        ] + [row]
        directory = self._user_dir(user_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{hashlib.sha1(name.encode(), usedforsecurity=False).hexdigest()}.json").write_text(
            json.dumps(material)
        )
        return {k: material.get(k, "") for k in ("name", "vendor", "family", "color", "resin_type")}

    def delete(self, user_id: str, name: str) -> bool:
        path = self.path(user_id, name)
        if path is None:
            return False
        path.unlink()
        return True


user_resins = UserResins()
