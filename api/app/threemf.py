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
and apply the right color to each mesh.

A leaf's single `extruder`/`color` above is still only the OBJECT/PART's
own base assignment, though -- a hand-painted file (e.g. a downloaded
multi-color model with just one part, its actual color variation living
entirely as per-triangle "paint_color" attributes on individual
<triangle> elements, OrcaSlicer's own proprietary MMU-segmentation
format) needs `triangle_extruders`/`triangle_colors` instead: one
representative extruder/color PER ORIGINAL TRIANGLE (same order as that
part's <triangle> elements, so the same order the loaded 3D geometry's
faces come in). This is a deliberate approximation, not the file's exact
paint pattern -- a triangle whose paint data is itself split into
multiple colors reports only its most-common one, not a
sub-triangle-accurate boundary (see _representative_extruder). Good
enough for "does the preview roughly look like the print", which is all
it needs to be: the actual slice already uses the real, exact paint data
regardless of what the preview shows (see cli_runner.py/OrcaSlicer's own
--remap-filament-extruder patch, which operates on the real engine-side
paint data, not this approximation).
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

    A part with no "extruder" metadata of its own inherits its parent
    object's value, mirroring OrcaSlicer's own ModelVolume::extruder_id()
    (falls back to the parent ModelObject's config when the volume's own
    is unset) -- confirmed against a real single-part painted file (the
    common case: one part per object, so the author only ever set
    "extruder" once, at the object level) whose color_tree previously
    resolved to no color at all (the leaf's part id had no entry here),
    silently falling back to the 3D viewer's flat default color.
    """
    result: dict[str, int] = {}
    for object_elem in root.findall("object"):
        obj_id = object_elem.get("id")
        obj_extruder: int | None = None
        try:
            meta = _metadata_dict(object_elem)
            raw = meta.get("extruder")
            if raw is not None:
                obj_extruder = int(raw)
                if obj_id:
                    result[obj_id] = obj_extruder
        except Exception:  # noqa: BLE001 - skip this object's metadata, keep going
            pass
        for part_elem in object_elem.findall("part"):
            part_id = part_elem.get("id")
            try:
                part_meta = _metadata_dict(part_elem)
                raw = part_meta.get("extruder")
                if part_id and raw is not None:
                    result[part_id] = int(raw)
                elif part_id and obj_extruder is not None:
                    result[part_id] = obj_extruder
            except Exception:  # noqa: BLE001
                pass
    return result


# -- per-triangle paint ("MMU segmentation") decoding --------------------
#
# Reverse-engineered from vendor/orcaslicer/src/libslic3r/TriangleSelector.cpp
# (serialize()/deserialize(), ~line 1692-1907) and Model.cpp's
# FacetsAnnotation::get_triangle_as_string/set_triangle_from_string
# (~line 3654-3703), and verified bit-for-bit against that same repo's own
# Catch2 ground-truth vectors (tests/libslic3r/test_triangle_selector.cpp
# and the CONST_FILAMENTS table, Model.cpp:54-57) -- see this module's
# tests for the hardcoded vectors. A <triangle>'s paint_color hex string
# encodes a small recursive tree: every node is one 4-bit "nibble" whose
# low 2 bits say whether it's a split (1-3 = split into that+1 children)
# or a leaf (0 = leaf, high 2 bits give the state -- an extruder number --
# directly for 0-2, or trigger reading 1-2 more nibbles for 3-17/18-32).
# We only need the *set* of leaf states a triangle's paint encodes (for
# the one-representative-color-per-triangle approximation, see module
# docstring), not their geometry, so unlike a full reconstruction we don't
# need to track which child is which -- just consume the right number of
# bits per node.


def _decode_paint_color_states(hex_str: str) -> list[int]:
    """Every leaf state (0 = NONE/unpainted, 1-32 = Extruder1-32) this
    triangle's paint_color attribute encodes, in whatever order the
    recursive descent visits them -- never raises; a malformed string
    (odd bit count, truncated, non-hex chars) yields whatever states were
    fully decoded before the problem, dropping only the tail.
    """
    if not hex_str:
        return []
    bits: list[int] = []
    for ch in reversed(hex_str):
        try:
            value = int(ch, 16)
        except ValueError:
            break
        bits.extend((value >> i) & 1 for i in range(4))

    states: list[int] = []
    pos = 0

    def next_nibble() -> int | None:
        nonlocal pos
        if pos + 4 > len(bits):
            return None
        nibble = 0
        for i in range(4):
            nibble |= bits[pos] << i
            pos += 1
        return nibble

    def decode_node() -> bool:
        code = next_nibble()
        if code is None:
            return False
        num_split_sides = code & 0b11
        if num_split_sides == 0:
            high = code >> 2
            if high == 0b11:
                nxt = next_nibble()
                if nxt is None:
                    return False
                if nxt == 0b1111:
                    third = next_nibble()
                    if third is None:
                        return False
                    states.append(third + 18)
                else:
                    states.append(nxt + 3)
            else:
                states.append(high)
        else:
            for _ in range(num_split_sides + 1):
                if not decode_node():
                    return False
        return True

    decode_node()
    return states


def _representative_extruder(hex_str: str) -> int | None:
    """One representative extruder number for a whole triangle -- the
    most-common non-NONE leaf state its paint data encodes (ties broken by
    first-encountered), or None if it has no paint override at all (every
    leaf is NONE, or the string didn't decode to anything). Deliberately
    a per-triangle approximation, not a sub-triangle-accurate split --
    see module docstring.
    """
    states = [s for s in _decode_paint_color_states(hex_str) if s != 0]
    if not states:
        return None
    counts: dict[int, int] = {}
    order: list[int] = []
    for state in states:
        if state not in counts:
            order.append(state)
        counts[state] = counts.get(state, 0) + 1
    return max(order, key=lambda s: counts[s])


def _parse_triangle_extruders(zf: zipfile.ZipFile) -> dict[str, list[int | None]]:
    """Maps a leaf object's id (same id space as _parse_id_extruders) to
    one representative extruder number per triangle in its <mesh>, in
    <triangle> document order -- matching the order the loaded 3D
    geometry's faces come in, since neither the 3MF writer nor three.js's
    loader reorders them. An object id is only present in the result if
    at least one of its triangles actually has a real paint override --
    keeps the common (fully unpainted) case's payload untouched, and lets
    _build_color_node fall back to that leaf's single base color exactly
    as it already does when there's no entry at all.
    """
    result: dict[str, list[int | None]] = {}
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
            mesh_elem = object_elem.find(_tag("mesh"))
            if mesh_elem is None:
                continue
            triangles_elem = mesh_elem.find(_tag("triangles"))
            if triangles_elem is None:
                continue
            per_triangle: list[int | None] = []
            any_painted = False
            for triangle_elem in triangles_elem.findall(_tag("triangle")):
                raw = triangle_elem.get("paint_color")
                extruder = _representative_extruder(raw) if raw else None
                if extruder is not None:
                    any_painted = True
                per_triangle.append(extruder)
            if any_painted:
                result[obj_id] = per_triangle
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


def _resolve_color(extruder: int | None, filament_colors: list[str]) -> tuple[str | None, int | None]:
    """Shared by the leaf's single color/extruder and each entry of
    triangle_colors/triangle_extruders -- same out-of-range guard either
    way, so a bogus/unconfigured index never reaches the frontend."""
    if extruder is not None and 1 <= extruder <= len(filament_colors):
        return filament_colors[extruder - 1] or None, extruder
    return None, None


def _build_color_node(
    object_id: str,
    objects: dict[str, list[str] | None],
    id_extruders: dict[str, int],
    filament_colors: list[str],
    triangle_extruders_by_id: dict[str, list[int | None]],
    depth: int = 0,
) -> ColorNode:
    children_ids = objects.get(object_id) if depth < _MAX_COMPONENT_DEPTH else None
    if children_ids:
        return ColorNode(
            children=[
                _build_color_node(
                    child_id, objects, id_extruders, filament_colors, triangle_extruders_by_id, depth + 1
                )
                for child_id in children_ids
            ]
        )
    color, extruder = _resolve_color(id_extruders.get(object_id), filament_colors)

    triangle_extruders = triangle_extruders_by_id.get(object_id)
    triangle_colors: list[str | None] | None = None
    resolved_triangle_extruders: list[int | None] | None = None
    if triangle_extruders is not None:
        resolved_triangle_extruders = []
        triangle_colors = []
        for raw_extruder in triangle_extruders:
            tri_color, tri_extruder = _resolve_color(raw_extruder, filament_colors)
            resolved_triangle_extruders.append(tri_extruder)
            triangle_colors.append(tri_color)

    return ColorNode(
        color=color,
        extruder=extruder,
        triangle_extruders=resolved_triangle_extruders,
        triangle_colors=triangle_colors,
    )


def _parse_color_tree(
    zf: zipfile.ZipFile,
    id_extruders: dict[str, int],
    filament_colors: list[str],
    triangle_extruders_by_id: dict[str, list[int | None]],
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
    return [
        _build_color_node(item_id, objects, id_extruders, filament_colors, triangle_extruders_by_id)
        for item_id in build_item_ids
    ]


def _string_list(data: dict, key: str) -> list[str]:
    values = data.get(key)
    if not isinstance(values, list):
        return []
    return [v if isinstance(v, str) else "" for v in values]


def _parse_embedded_filament_info(zf: zipfile.ZipFile) -> tuple[list[str], list[str]]:
    """The file's own author's filament_colour and filament_settings_id
    arrays from Metadata/project_settings.config, if present -- one entry
    per filament role the file was originally configured with (see module
    docstring for why filament_colour is more reliable than the per-object
    extruder metadata above). filament_settings_id is the actual saved
    material name (e.g. "Bambu PLA Basic @BBL A1M") -- surfaced purely to
    help a user match the file's intended material to one of their own,
    never used to resolve a real profile itself. Either array can have an
    empty-string entry (seen for genuinely unconfigured slots) -- callers
    should treat that as "role exists, no known value" rather than
    dropping it and losing the role count. The two arrays share the same
    index space (confirmed against a real downloaded project file), but
    are looked up independently in case a real file's lengths ever
    disagree -- never assume one implies the other.
    """
    try:
        raw = zf.read(_PROJECT_SETTINGS_PATH)
    except KeyError:
        return [], []
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return [], []
    return _string_list(data, "filament_colour"), _string_list(data, "filament_settings_id")


def read_project_scalar_settings(path: Path) -> dict[str, str]:
    """The file's own Metadata/project_settings.config, filtered to only the
    plain-string-valued top-level keys (drops list/dict values like
    `filament_colour` -- those are vector settings, out of scope for the
    scalar-bounds sanity check this feeds, see cli_runner.py).

    A saved 3mf project bakes in a full settings snapshot from whatever
    slicer/profile last touched it -- confirmed against a real downloaded
    file whose `raft_first_layer_expansion` was "-1", a value our engine's
    own PrintConfig.cpp declares `min = 0` for. That value is completely
    inert here (the same file's `raft_layers` is "0", i.e. no raft at all),
    but `m_print_config.validate(true)` (OrcaSlicer.cpp) checks every
    present key's bounds unconditionally, regardless of whether anything
    else in the config actually uses it -- failing the whole job with
    "Invalid parameter value(s) included in the 3mf file" over a setting
    that was never going to affect the print. Never raises; empty dict on
    anything missing/malformed.
    """
    try:
        with zipfile.ZipFile(path) as zf:
            raw = zf.read(_PROJECT_SETTINGS_PATH)
    except (OSError, zipfile.BadZipFile, KeyError):
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, str)}


def inspect_3mf(path: Path) -> ThreeMfInspection:
    """Never raises -- degrades to a single implicit plate with no known
    material split on any missing/malformed/unreadable input."""
    try:
        with zipfile.ZipFile(path) as zf:
            plates, extruder_indices, id_extruders = _parse_model_settings(zf)
            embedded_filament_colors, embedded_filament_names = _parse_embedded_filament_info(zf)
            try:
                triangle_extruders_by_id = _parse_triangle_extruders(zf)
            except Exception:  # noqa: BLE001 - never let a malformed paint attribute break the rest of the inspection
                triangle_extruders_by_id = {}
            try:
                color_tree = _parse_color_tree(zf, id_extruders, embedded_filament_colors, triangle_extruders_by_id)
            except Exception:  # noqa: BLE001 - the object-graph walk is the riskiest part of this module; never let it break the rest of the inspection
                color_tree = []
    except (OSError, zipfile.BadZipFile):
        return _SINGLE_IMPLICIT_PLATE

    from .threemf_objects import list_objects  # local: threemf_objects imports schemas, not this module

    return ThreeMfInspection(
        plates=plates or [PlateInfo(index=1)],
        objects=list_objects(path),
        extruder_indices=extruder_indices,
        embedded_filament_colors=embedded_filament_colors,
        embedded_filament_names=embedded_filament_names,
        color_tree=color_tree,
    )
