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

import json
import re
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
    items: list[_Item], order: list[int], gap_mm: float, center_x: float
) -> dict[int, tuple[float, float]]:
    """index -> (dx, dy): objects in `order`, each centred on center_x in X and
    stacked along Y starting at 0 with gap_mm between neighbours."""
    by_index = {it.index: it for it in items}
    cursor = 0.0
    shifts: dict[int, tuple[float, float]] = {}
    for idx in order:
        it = by_index[idx]
        if it.box is None:
            shifts[idx] = (0.0, 0.0)
            continue
        (x0, y0, _), (x1, y1, _) = it.box
        shifts[idx] = (center_x - (x0 + x1) / 2, cursor - y0)
        cursor += (y1 - y0) + gap_mm
    return shifts


def write_derived_3mf(
    src: Path,
    dst: Path,
    *,
    excluded: set[int],
    order: list[int] | None = None,
    gap_mm: float = 10.0,
    center_x: float = 0.0,
    placement: tuple[float, float] | None = None,
    bed_area: list[str] | None = None,
    bed_height: float | None = None,
) -> list[int]:
    """Copy src to dst without the excluded objects.

    With `order`, the kept objects are also collapsed onto a single plate and
    laid out in that order along Y (see module docstring). `order` may be a
    partial or stale list: unknown indices are ignored and kept objects it
    leaves out follow in file order. Returns the kept indices in final order.
    `placement` moves the kept objects as a group so the centre of their
    footprint lands on (x, y); it is ignored when `order` is given.
    `bed_area` / `bed_height` (the printer's printable_area strings and
    height) are written into the project settings: OrcaSlicer's CLI
    re-centres a 3mf whose recorded bed differs from the printer's, which
    would move everything this function just placed.
    Raises ValueError if nothing would be left or the file is not one this
    rewrite understands.
    """
    with zipfile.ZipFile(src) as zf:
        items = _read_items(zf)
        kept = [it.index for it in items if it.index not in excluded]
        if not kept:
            raise ValueError("No objects left to print")
        final = kept
        if order is not None:
            wanted = [i for i in order if i in set(kept)]
            final = wanted + [i for i in kept if i not in set(wanted)]
        shifts = _row_layout(items, final, gap_mm, center_x) if order is not None else {}
        if order is None and placement is not None:
            group: Box | None = None
            for it in items:
                if it.index in set(kept):
                    group = _merge(group, it.box)
            if group is not None:
                dx = placement[0] - (group[0][0] + group[1][0]) / 2
                dy = placement[1] - (group[0][1] + group[1][1]) / 2
                shifts = {i: (dx, dy) for i in kept}

        model_text = zf.read(_ROOT_MODEL).decode("utf-8")
        matches = list(_ITEM_RE.finditer(model_text))
        if len(matches) != len(items):
            raise ValueError("Unsupported 3MF build layout (items could not be rewritten safely)")
        pieces: list[str] = []
        last = 0
        for m, it in zip(matches, items):
            pieces.append(model_text[last : m.start()])
            last = m.end()
            if it.index in excluded:
                continue
            tag = m.group(0)
            if it.index in shifts:
                dx, dy = shifts[it.index]
                nm = list(it.transform)
                nm[9] += dx
                nm[10] += dy
                value = _format_matrix(nm)
                if _TRANSFORM_RE.search(tag):
                    tag = _TRANSFORM_RE.sub(f'transform="{value}"', tag, count=1)
                else:
                    tag = tag.replace("<item", f'<item transform="{value}"', 1)
            pieces.append(tag)
        pieces.append(model_text[last:])
        new_model = "".join(pieces)

        new_settings: bytes | None = None
        if _MODEL_SETTINGS in zf.namelist():
            new_settings = _rewrite_settings(
                zf.read(_MODEL_SETTINGS), items, excluded, final if order is not None else None
            )

        project_settings: bytes | None = None
        if bed_area:
            try:
                project = json.loads(zf.read(_PROJECT_SETTINGS)) if _PROJECT_SETTINGS in zf.namelist() else {}
            except (ValueError, KeyError):
                project = {}
            project["printable_area"] = list(bed_area)
            if bed_height:
                project["printable_height"] = f"{bed_height:g}"
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


def _rewrite_settings(
    raw: bytes, items: list[_Item], excluded: set[int], single_plate_order: list[int] | None
) -> bytes:
    """Drop excluded objects' model_instances. With single_plate_order, also
    merge every plate into plate 1 with the instances in that order."""
    root = ET.fromstring(raw)
    dropped = {(it.object_id, it.instance) for it in items if it.index in excluded}
    by_key = {(it.object_id, it.instance): it.index for it in items}
    plates = root.findall("plate")
    collected: dict[int, ET.Element] = {}
    for plate in plates:
        counts: dict[str, int] = {}
        for inst in list(plate.findall("model_instance")):
            fields = {m.get("key"): m.get("value") for m in inst.findall("metadata")}
            object_id = fields.get("object_id") or ""
            try:
                k = int(fields["instance_id"]) if "instance_id" in fields else counts.get(object_id, 0)
            except (TypeError, ValueError):
                k = counts.get(object_id, 0)
            counts[object_id] = counts.get(object_id, 0) + 1
            if (object_id, k) in dropped:
                plate.remove(inst)
            elif (object_id, k) in by_key:
                collected[by_key[(object_id, k)]] = inst
    if single_plate_order is not None and plates:
        first = plates[0]
        for plate in plates[1:]:
            root.remove(plate)
        for inst in list(first.findall("model_instance")):
            first.remove(inst)
        for idx in single_plate_order:
            if idx in collected:
                first.append(collected[idx])
        for meta in first.findall("metadata"):
            if meta.get("key") == "plater_id":
                meta.set("value", "1")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
