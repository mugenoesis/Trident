"""Introspects OrcaSlicer's baked-in profile catalog.

Layout (resources/profiles/): a `<Vendor>.json` index file per vendor plus
a sibling `<Vendor>/` directory holding the individual machine/process/
filament preset JSON files. Each preset JSON carries a "type" key
("machine"/"process"/"filament") in upstream OrcaSlicer; we key off that
when present and fall back to filename/subdirectory heuristics otherwise
so this doesn't hard-fail against fork drift.

Cached in memory at process startup per docs/ARCHITECTURE.md; call
`load_catalog()` again (e.g. from a debug/admin route) to pick up changes
without restarting, if that's ever needed.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .config import settings
from .schemas import ProfileDetail, ProfileSummary

logger = logging.getLogger(__name__)

_KNOWN_KINDS = {"machine", "process", "filament"}


def _infer_kind(data: dict, path: Path) -> str:
    kind = data.get("type")
    if isinstance(kind, str):
        # A recognized explicit type always wins. An unrecognized-but-present
        # type (e.g. upstream's "machine_model" -- a printer-family
        # descriptor like bed shape/available nozzles, not a loadable
        # preset) must NOT fall through to the path guess below: its own
        # "machine" subdirectory would otherwise misclassify it as an
        # actual, selectable machine preset.
        return kind.lower() if kind.lower() in _KNOWN_KINDS else "unknown"
    lower_parts = {p.lower() for p in path.parts}
    for known in _KNOWN_KINDS:
        if known in lower_parts or f"{known}s" in lower_parts:
            return known
    return "unknown"


class ProfileCatalog:
    def __init__(self, profiles_dir: Path):
        self._profiles_dir = profiles_dir
        self._by_key: dict[tuple[str, str, str], ProfileDetail] = {}

    def load(self) -> None:
        self._by_key.clear()
        if not self._profiles_dir.is_dir():
            logger.warning("profiles_dir %s does not exist; catalog is empty", self._profiles_dir)
            return

        for vendor_index in sorted(self._profiles_dir.glob("*.json")):
            vendor = vendor_index.stem
            vendor_dir = self._profiles_dir / vendor
            if not vendor_dir.is_dir():
                continue
            for preset_path in sorted(vendor_dir.rglob("*.json")):
                try:
                    data = json.loads(preset_path.read_text())
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning("Skipping unreadable profile %s: %s", preset_path, exc)
                    continue
                # instantiation:"false" marks shared base/template presets meant
                # only to be `inherits`-ed from (e.g. "fdm_machine_common"), not
                # to be loaded directly -- OrcaSlicer's CLI resolves `inherits`
                # chains on its own from the leaf preset's path, so these never
                # need to be independently selectable or resolvable here.
                if str(data.get("instantiation", "true")).lower() == "false":
                    continue

                kind = _infer_kind(data, preset_path.relative_to(vendor_dir))
                name = data.get("name", preset_path.stem)
                detail = ProfileDetail(
                    vendor=vendor,
                    kind=kind,
                    name=name,
                    path=str(preset_path.relative_to(self._profiles_dir)),
                    data=data,
                )
                self._by_key[(vendor, kind, name)] = detail

        logger.info("Loaded %d profiles from %s", len(self._by_key), self._profiles_dir)

    def list(self) -> list[ProfileSummary]:
        return [
            ProfileSummary(vendor=d.vendor, kind=d.kind, name=d.name, path=d.path)
            for d in self._by_key.values()
        ]

    def get(self, vendor: str, kind: str, name: str) -> ProfileDetail | None:
        return self._by_key.get((vendor, kind, name))

    def get_by_name(self, kind: str, name: str) -> ProfileDetail | None:
        """Look up a profile by (kind, name) alone, ignoring vendor.

        Used to resolve JobCreateRequest's printer_profile/process_profile/
        filament_profiles (bare names, as shown in GET /profiles) into the
        actual file path `--load-settings`/`--load-filaments` need (see
        cli_runner.py). Names aren't guaranteed globally unique across
        vendors, so this is a best-effort first match -- acceptable because
        process/filament profile names already carry a vendor-qualifying
        "@<printer>" suffix by convention, and machine names are themselves
        vendor+model-specific in practice.
        """
        for detail in self._by_key.values():
            if detail.kind == kind and detail.name == name:
                return detail
        return None


catalog = ProfileCatalog(settings.profiles_dir)
