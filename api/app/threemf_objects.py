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

import copy
import json
import math
import re
import uuid
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

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
            self._roots[path] = ET.fromstring(self._zf.read(path))
        return self._roots[path]

    def _find_object(self, path: str, object_id: str) -> ET.Element | None:
        resources = self.root(path).find(_c("resources"))
        if resources is None:
            return None
        for obj in resources.findall(_c("object")):
            if obj.get("id") == object_id:
                return obj
        return None

    def local_box(self, path: str, object_id: str, _depth: int = 0) -> Box | None:
        """Box of one object in its own coordinates (components applied)."""
        key = (path.lstrip("/"), object_id)
        if key in self._boxes:
            return self._boxes[key]
        box: Box | None = None
        obj = self._find_object(path, object_id)
        if obj is not None and _depth < 16:
            mesh = obj.find(_c("mesh"))
            if mesh is not None:
                verts = mesh.find(_c("vertices"))
                if verts is not None:
                    xs, ys, zs = [], [], []
                    for v in verts.findall(_c("vertex")):
                        xs.append(float(v.get("x", 0)))
                        ys.append(float(v.get("y", 0)))
                        zs.append(float(v.get("z", 0)))
                    if xs:
                        box = ((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))
            comps = obj.find(_c("components"))
            if comps is not None:
                for comp in comps.findall(_c("component")):
                    child_path = comp.get(f"{{{_PROD}}}path") or path
                    child = self.local_box(child_path, comp.get("objectid", ""), _depth + 1)
                    if child is not None:
                        box = _merge(box, _transform_box(_parse_matrix(comp.get("transform")), child))
        self._boxes[key] = box
        return box

    def local_points(self, path: str, object_id: str, matrix: Matrix | None = None, _depth: int = 0):
        """Every vertex of one object in its own coordinates (components applied), one at a time."""
        obj = self._find_object(path, object_id)
        if obj is None or _depth >= 16:
            return
        m = matrix or list(_IDENTITY)
        mesh = obj.find(_c("mesh"))
        if mesh is not None:
            verts = mesh.find(_c("vertices"))
            if verts is not None:
                for v in verts.findall(_c("vertex")):
                    yield _apply(m, (float(v.get("x", 0)), float(v.get("y", 0)), float(v.get("z", 0))))
        comps = obj.find(_c("components"))
        if comps is not None:
            for comp in comps.findall(_c("component")):
                child_path = comp.get(f"{{{_PROD}}}path") or path
                yield from self.local_points(
                    child_path, comp.get("objectid", ""), _compose(m, _parse_matrix(comp.get("transform"))), _depth + 1
                )


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


def _read_settings(zf: zipfile.ZipFile) -> tuple[dict[str, str], dict[tuple[str, int], int]]:
    """(object_id -> name, (object_id, instance) -> plate index)."""
    names: dict[str, str] = {}
    plates: dict[tuple[str, int], int] = {}
    try:
        root = ET.fromstring(zf.read(_MODEL_SETTINGS))
    except (KeyError, ET.ParseError):
        return names, plates
    for obj in root.findall("object"):
        for meta in obj.findall("metadata"):
            if meta.get("key") == "name" and obj.get("id"):
                names[obj.get("id", "")] = meta.get("value", "")
                break
    for n, plate in enumerate(root.findall("plate"), start=1):
        index = n
        for meta in plate.findall("metadata"):
            if meta.get("key") == "plater_id":
                try:
                    index = int(meta.get("value", n))
                except ValueError:
                    pass
        counts: dict[str, int] = {}
        for inst in plate.findall("model_instance"):
            fields = {m.get("key"): m.get("value") for m in inst.findall("metadata")}
            object_id = fields.get("object_id") or ""
            try:
                k = int(fields["instance_id"]) if "instance_id" in fields else counts.get(object_id, 0)
            except (TypeError, ValueError):
                k = counts.get(object_id, 0)
            counts[object_id] = counts.get(object_id, 0) + 1
            plates[(object_id, k)] = index
    return names, plates


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
        size = (
            [round(it.box[1][a] - it.box[0][a], 2) for a in range(3)] if it.box else [0.0, 0.0, 0.0]
        )
        centre = (
            [round((it.box[0][a] + it.box[1][a]) / 2, 3) for a in range(2)] if it.box else [0.0, 0.0]
        )
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


def _row_layout(
    items: list[_Item], sequence: list[int], gap_mm: float, center_x: float
) -> list[tuple[float, float]]:
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


def _plate_row(
    items: list[_Item], final: list[int], plate_of: dict[int, int], copies: int, gap_mm: float, center_x: float
) -> tuple[list[int], list[tuple[float, float]]]:
    """The row for a file whose kept objects sit on several plates: each plate is one block that keeps
    the objects' arrangement within it, and the blocks follow one another along Y (plates in the order
    their first object appears in `final`), centred on center_x, with gap_mm between them. Returns the
    object indices in printed order (the whole row repeated per copy) and one (dx, dy) shift for each."""
    by_index = {it.index: it for it in items}
    plate_order: list[int] = []
    for idx in final:
        if plate_of[idx] not in plate_order:
            plate_order.append(plate_of[idx])
    sequence: list[int] = []
    shifts: list[tuple[float, float]] = []
    cursor = 0.0
    for _ in range(copies):
        for plate in plate_order:
            members = [idx for idx in final if plate_of[idx] == plate]
            block: Box | None = None
            for idx in members:
                block = _merge(block, by_index[idx].box)
            if block is None:
                dx, dy, depth = 0.0, 0.0, 0.0
            else:
                (x0, y0, _), (x1, y1, _) = block
                dx, dy, depth = center_x - (x0 + x1) / 2, cursor - y0, y1 - y0
            for idx in members:
                sequence.append(idx)
                shifts.append((dx, dy))
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
        kept = [it.index for it in items if it.index not in excluded]
        if not kept:
            raise ValueError("No objects left to print")
        final = kept
        if order is not None:
            wanted = [i for i in order if i in set(kept)]
            final = wanted + [i for i in kept if i not in set(wanted)]
        # One slot per printed object: the whole selection, repeated.
        sequence = [idx for _ in range(copies) for idx in final]
        plate_of: dict[int, int] = {}
        if order is not None:
            _, plates_by_object = _read_settings(zf)
            plate_of = {it.index: plates_by_object.get((it.object_id, it.instance), 1) for it in items}
        if order is not None and by_plate and len({plate_of[i] for i in final}) > 1:
            # Several plates: each one goes along the belt as a block, one after the other.
            sequence, shifts = _plate_row(items, final, plate_of, copies, gap_mm, center_x)
        elif order is not None:
            shifts = _row_layout(items, sequence, gap_mm, center_x)
        elif placement is not None:
            group: Box | None = None
            for it in items:
                if it.index in set(kept):
                    group = _merge(group, it.box)
            if group is not None:
                dx = placement[0] - (group[0][0] + group[1][0]) / 2
                dy = placement[1] - (group[0][1] + group[1][1]) / 2
                shifts = [(dx, dy)] * len(sequence)
            else:
                shifts = [(0.0, 0.0)] * len(sequence)
        else:
            shifts = [None] * len(sequence)  # type: ignore[list-item]

        model_text = zf.read(_ROOT_MODEL).decode("utf-8")
        matches = list(_ITEM_RE.finditer(model_text))
        if len(matches) != len(items):
            raise ValueError("Unsupported 3MF build layout (items could not be rewritten safely)")
        by_index = {it.index: it for it in items}
        tags: list[str] = []
        seen_copy: dict[int, int] = {}
        for idx, shift in zip(sequence, shifts):
            it = by_index[idx]
            tag = matches[idx].group(0)
            k = seen_copy.get(idx, 0)
            seen_copy[idx] = k + 1
            if shift is not None:
                nm = list(it.transform)
                nm[9] += shift[0]
                nm[10] += shift[1]
                value = _format_matrix(nm)
                if _TRANSFORM_RE.search(tag):
                    tag = _TRANSFORM_RE.sub(f'transform="{value}"', tag, count=1)
                else:
                    tag = tag.replace("<item", f'<item transform="{value}"', 1)
            if k > 0:
                # A copy is its own item, so it needs its own production UUID.
                tag = _UUID_ATTR.sub(lambda m: f"{m.group(1)}{uuid.uuid4()}{m.group(2)}", tag)
            tags.append(tag)
        new_model = model_text[: matches[0].start()] + "".join(tags) + model_text[matches[-1].end() :]

        new_settings: bytes | None = None
        if _MODEL_SETTINGS in zf.namelist():
            new_settings = _rewrite_settings(zf.read(_MODEL_SETTINGS), items, sequence, collapse=order is not None)

        project_settings: bytes | None = None
        if bed_area or drop_project_keys:
            try:
                project = json.loads(zf.read(_PROJECT_SETTINGS)) if _PROJECT_SETTINGS in zf.namelist() else {}
            except (ValueError, KeyError):
                project = {}
            if bed_area:
                project["printable_area"] = list(bed_area)
                if bed_height:
                    project["printable_height"] = f"{bed_height:g}"
            for key in drop_project_keys or ():
                project.pop(key, None)
            project_settings = json.dumps(project).encode()

        dst.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as out:
            for info in zf.infolist():
                if info.filename == _ROOT_MODEL:
                    out.writestr(info.filename, new_model)
                elif info.filename == _MODEL_SETTINGS and new_settings is not None:
                    out.writestr(info.filename, new_settings)
                elif info.filename == _PROJECT_SETTINGS and project_settings is not None:
                    out.writestr(info.filename, project_settings)
                else:
                    out.writestr(info, zf.read(info.filename))
            if project_settings is not None and _PROJECT_SETTINGS not in zf.namelist():
                out.writestr(_PROJECT_SETTINGS, project_settings)
    return final


def _instance_fields(inst: ET.Element) -> dict[str, str | None]:
    return {m.get("key"): m.get("value") for m in inst.findall("metadata")}


def _rewrite_settings(raw: bytes, items: list[_Item], sequence: list[int], *, collapse: bool) -> bytes:
    """Rebuild the plates' model_instance lists to match the new build: one
    instance per entry of `sequence` (item indices, repeats allowed; objects
    not in it are dropped), numbered by occurrence per object. With collapse,
    every plate is merged into plate 1."""
    root = ET.fromstring(raw)
    by_key = {(it.object_id, it.instance): it.index for it in items}
    plates = root.findall("plate")
    # item index -> (the plate it was on, its instance element)
    origin: dict[int, tuple[ET.Element, ET.Element]] = {}
    for plate in plates:
        counts: dict[str, int] = {}
        for inst in list(plate.findall("model_instance")):
            fields = _instance_fields(inst)
            object_id = fields.get("object_id") or ""
            try:
                k = int(fields["instance_id"]) if "instance_id" in fields else counts.get(object_id, 0)
            except (TypeError, ValueError):
                k = counts.get(object_id, 0)
            counts[object_id] = counts.get(object_id, 0) + 1
            if (object_id, k) in by_key:
                origin[by_key[(object_id, k)]] = (plate, inst)
            plate.remove(inst)
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
        for meta in clone.findall("metadata"):
            if meta.get("key") == "instance_id":
                meta.set("value", str(n))
                break
        else:
            ET.SubElement(clone, "metadata", {"key": "instance_id", "value": str(n)})
        (target_default if collapse else plate).append(clone)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _rotation(rx: float, ry: float, rz: float) -> list[list[float]]:
    """The 3x3 matrix for turning about X, then Y, then Z (degrees), each about the plate's own axes."""
    ax, ay, az = (math.radians(v) for v in (rx, ry, rz))
    cx, sx, cy, sy, cz, sz = math.cos(ax), math.sin(ax), math.cos(ay), math.sin(ay), math.cos(az), math.sin(az)
    rot_x = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]
    rot_y = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]
    rot_z = [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]

    def mul(a, b):
        return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]

    return mul(rot_z, mul(rot_y, rot_x))


@dataclass
class ObjectEdit:
    """Turn one object and put its footprint centre at (x, y) in plate coordinates."""

    index: int
    rotation: tuple[float, float, float]  # degrees: X, then Y, then Z
    x: float
    y: float


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
            if it is None or it.box is None:
                raise ValueError(f"Object {edit.index} was not found")
            old = it.transform
            if all(abs(a) < 1e-9 for a in edit.rotation):
                (x0, y0, _), (x1, y1, _) = it.box
                new = list(old)
                new[9] += edit.x - (x0 + x1) / 2
                new[10] += edit.y - (y0 + y1) / 2
            else:
                rot = _rotation(*edit.rotation)
                # Where the object is now (world), then where it would be after the turn about its centre.
                points = [_apply(old, p) for p in files.local_points(_ROOT_MODEL, it.object_id)]
                if not points:
                    raise ValueError(f"Object {edit.index} has no geometry")
                mins = [min(p[a] for p in points) for a in range(3)]
                maxs = [max(p[a] for p in points) for a in range(3)]
                centre = [(mins[a] + maxs[a]) / 2 for a in range(3)]
                turned = [
                    tuple(sum(rot[i][k] * (p[k] - centre[k]) for k in range(3)) for i in range(3)) for p in points
                ]
                t_min = [min(p[a] for p in turned) for a in range(3)]
                t_max = [max(p[a] for p in turned) for a in range(3)]
                shift = (edit.x - (t_min[0] + t_max[0]) / 2, edit.y - (t_min[1] + t_max[1]) / 2, -t_min[2])
                new = []
                for j in range(3):
                    col = (old[3 * j], old[3 * j + 1], old[3 * j + 2])
                    new += [sum(rot[i][k] * col[k] for k in range(3)) for i in range(3)]
                offset = (old[9] - centre[0], old[10] - centre[1], old[11] - centre[2])
                new += [sum(rot[i][k] * offset[k] for k in range(3)) + shift[i] for i in range(3)]
            tag = matches[edit.index].group(0)
            value = _format_matrix(new)
            if _TRANSFORM_RE.search(tag):
                tag = _TRANSFORM_RE.sub(f'transform="{value}"', tag, count=1)
            else:
                tag = tag.replace("<item", f'<item transform="{value}"', 1)
            tags[edit.index] = tag
        out_model = []
        cursor = 0
        for i, match in enumerate(matches):
            out_model.append(model_text[cursor : match.start()])
            out_model.append(tags.get(i, match.group(0)))
            cursor = match.end()
        out_model.append(model_text[cursor:])
        new_model = "".join(out_model)
        dst.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as out:
            for info in zf.infolist():
                if info.filename == _ROOT_MODEL:
                    out.writestr(info.filename, new_model)
                else:
                    out.writestr(info, zf.read(info.filename))
