"""Upload-time check of an STL for the mesh defects OrcaSlicer repairs itself.

The slicer already repairs these when it loads the file, silently. This only
finds out what is wrong so the user can be told, and so a defect it cannot
repair (holes) is flagged rather than discovered as a bad print. Pure Python,
no mesh library: the file is welded by exact vertex coordinates and its edges
are counted.

Fixed by the slicer on load (verified against the CLI with --info):
degenerate and duplicate triangles, inconsistent triangle orientation, and a
mesh that is inside-out. Not fixed: open edges (holes) and edges shared by
more than two triangles.
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

from .schemas import MeshReport

# Above this a Python pass costs too long inside an upload request.
_MAX_TRIANGLES = 1_500_000
_ASCII_VERTEX = re.compile(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)")


def _read_triangles(path: Path) -> list[tuple[tuple[float, float, float], ...]] | None:
    """Triangles as ((x,y,z),(x,y,z),(x,y,z)); None if unreadable or too big."""
    data = path.read_bytes()
    if len(data) >= 84:
        (count,) = struct.unpack_from("<I", data, 80)
        if 84 + 50 * count == len(data):  # a binary STL's size is fixed by its header
            if count > _MAX_TRIANGLES:
                return None
            tris = []
            for i in range(count):
                v = struct.unpack_from("<9f", data, 84 + 50 * i + 12)
                tris.append(((v[0], v[1], v[2]), (v[3], v[4], v[5]), (v[6], v[7], v[8])))
            return tris
    # ASCII
    try:
        coords = [(float(m.group(1)), float(m.group(2)), float(m.group(3))) for m in _ASCII_VERTEX.finditer(data)]
    except ValueError:
        return None
    if not coords or len(coords) % 3 or len(coords) // 3 > _MAX_TRIANGLES:
        return None
    return [(coords[i], coords[i + 1], coords[i + 2]) for i in range(0, len(coords), 3)]


def analyze_stl(path: Path) -> MeshReport | None:
    """None when the file cannot be analysed (not a readable STL, too large)."""
    try:
        tris = _read_triangles(path)
    except OSError:
        return None
    if not tris:
        return None

    ids: dict[tuple[float, float, float], int] = {}
    faces: list[tuple[int, int, int]] = []
    degenerate = 0
    signed_volume = 0.0
    for a, b, c in tris:
        ia = ids.setdefault(a, len(ids))
        ib = ids.setdefault(b, len(ids))
        ic = ids.setdefault(c, len(ids))
        cross_x = (b[1] - a[1]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[1] - a[1])
        cross_y = (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2])
        cross_z = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if ia == ib or ib == ic or ia == ic or (cross_x == 0 and cross_y == 0 and cross_z == 0):
            degenerate += 1
            continue
        faces.append((ia, ib, ic))
        signed_volume += (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0

    seen: set[tuple[int, int, int]] = set()
    unique: list[tuple[int, int, int]] = []
    duplicate = 0
    for f in faces:
        key = tuple(sorted(f))
        if key in seen:
            duplicate += 1
        else:
            seen.add(key)
            unique.append(f)

    # edge -> forward uses + 65536 * backward uses (a<b counts as forward)
    edges: dict[int, int] = {}
    n = len(ids) + 1
    for a, b, c in unique:
        for u, v in ((a, b), (b, c), (c, a)):
            key = (u * n + v) if u < v else (v * n + u)
            edges[key] = edges.get(key, 0) + (1 if u < v else 65536)
    open_edges = nonmanifold = inconsistent = 0
    for val in edges.values():
        forward, backward = val & 0xFFFF, val >> 16
        uses = forward + backward
        if uses == 1:
            open_edges += 1
        elif uses > 2:
            nonmanifold += 1
        elif forward != backward:
            inconsistent += 1

    inverted = signed_volume < 0 and inconsistent == 0 and open_edges == 0
    report = MeshReport(
        degenerate_faces=degenerate,
        duplicate_faces=duplicate,
        inconsistent_edges=inconsistent,
        inverted=inverted,
        open_edges=open_edges,
        nonmanifold_edges=nonmanifold,
    )
    return report
