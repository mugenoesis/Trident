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
from typing import cast

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


Vertex = tuple[float, float, float]
Face = tuple[int, int, int]


def _is_degenerate(a: Vertex, b: Vertex, c: Vertex, ia: int, ib: int, ic: int) -> bool:
    """A triangle with a repeated corner, or whose corners lie on one line."""
    if ia in (ib, ic) or ib == ic:
        return True
    cross_x = (b[1] - a[1]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[1] - a[1])
    cross_y = (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2])
    cross_z = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return cross_x == 0 and cross_y == 0 and cross_z == 0


def _tetra_volume(a: Vertex, b: Vertex, c: Vertex) -> float:
    """Signed volume of the tetrahedron from the origin to a triangle."""
    return (
        a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0])
    ) / 6.0


def _welded_faces(tris) -> tuple[list[Face], int, float, int]:
    """(faces on shared vertex ids, degenerate triangles dropped, signed volume, vertex count)."""
    ids: dict[Vertex, int] = {}
    faces: list[Face] = []
    degenerate = 0
    signed_volume = 0.0
    for a, b, c in tris:
        ia = ids.setdefault(a, len(ids))
        ib = ids.setdefault(b, len(ids))
        ic = ids.setdefault(c, len(ids))
        if _is_degenerate(a, b, c, ia, ib, ic):
            degenerate += 1
            continue
        faces.append((ia, ib, ic))
        signed_volume += _tetra_volume(a, b, c)
    return faces, degenerate, signed_volume, len(ids)


def _unique_faces(faces: list[Face]) -> tuple[list[Face], int]:
    """The faces with repeats (the same three corners in any order) dropped, and how many were dropped."""
    seen: set[Face] = set()
    unique: list[Face] = []
    for f in faces:
        key = cast("Face", tuple(sorted(f)))
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique, len(faces) - len(unique)


def _edge_counts(faces: list[Face], vertex_count: int) -> tuple[int, int, int]:
    """(open edges, edges shared by more than two faces, edges whose two faces disagree on direction)."""
    # edge -> forward uses + 65536 * backward uses (a<b counts as forward)
    edges: dict[int, int] = {}
    n = vertex_count + 1
    for a, b, c in faces:
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
    return open_edges, nonmanifold, inconsistent


def analyze_stl(path: Path) -> MeshReport | None:
    """None when the file cannot be analysed (not a readable STL, too large)."""
    try:
        tris = _read_triangles(path)
    except OSError:
        return None
    if not tris:
        return None

    faces, degenerate, signed_volume, vertex_count = _welded_faces(tris)
    unique, duplicate = _unique_faces(faces)
    open_edges, nonmanifold, inconsistent = _edge_counts(unique, vertex_count)
    return MeshReport(
        degenerate_faces=degenerate,
        duplicate_faces=duplicate,
        inconsistent_edges=inconsistent,
        inverted=signed_volume < 0 and inconsistent == 0 and open_edges == 0,
        open_edges=open_edges,
        nonmanifold_edges=nonmanifold,
    )
