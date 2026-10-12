"""Per-object view of a .3mf: list what is in it, and write a derived copy with
some objects removed and the rest optionally laid out in a row.

An uploaded project can hold many objects across several plates, and the user
may not want to print all of them. OrcaSlicer's CLI has no "skip this object"
option, so exclusion is done by rewriting the file before slicing: dropping an
object's <build><item> and its <model_instance> in Metadata/model_settings.config.

For a belt printer the same rewrite lays the kept objects out one after the
other along the belt (the slicing Y axis) instead of leaving them on separate
plates, which the CLI would otherwise pile onto one plate with its auto-arrange.

Objects are identified by their <build><item> position (0-based, file order),
the same order three.js's 3MFLoader builds its children in -- so the browser's
per-object meshes and this module's list line up by index (see threemf.py).

The root model is edited as text, not through ElementTree, because ET rewrites
namespace prefixes (p: becomes ns0:) and OrcaSlicer's own loader is picky about
the Production Extension attributes.
"""

from __future__ import annotations

import contextlib
import copy
import json
import math
import re
import uuid
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from defusedxml import ElementTree as DET

from .schemas import ObjectInfo

_CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
_PROD = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
_ROOT_MODEL = "3D/3dmodel.model"
_MODEL_SETTINGS = "Metadata/model_settings.config"
_PROJECT_SETTINGS = "Metadata/project_settings.config"

_ITEM_RE = re.compile(r"<item\b[^>]*?/>")
_TRANSFORM_RE = re.compile(r'\btransform="([^"]*)"')

Matrix = list[float]  # 3MF row-vector affine: m00 m01 m02 m10 m11 m12 m20 m21 m22 tx ty tz
_IDENTITY: Matrix = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]


def _c(name: str) -> str:
    return f"{{{_CORE}}}{name}"


def _parse_matrix(raw: str | None) -> Matrix:
    if not raw:
        return list(_IDENTITY)
    try:
        values = [float(v) for v in raw.split()]
    except ValueError:
        return list(_IDENTITY)
    return values if len(values) == 12 else list(_IDENTITY)


def _apply(m: Matrix, p: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = p
    return (
        x * m[0] + y * m[3] + z * m[6] + m[9],
        x * m[1] + y * m[4] + z * m[7] + m[10],
        x * m[2] + y * m[5] + z * m[8] + m[11],
    )


Box = tuple[tuple[float, float, float], tuple[float, float, float]]  # (min, max)


def _transform_box(m: Matrix, box: Box) -> Box:
    (x0, y0, z0), (x1, y1, z1) = box
    corners = [_apply(m, (x, y, z)) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
    return (
        (min(c[0] for c in corners), min(c[1] for c in corners), min(c[2] for c in corners)),
        (max(c[0] for c in corners), max(c[1] for c in corners), max(c[2] for c in corners)),
    )


def _merge(a: Box | None, b: Box | None) -> Box | None:
    if a is None:
        return b
    if b is None:
        return a
    return (
        (min(a[0][0], b[0][0]), min(a[0][1], b[0][1]), min(a[0][2], b[0][2])),
        (max(a[1][0], b[1][0]), max(a[1][1], b[1][1]), max(a[1][2], b[1][2])),
    )


class _ModelFiles:
    """Lazy cache of the parsed .model files in a 3mf, and object boxes."""

    def __init__(self, zf: zipfile.ZipFile):
        self._zf = zf
        self._roots: dict[str, ET.Element] = {}
        self._boxes: dict[tuple[str, str], Box | None] = {}

    def root(self, path: str) -> ET.Element:
        path = path.lstrip("/")
        if path not in self._roots:
            self._roots[path] = DET.fromstring(self._zf.read(path))
        return self._roots[path]

    def _find_object(self, path: str, object_id: str) -> ET.Element | None:
        resources = self.root(path).find(_c("resources"))
        if resources is None:
            return None
        for obj in resources.findall(_c("object")):
            if obj.get("id") == object_id:
                return obj
        return None

    def _mesh_box(self, obj: ET.Element) -> Box | None:
        """Box of an object's own vertices, not counting its components."""
        verts = obj.find(_c("mesh") + "/" + _c("vertices"))
        if verts is None:
            return None
        points = [
            (float(v.get("x", 0)), float(v.get("y", 0)), float(v.get("z", 0))) for v in verts.findall(_c("vertex"))
        ]
        if not points:
            return None
        xs, ys, zs = zip(*points, strict=True)
        return ((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))

    def local_box(self, path: str, object_id: str, _depth: int = 0) -> Box | None:
        """Box of one object in its own coordinates (components applied)."""
        key = (path.lstrip("/"), object_id)
        if key in self._boxes:
            return self._boxes[key]
        box: Box | None = None
        obj = self._find_object(path, object_id)
        if obj is not None and _depth < 16:
            box = self._mesh_box(obj)
            for child_path, child_id, transform in _components(obj, path):
                child = self.local_box(child_path, child_id, _depth + 1)
                if child is not None:
                    box = _merge(box, _transform_box(transform, child))
        self._boxes[key] = box
        return box

    def local_points(self, path: str, object_id: str, matrix: Matrix | None = None, _depth: int = 0):
        """Every vertex of one object in its own coordinates (components applied), one at a time."""
        obj = self._find_object(path, object_id)
        if obj is None or _depth >= 16:
            return
        m = matrix or list(_IDENTITY)
        for v in obj.findall(_c("mesh") + "/" + _c("vertices") + "/" + _c("vertex")):
            yield _apply(m, (float(v.get("x", 0)), float(v.get("y", 0)), float(v.get("z", 0))))
        for child_path, child_id, transform in _components(obj, path):
            yield from self.local_points(child_path, child_id, _compose(m, transform), _depth + 1)


def _components(obj: ET.Element, path: str) -> list[tuple[str, str, Matrix]]:
    """(file, object id, transform) of each component of an object; a component without a file is in the same one."""
    return [
        (comp.get(f"{{{_PROD}}}path") or path, comp.get("objectid", ""), _parse_matrix(comp.get("transform")))
        for comp in obj.findall(_c("components") + "/" + _c("component"))
    ]


def _compose(outer: Matrix, inner: Matrix) -> Matrix:
    """The transform that applies `inner` first, then `outer`."""
    out: Matrix = []
    for j in range(3):
        col = (inner[3 * j], inner[3 * j + 1], inner[3 * j + 2])
        out += [sum(outer[3 * k + i] * col[k] for k in range(3)) for i in range(3)]
    t = _apply(outer, (inner[9], inner[10], inner[11]))
    return out + list(t)


@dataclass
class _Item:
    index: int
    object_id: str
    instance: int  # which occurrence of object_id in the build (0-based)
    transform: Matrix
    box: Box | None  # world-space, after the item's own transform


def _read_items(zf: zipfile.ZipFile) -> list[_Item]:
    files = _ModelFiles(zf)
    build = files.root(_ROOT_MODEL).find(_c("build"))
    if build is None:
        return []
    seen: dict[str, int] = {}
    items: list[_Item] = []
    for i, elem in enumerate(build.findall(_c("item"))):
        object_id = elem.get("objectid", "")
        transform = _parse_matrix(elem.get("transform"))
        local = files.local_box(_ROOT_MODEL, object_id)
        items.append(
            _Item(
                index=i,
                object_id=object_id,
                instance=seen.get(object_id, 0),
                transform=transform,
                box=_transform_box(transform, local) if local else None,
            )
        )
        seen[object_id] = seen.get(object_id, 0) + 1
    return items


def _object_names(root: ET.Element) -> dict[str, str]:
    names: dict[str, str] = {}
    for obj in root.findall("object"):
        object_id = obj.get("id")
        for meta in obj.findall("metadata"):
            if meta.get("key") == "name" and object_id:
                names[object_id] = meta.get("value", "")
                break
    return names


def _plate_number(plate: ET.Element, default: int) -> int:
    for meta in plate.findall("metadata"):
        if meta.get("key") == "plater_id":
            with contextlib.suppress(ValueError):
                return int(meta.get("value", default))
    return default


def _instance_number(fields: dict[str, str | None], seen: int) -> int:
    """An instance's number: its own instance_id, else how many of that object came before it on the plate."""
    try:
        return int(str(fields["instance_id"])) if "instance_id" in fields else seen
    except (TypeError, ValueError):
        return seen


def _read_settings(zf: zipfile.ZipFile) -> tuple[dict[str, str], dict[tuple[str, int], int]]:
    """(object_id -> name, (object_id, instance) -> plate index)."""
    try:
        root = DET.fromstring(zf.read(_MODEL_SETTINGS))
    except (KeyError, ET.ParseError):
        return {}, {}
    plates: dict[tuple[str, int], int] = {}
    for n, plate in enumerate(root.findall("plate"), start=1):
        index = _plate_number(plate, n)
        counts: dict[str, int] = {}
        for inst in plate.findall("model_instance"):
            fields = _instance_fields(inst)
            object_id = fields.get("object_id") or ""
            plates[(object_id, _instance_number(fields, counts.get(object_id, 0)))] = index
            counts[object_id] = counts.get(object_id, 0) + 1
    return _object_names(root), plates


def list_objects(path: Path) -> list[ObjectInfo]:
    """One entry per <build><item>. Never raises: [] on anything unreadable."""
    try:
        with zipfile.ZipFile(path) as zf:
            items = _read_items(zf)
            names, plates = _read_settings(zf)
    except (OSError, zipfile.BadZipFile, ET.ParseError, KeyError, ValueError):
        return []
    out: list[ObjectInfo] = []
    for it in items:
        size = [round(it.box[1][a] - it.box[0][a], 2) for a in range(3)] if it.box else [0.0, 0.0, 0.0]
        centre = [round((it.box[0][a] + it.box[1][a]) / 2, 3) for a in range(2)] if it.box else [0.0, 0.0]
        out.append(
            ObjectInfo(
                index=it.index,
                name=names.get(it.object_id) or f"Object {it.index + 1}",
                plate=plates.get((it.object_id, it.instance), 1),
                width_mm=size[0],
                depth_mm=size[1],
                height_mm=size[2],
                center_x_mm=centre[0],
                center_y_mm=centre[1],
            )
        )
    return out


def plates_of_selection(path: Path, excluded: set[int]) -> set[int]:
    """Plates that still hold at least one non-excluded object."""
    return {o.plate for o in list_objects(path) if o.index not in excluded}


def _format_matrix(m: Matrix) -> str:
    parts = []
    for v in m:
        s = f"{v:.6f}".rstrip("0").rstrip(".")
        parts.append("0" if s in ("", "-0") else s)
    return " ".join(parts)


def _row_layout(items: list[_Item], sequence: list[int], gap_mm: float, center_x: float) -> list[tuple[float, float]]:
    """One (dx, dy) per entry of `sequence` (item indices, repeats allowed):
    the objects centred on center_x in X and stacked along Y starting at 0 with
    gap_mm between neighbours."""
    by_index = {it.index: it for it in items}
    cursor = 0.0
    shifts: list[tuple[float, float]] = []
    for idx in sequence:
        it = by_index[idx]
        if it.box is None:
            shifts.append((0.0, 0.0))
            continue
        (x0, y0, _), (x1, y1, _) = it.box
        shifts.append((center_x - (x0 + x1) / 2, cursor - y0))
        cursor += (y1 - y0) + gap_mm
    return shifts


def _block_shift(block: Box | None, center_x: float, cursor: float) -> tuple[float, float, float]:
    """(dx, dy, depth) that put a block's centre on center_x and its front edge at cursor."""
    if block is None:
        return 0.0, 0.0, 0.0
    (x0, y0, _), (x1, y1, _) = block
    return center_x - (x0 + x1) / 2, cursor - y0, y1 - y0


def _plate_row(
    items: list[_Item], final: list[int], plate_of: dict[int, int], copies: int, gap_mm: float, center_x: float
) -> tuple[list[int], list[tuple[float, float]]]:
    """The row for a file whose kept objects sit on several plates: each plate is one block that keeps
    the objects' arrangement within it, and the blocks follow one another along Y (plates in the order
    their first object appears in `final`), centred on center_x, with gap_mm between them. Returns the
    object indices in printed order (the whole row repeated per copy) and one (dx, dy) shift for each."""
    by_index = {it.index: it for it in items}
    plate_order = list(dict.fromkeys(plate_of[idx] for idx in final))
    sequence: list[int] = []
    shifts: list[tuple[float, float]] = []
    cursor = 0.0
    for _ in range(copies):
        for plate in plate_order:
            members = [idx for idx in final if plate_of[idx] == plate]
            block: Box | None = None
            for idx in members:
                block = _merge(block, by_index[idx].box)
            dx, dy, depth = _block_shift(block, center_x, cursor)
            sequence.extend(members)
            shifts.extend([(dx, dy)] * len(members))
            cursor += depth + gap_mm
    return sequence, shifts


_UUID_ATTR = re.compile(r'(p:UUID=")[^"]*(")')


def project_keys(path: Path, keys: tuple[str, ...]) -> set[str]:
    """Which of `keys` the project's own settings (Metadata/project_settings.config) define."""
    try:
        with zipfile.ZipFile(path) as zf:
            project = json.loads(zf.read(_PROJECT_SETTINGS))
    except (OSError, zipfile.BadZipFile, KeyError, ValueError):
        return set()
    return {k for k in keys if isinstance(project, dict) and k in project}


def keys_sized_for_fewer_filaments(path: Path, filament_count: int) -> set[str]:
    """Per-filament settings of a project saved with fewer filaments than are
    now requested. The slicer refuses a vector whose length no longer matches
    the filament count, so these have to go and let the chosen profiles
    supply values of the right size. Some are sized by filaments times
    extruder variants or by the flush matrix (filaments squared), so they are
    recognised by name as well as by length."""
    try:
        with zipfile.ZipFile(path) as zf:
            project = json.loads(zf.read(_PROJECT_SETTINGS))
    except (OSError, zipfile.BadZipFile, KeyError, ValueError):
        return set()
    if not isinstance(project, dict):
        return set()
    ids = project.get("filament_settings_id")
    saved = len(ids) if isinstance(ids, list) else 0
    if saved < 1 or filament_count <= saved:
        return set()
    return {
        k
        for k, v in project.items()
        if isinstance(v, list) and (len(v) == saved or k.startswith(("filament_", "flush_volumes_")))
    }


def _final_order(items: list[_Item], excluded: set[int], order: list[int] | None) -> list[int]:
    """Indices of the kept objects in printed order. `order` may be partial or stale."""
    kept = [it.index for it in items if it.index not in excluded]
    if not kept:
        raise ValueError("No objects left to print")
    if order is None:
        return kept
    kept_set = set(kept)
    wanted = [i for i in order if i in kept_set]
    wanted_set = set(wanted)
    return wanted + [i for i in kept if i not in wanted_set]


def _group_shifts(
    items: list[_Item], final: list[int], placement: tuple[float, float], count: int
) -> list[tuple[float, float]]:
    """One shift for each of `count` slots that moves the kept objects, as a group, to centre on placement."""
    group: Box | None = None
    for it in items:
        if it.index in set(final):
            group = _merge(group, it.box)
    if group is None:
        return [(0.0, 0.0)] * count
    dx = placement[0] - (group[0][0] + group[1][0]) / 2
    dy = placement[1] - (group[0][1] + group[1][1]) / 2
    return [(dx, dy)] * count


def _with_transform(tag: str, matrix: Matrix) -> str:
    """An <item> tag with its transform attribute set (added when it had none)."""
    value = _format_matrix(matrix)
    if _TRANSFORM_RE.search(tag):
        return _TRANSFORM_RE.sub(f'transform="{value}"', tag, count=1)
    return tag.replace("<item", f'<item transform="{value}"', 1)


def _item_tag(tag: str, item: _Item, shift: tuple[float, float] | None, *, is_copy: bool) -> str:
    """One <item> of the build, moved by shift, and given a fresh production UUID when it is a copy."""
    if shift is not None:
        nm = list(item.transform)
        nm[9] += shift[0]
        nm[10] += shift[1]
        tag = _with_transform(tag, nm)
    if is_copy:
        # A copy is its own item, so it needs its own production UUID.
        tag = _UUID_ATTR.sub(lambda m: f"{m.group(1)}{uuid.uuid4()}{m.group(2)}", tag)
    return tag


def _rewrite_build(
    model_text: str, items: list[_Item], sequence: list[int], shifts: list[tuple[float, float] | None]
) -> str:
    matches = list(_ITEM_RE.finditer(model_text))
    if len(matches) != len(items):
        raise ValueError("Unsupported 3MF build layout (items could not be rewritten safely)")
    by_index = {it.index: it for it in items}
    tags: list[str] = []
    seen_copy: dict[int, int] = {}
    for idx, shift in zip(sequence, shifts, strict=False):
        k = seen_copy.get(idx, 0)
        seen_copy[idx] = k + 1
        tags.append(_item_tag(matches[idx].group(0), by_index[idx], shift, is_copy=k > 0))
    return model_text[: matches[0].start()] + "".join(tags) + model_text[matches[-1].end() :]


def _edited_project_settings(
    zf: zipfile.ZipFile, bed_area: list[str] | None, bed_height: float | None, drop_keys: set[str] | None
) -> bytes | None:
    if not (bed_area or drop_keys):
        return None
    try:
        project = json.loads(zf.read(_PROJECT_SETTINGS)) if _PROJECT_SETTINGS in zf.namelist() else {}
    except (ValueError, KeyError):
        project = {}
    if bed_area:
        project["printable_area"] = list(bed_area)
        if bed_height:
            project["printable_height"] = f"{bed_height:g}"
    for key in drop_keys or ():
        project.pop(key, None)
    return json.dumps(project).encode()


def _write_replaced(
    zf: zipfile.ZipFile, dst: Path, replacements: dict[str, bytes | str | None], *, add_missing: str | None = None
) -> None:
    """Copy zf to dst, swapping in the replacement for each named file (None leaves a file as it is)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as out:
        for info in zf.infolist():
            replacement = replacements.get(info.filename)
            if replacement is None:
                out.writestr(info, zf.read(info.filename))
            else:
                out.writestr(info.filename, replacement)
        if add_missing is not None and replacements.get(add_missing) is not None and add_missing not in zf.namelist():
            out.writestr(add_missing, replacements[add_missing])  # type: ignore[arg-type]


def write_derived_3mf(
    src: Path,
    dst: Path,
    *,
    excluded: set[int],
    order: list[int] | None = None,
    gap_mm: float = 10.0,
    center_x: float = 0.0,
    placement: tuple[float, float] | None = None,
    copies: int = 1,
    bed_area: list[str] | None = None,
    bed_height: float | None = None,
    drop_project_keys: set[str] | None = None,
    by_plate: bool = True,
) -> list[int]:
    """Copy src to dst without the excluded objects.

    With `order`, the kept objects are also collapsed onto a single plate and
    laid out in that order along Y (see module docstring). `order` may be a
    partial or stale list: unknown indices are ignored and kept objects it
    leaves out follow in file order. Returns the kept indices in final order.
    `copies` repeats the whole kept selection that many times: in a row when
    `order` is given, otherwise stacked where they are (the caller lets the
    slicer arrange them).
    With `order`, kept objects on several plates go along the belt plate by plate (each plate a block that
    keeps its arrangement) unless `by_plate` is false, which puts every object in one row instead.
    `placement` moves the kept objects as a group so the centre of their
    footprint lands on (x, y); it is ignored when `order` is given.
    `bed_area` / `bed_height` (the printer's printable_area strings and
    height) are written into the project settings: OrcaSlicer's CLI
    re-centres a 3mf whose recorded bed differs from the printer's, which
    would move everything this function just placed.
    `drop_project_keys` removes those settings from the project settings: a
    file saved for another printer carries that printer's own values (e.g. a
    per-nozzle print area), which otherwise leak into a slice for a printer
    whose profile does not define them.
    Raises ValueError if nothing would be left or the file is not one this
    rewrite understands.
    """
    copies = max(1, int(copies))
    with zipfile.ZipFile(src) as zf:
        items = _read_items(zf)
        final = _final_order(items, excluded, order)
        # One slot per printed object: the whole selection, repeated.
        sequence = [idx for _ in range(copies) for idx in final]
        shifts: list[tuple[float, float] | None]
        if order is not None:
            _, plates_by_object = _read_settings(zf)
            plate_of = {it.index: plates_by_object.get((it.object_id, it.instance), 1) for it in items}
            if by_plate and len({plate_of[i] for i in final}) > 1:
                # Several plates: each one goes along the belt as a block, one after the other.
                sequence, row_shifts = _plate_row(items, final, plate_of, copies, gap_mm, center_x)
            else:
                row_shifts = _row_layout(items, sequence, gap_mm, center_x)
            shifts = list(row_shifts)
        elif placement is not None:
            shifts = list(_group_shifts(items, final, placement, len(sequence)))
        else:
            shifts = [None] * len(sequence)

        new_model = _rewrite_build(zf.read(_ROOT_MODEL).decode("utf-8"), items, sequence, shifts)
        new_settings: bytes | None = None
        if _MODEL_SETTINGS in zf.namelist():
            new_settings = _rewrite_settings(zf.read(_MODEL_SETTINGS), items, sequence, collapse=order is not None)
        project_settings = _edited_project_settings(zf, bed_area, bed_height, drop_project_keys)
        _write_replaced(
            zf,
            dst,
            {_ROOT_MODEL: new_model, _MODEL_SETTINGS: new_settings, _PROJECT_SETTINGS: project_settings},
            add_missing=_PROJECT_SETTINGS,
        )
    return final


def _instance_fields(inst: ET.Element) -> dict[str, str | None]:
    return {key: m.get("value") for m in inst.findall("metadata") if (key := m.get("key")) is not None}


def _detach_instances(
    plates: list[ET.Element], by_key: dict[tuple[str, int], int]
) -> dict[int, tuple[ET.Element, ET.Element]]:
    """Take every model_instance off its plate; returns item index -> (the plate it was on, its element)."""
    origin: dict[int, tuple[ET.Element, ET.Element]] = {}
    for plate in plates:
        counts: dict[str, int] = {}
        for inst in list(plate.findall("model_instance")):
            fields = _instance_fields(inst)
            object_id = fields.get("object_id") or ""
            k = _instance_number(fields, counts.get(object_id, 0))
            counts[object_id] = counts.get(object_id, 0) + 1
            if (object_id, k) in by_key:
                origin[by_key[(object_id, k)]] = (plate, inst)
            plate.remove(inst)
    return origin


def _number_instance(clone: ET.Element, n: int) -> None:
    for meta in clone.findall("metadata"):
        if meta.get("key") == "instance_id":
            meta.set("value", str(n))
            return
    ET.SubElement(clone, "metadata", {"key": "instance_id", "value": str(n)})


def _rewrite_settings(raw: bytes, items: list[_Item], sequence: list[int], *, collapse: bool) -> bytes:
    """Rebuild the plates' model_instance lists to match the new build: one
    instance per entry of `sequence` (item indices, repeats allowed; objects
    not in it are dropped), numbered by occurrence per object. With collapse,
    every plate is merged into plate 1."""
    root = DET.fromstring(raw)
    plates = root.findall("plate")
    origin = _detach_instances(plates, {(it.object_id, it.instance): it.index for it in items})
    if collapse and plates:
        for plate in plates[1:]:
            root.remove(plate)
        for meta in plates[0].findall("metadata"):
            if meta.get("key") == "plater_id":
                meta.set("value", "1")
    target_default = plates[0] if plates else None
    numbered: dict[str, int] = {}
    for idx in sequence:
        if idx not in origin:
            continue
        plate, inst = origin[idx]
        clone = copy.deepcopy(inst)
        object_id = _instance_fields(clone).get("object_id") or ""
        n = numbered.get(object_id, 0)
        numbered[object_id] = n + 1
        _number_instance(clone, n)
        cast("ET.Element", target_default if collapse else plate).append(clone)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _rotation(rx: float, ry: float, rz: float) -> list[list[float]]:
    """The 3x3 matrix for turning about X, then Y, then Z (degrees), each about the plate's own axes."""
    ax, ay, az = (math.radians(v) for v in (rx, ry, rz))
    cx, sx, cy, sy, cz, sz = math.cos(ax), math.sin(ax), math.cos(ay), math.sin(ay), math.cos(az), math.sin(az)
    rot_x: list[list[float]] = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]
    rot_y: list[list[float]] = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]
    rot_z: list[list[float]] = [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]

    def mul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
        return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]

    return mul(rot_z, mul(rot_y, rot_x))


@dataclass
class ObjectEdit:
    """Turn one object and put its footprint centre at (x, y) in plate coordinates."""

    index: int
    rotation: tuple[float, float, float]  # degrees: X, then Y, then Z
    x: float
    y: float


def _moved_matrix(item: _Item, box: Box, x: float, y: float) -> Matrix:
    """The item's transform with its footprint centre moved to (x, y); the height is kept."""
    (x0, y0, _), (x1, y1, _) = box
    new = list(item.transform)
    new[9] += x - (x0 + x1) / 2
    new[10] += y - (y0 + y1) / 2
    return new


def _rotate(rot: list[list[float]], v: Any) -> list[float]:
    return [sum(rot[i][k] * v[k] for k in range(3)) for i in range(3)]


def _extent(points: list[Any]) -> tuple[list[float], list[float]]:
    """Lowest and highest coordinate on each axis."""
    return [min(p[a] for p in points) for a in range(3)], [max(p[a] for p in points) for a in range(3)]


def _turned_matrix(item: _Item, edit: ObjectEdit, files: _ModelFiles) -> Matrix:
    """The item's transform after a turn about the centre of its box, dropped onto the plate at (x, y)."""
    old = item.transform
    rot = _rotation(*edit.rotation)
    # Where the object is now (world), then where it would be after the turn about its centre.
    points = [_apply(old, p) for p in files.local_points(_ROOT_MODEL, item.object_id)]
    if not points:
        raise ValueError(f"Object {edit.index} has no geometry")
    mins, maxs = _extent(points)
    centre = [(mins[a] + maxs[a]) / 2 for a in range(3)]
    turned = [_rotate(rot, [p[k] - centre[k] for k in range(3)]) for p in points]
    t_min, t_max = _extent(turned)
    shift = (edit.x - (t_min[0] + t_max[0]) / 2, edit.y - (t_min[1] + t_max[1]) / 2, -t_min[2])
    new: Matrix = []
    for j in range(3):
        new += _rotate(rot, old[3 * j : 3 * j + 3])
    offset = (old[9] - centre[0], old[10] - centre[1], old[11] - centre[2])
    return new + [r + s for r, s in zip(_rotate(rot, offset), shift, strict=True)]


def _edited_matrix(item: _Item, edit: ObjectEdit, files: _ModelFiles) -> Matrix:
    if item.box is None:
        raise ValueError(f"Object {edit.index} was not found")
    if all(abs(a) < 1e-9 for a in edit.rotation):
        return _moved_matrix(item, item.box, edit.x, edit.y)
    return _turned_matrix(item, edit, files)


def edit_objects_3mf(src: Path, dst: Path, edits: list[ObjectEdit]) -> None:
    """Copy src to dst with some objects turned and moved.

    Each edited object is turned about the centre of its own bounding box (about X, then Y, then Z, each
    about the plate's own axes), then placed so its footprint centre lands on (x, y). A turned object is
    also dropped so its lowest point rests on the plate; one that is only moved keeps its height. Only
    the object's <build><item> transform changes, so plates, colours and settings stay as they were.
    Raises ValueError for an unknown object or a file this rewrite does not understand.
    """
    with zipfile.ZipFile(src) as zf:
        items = _read_items(zf)
        files = _ModelFiles(zf)
        by_index = {it.index: it for it in items}
        model_text = zf.read(_ROOT_MODEL).decode("utf-8")
        matches = list(_ITEM_RE.finditer(model_text))
        if len(matches) != len(items):
            raise ValueError("Unsupported 3MF build layout (items could not be rewritten safely)")
        tags: dict[int, str] = {}
        for edit in edits:
            it = by_index.get(edit.index)
            if it is None:
                raise ValueError(f"Object {edit.index} was not found")
            tags[edit.index] = _with_transform(matches[edit.index].group(0), _edited_matrix(it, edit, files))
        out_model: list[str] = []
        cursor = 0
        for i, match in enumerate(matches):
            out_model.append(model_text[cursor : match.start()])
            out_model.append(tags.get(i, match.group(0)))
            cursor = match.end()
        out_model.append(model_text[cursor:])
        _write_replaced(zf, dst, {_ROOT_MODEL: "".join(out_model)})
