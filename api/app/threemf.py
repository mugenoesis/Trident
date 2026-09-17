"""Best-effort .3mf zip/XML inspection for the pre-slice plate picker.

A project .3mf's Metadata/model_settings.config (an Orca/Bambu convention,
not the 3MF standard -- confirmed against vendor/orcaslicer's own writer,
Format/bbs_3mf.cpp) holds one <plate> element per plate and one <object>
element per model object, each carrying <metadata key=.../> children:

    <config>
      <object id="2">
        <metadata key="name" value="..."/>
        <metadata key="extruder" value="2"/>       <!-- 1-based filament slot -->
        <part id="..." subtype="normal_part">...</part>
      </object>
      <plate>
        <metadata key="plater_id" value="1"/>       <!-- 1-based, matches --slice N -->
        <metadata key="plater_name" value="My plate"/>
        <metadata key="thumbnail_file" value="Metadata/plate_1.png"/>
        <model_instance>
          <metadata key="object_id" value="2"/>
        </model_instance>
      </plate>
    </config>

A plain/generic .3mf from another tool may have none of this -- every
function here must degrade to "1 implicit plate, no known material split"
on anything missing or malformed, never raise.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .schemas import PlateInfo, ThreeMfInspection

_MODEL_SETTINGS_PATH = "Metadata/model_settings.config"

_SINGLE_IMPLICIT_PLATE = ThreeMfInspection(plates=[PlateInfo(index=1)], extruder_indices=[])


def _metadata_dict(elem: ET.Element) -> dict[str, str]:
    values: dict[str, str] = {}
    for child in elem.findall("metadata"):
        key = child.get("key")
        value = child.get("value")
        if key is not None and value is not None:
            values[key] = value
    return values


def _parse_plates(root: ET.Element) -> list[PlateInfo]:
    plates: list[PlateInfo] = []
    for i, plate_elem in enumerate(root.findall("plate"), start=1):
        try:
            meta = _metadata_dict(plate_elem)
            raw_index = meta.get("plater_id")
            try:
                index = int(raw_index) if raw_index is not None else i
            except ValueError:
                index = i
            plates.append(
                PlateInfo(
                    index=index,
                    name=meta.get("plater_name") or None,
                    object_count=len(plate_elem.findall("model_instance")) or None,
                    thumbnail=meta.get("thumbnail_file") or None,
                )
            )
        except Exception:  # noqa: BLE001 - one malformed <plate> shouldn't blank out the rest
            continue
    return plates


def _parse_extruder_indices(root: ET.Element) -> list[int]:
    indices: set[int] = set()
    for object_elem in root.findall("object"):
        try:
            meta = _metadata_dict(object_elem)
            raw = meta.get("extruder")
            if raw is not None:
                indices.add(int(raw))
        except Exception:  # noqa: BLE001 - skip this object's metadata, keep going
            continue
        for part_elem in object_elem.findall("part"):
            try:
                part_meta = _metadata_dict(part_elem)
                raw = part_meta.get("extruder")
                if raw is not None:
                    indices.add(int(raw))
            except Exception:  # noqa: BLE001
                continue
    return sorted(indices)


def inspect_3mf(path: Path) -> ThreeMfInspection:
    """Never raises -- degrades to a single implicit plate with no known
    material split on any missing/malformed/unreadable input."""
    try:
        with zipfile.ZipFile(path) as zf:
            try:
                raw = zf.read(_MODEL_SETTINGS_PATH)
            except KeyError:
                return _SINGLE_IMPLICIT_PLATE
    except (OSError, zipfile.BadZipFile):
        return _SINGLE_IMPLICIT_PLATE

    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return _SINGLE_IMPLICIT_PLATE

    plates = _parse_plates(root)
    if not plates:
        plates = [PlateInfo(index=1)]
    extruder_indices = _parse_extruder_indices(root)

    return ThreeMfInspection(plates=plates, extruder_indices=extruder_indices)
