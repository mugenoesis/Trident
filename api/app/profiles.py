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
        # Every profile's own (unmerged) leaf keys, INCLUDING non-instantiable
        # base/template presets (e.g. "fdm_belt_common") -- kept around
        # purely as `inherits` merge sources; never exposed via list()/get().
        self._raw_by_key: dict[tuple[str, str, str], dict] = {}

    def load(self) -> None:
        self._by_key.clear()
        self._raw_by_key.clear()
        if not self._profiles_dir.is_dir():
            logger.warning("profiles_dir %s does not exist; catalog is empty", self._profiles_dir)
            return

        # Pass 1: parse every profile file's own keys (leaf-only, unmerged),
        # instantiable or not -- a later pass needs every base/template
        # preset available as a potential `inherits` target regardless of
        # whether it's independently selectable.
        entries: list[tuple[str, str, str, Path, dict]] = []
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
                kind = _infer_kind(data, preset_path.relative_to(vendor_dir))
                name = data.get("name", preset_path.stem)
                self._raw_by_key[(vendor, kind, name)] = data
                entries.append((vendor, kind, name, preset_path, data))

        # Pass 2: resolve each instantiable profile's full `inherits` chain
        # into one merged effective config. OrcaSlicer profiles are commonly
        # split leaf/base (e.g. "IdeaFormer IR3 V2 0.4 nozzle" inherits
        # "fdm_belt_common" inherits "fdm_klipper_common" inherits
        # "fdm_machine_common") -- a key declared only on a base preset (e.g.
        # `belt_printer`, `gcode_remap_x`) must still reach the leaf's
        # resolved config, or it silently falls back to PrintConfig's
        # hardcoded default. This is NOT something OrcaSlicer's CLI does on
        # its own for a raw `--load-settings <path>` (that only walks
        # `inherits` in the GUI/PresetBundle preset-selection flow) -- confirmed
        # against a real build: a belt machine profile's `--load-settings`
        # slice came back with `belt_printer = 0` and identity `gcode_remap_*`
        # in its own gcode config dump, despite both being declared "1"/non-identity
        # on the (uninherited) base preset.
        for vendor, kind, name, preset_path, data in entries:
            if str(data.get("instantiation", "true")).lower() == "false":
                # instantiation:"false" marks a shared base/template preset
                # (e.g. "fdm_machine_common") meant only to be inherited from,
                # not independently selectable -- still merge-source-eligible
                # via _raw_by_key above, just not exposed here.
                continue

            merged = self._resolve_merged(vendor, kind, name, data)
            detail = ProfileDetail(
                vendor=vendor,
                kind=kind,
                name=name,
                path=str(preset_path.relative_to(self._profiles_dir)),
                data=merged,
            )
            self._by_key[(vendor, kind, name)] = detail

        logger.info("Loaded %d profiles from %s", len(self._by_key), self._profiles_dir)

    def _resolve_merged(
        self, vendor: str, kind: str, name: str, data: dict, _seen: frozenset[tuple[str, str, str]] = frozenset()
    ) -> dict:
        """Merge `data` over its full `inherits` ancestor chain, root-first so
        the child's own keys always win. `inherits` is a bare name (no
        vendor) -- each vendor directory normally carries its own copy of
        every ancestor it needs (e.g. every vendor has its own
        "fdm_process_common.json"), so same-vendor lookup is tried first;
        some chains cross vendor directories on purpose though (e.g. a
        filament's "Generic ... @System" parent lives under the separate
        "OrcaFilamentLibrary" vendor), so this falls back to a by-name search
        across all vendors. `_seen` guards against a cyclic `inherits` chain
        (shouldn't happen in a well-formed catalog, but a bad/malformed
        profile must not hang the whole catalog load).
        """
        inherits = data.get("inherits")
        if not isinstance(inherits, str) or not inherits or (vendor, kind, name) in _seen:
            return dict(data)

        seen = _seen | {(vendor, kind, name)}
        parent_key = (vendor, kind, inherits)
        parent_data = self._raw_by_key.get(parent_key)
        if parent_data is None:
            for (other_vendor, other_kind, other_name), other_data in self._raw_by_key.items():
                if other_kind == kind and other_name == inherits:
                    parent_key = (other_vendor, other_kind, other_name)
                    parent_data = other_data
                    break
        if parent_data is None:
            # Declared parent isn't in the catalog (fork drift/missing file)
            # -- fall back to this preset's own keys rather than failing the
            # whole catalog load.
            return dict(data)

        merged_parent = self._resolve_merged(*parent_key, parent_data, seen)
        merged = dict(merged_parent)
        merged.update(data)
        return merged

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
