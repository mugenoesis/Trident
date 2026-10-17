"""Resin (MSLA) printers and resins: the catalogue the slicing engine ships in resources/resin.

Layout (see the engine's docs/resin-materials.md and resources/resin):
  index.json            the printers: vendor, model, file (a machine preset), format, supported, ...
  printers/<Vendor>/<Model>.json
  materials-index.json  the resins: name, vendor, family, color, resin_type, file, rows
  materials/<Vendor>/<Resin>.json   {"type": "material", "name", "settings": [rows for printers and a layer height]}

choose_row() picks the row of a resin for a printer and layer height the way the engine does at slice time
(libslic3r/ResinMaterial.cpp, choose_resin_material), so the numbers shown before slicing are the ones used.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from .config import settings
from .resin_user import user_resins

logger = logging.getLogger(__name__)

# The settings a material row may hold (libslic3r/ResinMaterial.cpp, settings_keys).
ROW_KEYS = (
    "exposure_time",
    "initial_exposure_time",
    "bottom_layer_count",
    "faded_layers",
    "lift_distance",
    "lift_speed",
    "retract_speed",
    "delay_before_exposure",
    "delay_after_exposure",
    "light_pwm",
    "material_density",
    "bottle_volume",
    "bottle_weight",
    "bottle_cost",
)

PRINTER_EXACT, PRINTER_VENDOR, PRINTER_ANY = "exact", "vendor", "any"


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _printer_score(entry: str, names: list[str]) -> int:
    """3: the printer's name, 2: "Vendor *", 1: "*", 0: no match."""
    if entry == "*":
        return 1
    e = _normalise(entry)
    if entry.endswith("*"):
        prefix = _normalise(entry[:-1])
        return 2 if prefix and any(_normalise(n).startswith(prefix) for n in names) else 0
    for name in names:
        n = _normalise(name)
        if not n:
            continue
        # "Mars 3" is the printer's model and the row says "Elegoo Mars 3": one ends with the other
        if n == e or e.endswith(n) or n.endswith(e):
            return 3
    return 0


def _row_score(row: dict[str, Any], printer_names: list[str]) -> int:
    """How well a row's printer list fits the printer: 3, 2, 1 as in _printer_score, 0 for no fit; a row naming no printers fits any."""
    printers = row.get("printers")
    if not isinstance(printers, list):
        return 1
    return max((_printer_score(p, printer_names) for p in printers if isinstance(p, str)), default=0)


def check_printer_and_resins(printer_name: str, resin_names: list[str], user_id: str | None = None) -> None:
    """Raise ValueError saying why a resin printer with these resins cannot be sliced for."""
    printer = catalog.get_printer(printer_name)
    if printer is None:
        raise ValueError(f"Unknown resin printer: {printer_name!r}")
    if not printer["supported"]:
        raise ValueError(f"{printer['name']} reads {printer['format']} files, which the slicer cannot write yet")
    if len(resin_names) > 1:
        raise ValueError("A resin printer uses at most one resin")
    if resin_names and catalog.resin_path(resin_names[0], user_id) is None:
        raise ValueError(f"Unknown resin: {resin_names[0]!r}")


def choose_row(material: dict[str, Any], printer_names: list[str], layer_height: float) -> dict[str, Any] | None:
    """The best settings row of `material`, or None when no row fits the printer.

    A row at the asked layer height beats any row at another one; then the better printer match
    (the printer, its vendor, any printer); then the nearer layer height.
    """
    best: dict[str, Any] | None = None
    best_key: tuple[int, int, float] | None = None
    for row in material.get("settings", []):
        if not isinstance(row, dict) or "layer_height" not in row:
            continue
        score = _row_score(row, printer_names)
        if score == 0:
            continue
        gap = abs(float(row["layer_height"]) - layer_height)
        key = (0 if gap < 0.0005 else 1, -score, gap)
        if best_key is None or key < best_key:
            best, best_key = row, key
    return best


def match_kind(row: dict[str, Any], printer_names: list[str]) -> str:
    score = max((_printer_score(p, printer_names) for p in row.get("printers", []) if isinstance(p, str)), default=0)
    return {3: PRINTER_EXACT, 2: PRINTER_VENDOR}.get(score, PRINTER_ANY)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text())


class ResinCatalog:
    def __init__(self, resin_dir: Path):
        self._dir = resin_dir
        self._printers: list[dict[str, Any]] = []
        self._materials: list[dict[str, Any]] = []
        self._materials_by_name: dict[str, dict[str, Any]] = {}

    def load(self) -> None:
        self._printers, self._materials, self._materials_by_name = [], [], {}
        index = self._dir / "index.json"
        if index.is_file():
            try:
                for entry in _read_json(index).get("printers", []):
                    self._printers.append(
                        {
                            "name": f"{entry['vendor']} {entry['model']}",
                            "vendor": entry["vendor"],
                            "model": entry["model"],
                            "format": entry.get("format", ""),
                            "supported": bool(entry.get("supported")),
                            "nonsquare_pixels": bool(entry.get("nonsquare_pixels")),
                            "file": entry["file"],
                        }
                    )
            except (OSError, ValueError, KeyError) as exc:
                logger.warning("Resin printer index %s is unusable: %s", index, exc)
        materials = self._dir / "materials-index.json"
        if materials.is_file():
            try:
                for entry in _read_json(materials).get("materials", []):
                    self._materials.append(
                        {
                            "name": entry["name"],
                            "vendor": entry.get("vendor", ""),
                            "family": entry.get("family", ""),
                            "color": entry.get("color", ""),
                            "resin_type": entry.get("resin_type", ""),
                            "file": entry["file"],
                        }
                    )
                    self._materials_by_name[entry["name"]] = self._materials[-1]
            except (OSError, ValueError, KeyError) as exc:
                logger.warning("Resin material index %s is unusable: %s", materials, exc)
        logger.info(
            "Loaded %d resin printers and %d resins from %s", len(self._printers), len(self._materials), self._dir
        )

    # ---- printers
    def printers(self) -> list[dict[str, Any]]:
        """Every resin printer with its screen and build height read from its preset."""
        out = []
        for p in self._printers:
            info = dict(p)
            data = self.printer_preset(p["name"]) or {}
            info.update(_display_facts(data))
            info["extension"] = file_extension(info["format"])
            info.pop("file", None)
            out.append(info)
        return out

    def get_printer(self, name: str) -> dict[str, Any] | None:
        return next((p for p in self._printers if p["name"] == name), None)

    def printer_preset(self, name: str) -> dict[str, Any] | None:
        """The printer's machine preset (flat key/value JSON as the slicer's --load-settings takes it)."""
        printer = self.get_printer(name)
        if printer is None:
            return None
        try:
            return _read_json(self._dir / printer["file"])
        except (OSError, ValueError):
            return None

    # ---- resins
    def resins(self, user_id: str | None = None) -> list[dict[str, Any]]:
        """The built-in resins, then the user's own."""
        mine = user_resins.list(user_id) if user_id else []
        return [{k: v for k, v in m.items() if k != "file"} for m in self._materials] + mine

    def get_resin(self, name: str, user_id: str | None = None) -> dict[str, Any] | None:
        entry = self._materials_by_name.get(name)
        if entry is None:
            return user_resins.get(user_id, name) if user_id else None
        try:
            return _read_json(self._dir / entry["file"])
        except (OSError, ValueError):
            return None

    def resin_path(self, name: str, user_id: str | None = None) -> Path | None:
        entry = self._materials_by_name.get(name)
        if entry is None:
            return user_resins.path(user_id, name) if user_id else None
        return self._dir / entry["file"]

    def is_built_in(self, name: str) -> bool:
        return name in self._materials_by_name


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# The ending of the file each non-Anycubic format writes (the engine's registry); an Anycubic format id is its own ending.
_FORMAT_EXTENSIONS = {
    "CTB": "ctb",
    "CTBENCRYPTED": "ctb",
    "CTBGKTWO": "ctb",
    "CBDDLP": "cbddlp",
    "GOO": "goo",
    "CXDLP": "cxdlp",
    "SVGX": "svgx",
    "PHROZENZIP": "zip",
    "CHITUBOXZIP": "zip",
    "TINYMAKER": "zip",
}


def file_extension(format_id: str) -> str:
    return _FORMAT_EXTENSIONS.get(format_id, format_id.lower())


def _display_facts(preset: dict[str, Any]) -> dict[str, Any]:
    width, height = _num(preset.get("display_width")), _num(preset.get("display_height"))
    px, py = _num(preset.get("display_pixels_x")), _num(preset.get("display_pixels_y"))
    facts: dict[str, Any] = {
        "display_width_mm": width,
        "display_height_mm": height,
        "pixels_x": int(px) if px else None,
        "pixels_y": int(py) if py else None,
        "build_height_mm": _num(preset.get("printable_height")),
    }
    facts["pixel_size_mm"] = round(width / px, 4) if width and px else None
    return facts


catalog = ResinCatalog(settings.resin_dir)
