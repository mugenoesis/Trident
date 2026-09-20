"""Best-effort .3mf zip/XML inspection for the pre-slice plate picker and
per-role material/nozzle assignment.

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

This per-object "extruder" metadata is NOT the only (or most reliable) way
a .3mf can express multi-material intent, though -- confirmed against a
real downloaded multi-color model that crashed the CLI (exit code -11):
the object-level metadata above only ever said "extruder 1" for its
single object, even though the file's Metadata/project_settings.config
(a separate, flat JSON file -- Bambu Studio/OrcaSlicer's own "what was
configured when this project was saved" dump) had `"filament_colour":
["#000000", "#FFFF00"]`, i.e. two real filament roles, painted onto that
one object per-triangle rather than assigned per-object. That JSON file's
filament_colour array length is the authoritative "how many filament
roles does this file actually need" signal -- it catches paint-on/
per-triangle color assignments that the XML above misses entirely, and
gives real original colors for free. Preferred over extruder_indices
when present.

A plain/generic .3mf from another tool may have none of this -- every
function here must degrade to "1 implicit plate, no known material split"
on anything missing or malformed, never raise.

color_tree (for coloring the 3D preview) takes this one step further:
BambuStudio/OrcaSlicer's "Production Extension" 3MFs split a composite
object's parts across separate 3D/Objects/*.model files, referenced via
<components><component objectid="Y" p:path="...">. That "Y" is the SAME
id as the corresponding Metadata/model_settings.config <part id="Y">
carrying that part's own extruder assignment -- and three.js's 3MFLoader
resolves every .model part's objects into one flat, id-keyed map,
building a Group whose children mirror <build><item>/<components>
order exactly. _parse_object_graph mirrors that same resolution so a
frontend can walk its rendered Object3D tree in lockstep with color_tree
and apply the right color to each mesh. This only covers per-object/
per-part color assignment, not per-triangle "paint on" coloring (a
separate, proprietary, per-triangle mesh property this module does not
parse) -- a file using only that will get an empty color_tree.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .schemas import ColorNode, PlateInfo, ThreeMfInspection

_MODEL_SETTINGS_PATH = "Metadata/model_settings.config"
_PROJECT_SETTINGS_PATH = "Metadata/project_settings.config"

# The 3MF core spec's default namespace -- every element in 3D/*.model
# files (unlike Metadata/model_settings.config, which uses no namespace at
# all) lives in it, so tag lookups there need the {ns} prefix even though
# attributes (id, objectid, ...) don't.
_3MF_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"


def _tag(name: str) -> str:
    return f"{{{_3MF_NS}}}{name}"


_SINGLE_IMPLICIT_PLATE = ThreeMfInspection(plates=[PlateInfo(index=1)])


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


def _parse_id_extruders(root: ET.Element) -> dict[str, int]:
    """Maps every object id AND part id to its assigned extruder index --
    a composite object's <part id="Y"> (Metadata/model_settings.config)
    shares its id space with that same part's id as a standalone <object>
    in a Production-Extension sub-.model file, referenced via
    <component objectid="Y"> (see module docstring) -- so one flat mapping
    keyed by either kind of id is all a color-tree walk needs.
    """
    result: dict[str, int] = {}
    for object_elem in root.findall("object"):
        obj_id = object_elem.get("id")
        try:
            meta = _metadata_dict(object_elem)
            raw = meta.get("extruder")
            if obj_id and raw is not None:
                result[obj_id] = int(raw)
        except Exception:  # noqa: BLE001 - skip this object's metadata, keep going
            pass
        for part_elem in object_elem.findall("part"):
            part_id = part_elem.get("id")
            try:
                part_meta = _metadata_dict(part_elem)
                raw = part_meta.get("extruder")
                if part_id and raw is not None:
                    result[part_id] = int(raw)
            except Exception:  # noqa: BLE001
                pass
    return result


def _parse_model_settings(zf: zipfile.ZipFile) -> tuple[list[PlateInfo], list[int], dict[str, int]]:
    try:
        raw = zf.read(_MODEL_SETTINGS_PATH)
    except KeyError:
        return [], [], {}
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return [], [], {}
    return _parse_plates(root), _parse_extruder_indices(root), _parse_id_extruders(root)


def _parse_object_graph(zf: zipfile.ZipFile) -> tuple[dict[str, list[str] | None], list[str]]:
    """Reconstructs the exact object/component tree three.js's 3MFLoader
    builds, from every .model part in the zip (the root 3D/3dmodel.model
    plus any Production-Extension sub-parts under 3D/Objects/) -- three.js
    resolves objects by id globally across every part file into one flat
    map (confirmed against its own source: buildObjects() iterates every
    parsed .model file and populates a single `objects` dict keyed by
    id), so this mirrors that instead of trying to follow each
    <component p:path="..."> reference individually.

    Returns (objects, build_item_ids): `objects[id]` is a list of child
    object ids (in <components> order) for a composite, or None for a
    leaf mesh object; `build_item_ids` is the root file's <build><item>
    order -- three.js's top-level Group's children, positionally, are
    exactly `[objects[id] for id in build_item_ids]`.
    """
    objects: dict[str, list[str] | None] = {}
    build_item_ids: list[str] = []

    for name in zf.namelist():
        if not name.lower().endswith(".model"):
            continue
        try:
            root = ET.fromstring(zf.read(name))
        except (ET.ParseError, KeyError):
            continue

        for object_elem in root.iter(_tag("object")):
            obj_id = object_elem.get("id")
            if not obj_id:
                continue
            components_elem = object_elem.find(_tag("components"))
            if components_elem is not None:
                child_ids = [
                    c.get("objectid")
                    for c in components_elem.findall(_tag("component"))
                    if c.get("objectid")
                ]
                objects[obj_id] = child_ids  # type: ignore[assignment]
            else:
                objects.setdefault(obj_id, None)

        build_elem = root.find(_tag("build"))
        if build_elem is not None:
            item_ids = [item.get("objectid") for item in build_elem.findall(_tag("item")) if item.get("objectid")]
            if item_ids:
                build_item_ids = item_ids  # type: ignore[assignment]

    return objects, build_item_ids


_MAX_COMPONENT_DEPTH = 20  # guards against a malformed/cyclic <components> reference chain


def _build_color_node(
    object_id: str,
    objects: dict[str, list[str] | None],
    id_extruders: dict[str, int],
    filament_colors: list[str],
    depth: int = 0,
) -> ColorNode:
    children_ids = objects.get(object_id) if depth < _MAX_COMPONENT_DEPTH else None
    if children_ids:
        return ColorNode(
            children=[
                _build_color_node(child_id, objects, id_extruders, filament_colors, depth + 1)
                for child_id in children_ids
            ]
        )
    extruder = id_extruders.get(object_id)
    color = None
    if extruder is not None and 1 <= extruder <= len(filament_colors):
        color = filament_colors[extruder - 1] or None
    return ColorNode(color=color)


def _parse_color_tree(
    zf: zipfile.ZipFile, id_extruders: dict[str, int], filament_colors: list[str]
) -> list[ColorNode]:
    """Best-effort -- returns [] (meaning "nothing to color, use the
    default flat color") on anything missing/malformed, or when there's
    simply no per-object/part extruder+color info to place onto the tree.
    """
    if not id_extruders or not filament_colors:
        return []
    objects, build_item_ids = _parse_object_graph(zf)
    if not build_item_ids:
        return []
    return [_build_color_node(item_id, objects, id_extruders, filament_colors) for item_id in build_item_ids]


def _parse_embedded_filament_colors(zf: zipfile.ZipFile) -> list[str]:
    """The file's own author's filament_colour array from
    Metadata/project_settings.config, if present -- one entry per filament
    role the file was originally configured with (see module docstring for
    why this is more reliable than the per-object extruder metadata
    above). An entry can be an empty string (seen for genuinely
    unconfigured slots) -- callers should treat that as "role exists, no
    known color" rather than dropping it and losing the role count.
    """
    try:
        raw = zf.read(_PROJECT_SETTINGS_PATH)
    except KeyError:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return []
    colors = data.get("filament_colour")
    if not isinstance(colors, list):
        return []
    return [c if isinstance(c, str) else "" for c in colors]


def inspect_3mf(path: Path) -> ThreeMfInspection:
    """Never raises -- degrades to a single implicit plate with no known
    material split on any missing/malformed/unreadable input."""
    try:
        with zipfile.ZipFile(path) as zf:
            plates, extruder_indices, id_extruders = _parse_model_settings(zf)
            embedded_filament_colors = _parse_embedded_filament_colors(zf)
            try:
                color_tree = _parse_color_tree(zf, id_extruders, embedded_filament_colors)
            except Exception:  # noqa: BLE001 - the object-graph walk is the riskiest part of this module; never let it break the rest of the inspection
                color_tree = []
    except (OSError, zipfile.BadZipFile):
        return _SINGLE_IMPLICIT_PLATE

    return ThreeMfInspection(
        plates=plates or [PlateInfo(index=1)],
        extruder_indices=extruder_indices,
        embedded_filament_colors=embedded_filament_colors,
        color_tree=color_tree,
    )
