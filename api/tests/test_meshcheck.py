import io
import struct
from pathlib import Path

from app.meshcheck import analyze_stl

_V = [(0, 0, 0), (20, 0, 0), (20, 20, 0), (0, 20, 0), (0, 0, 20), (20, 0, 20), (20, 20, 20), (0, 20, 20)]
_T = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]


def _binary(tmp_path: Path, name: str, tris) -> Path:
    buf = io.BytesIO()
    buf.write(b"binary stl".ljust(80, b"\0"))
    buf.write(struct.pack("<I", len(tris)))
    for a, b, c in tris:
        buf.write(struct.pack("<12fH", 0, 0, 0, *_V[a], *_V[b], *_V[c], 0))
    path = tmp_path / name
    path.write_bytes(buf.getvalue())
    return path


def _ascii(tmp_path: Path, name: str, tris) -> Path:
    lines = ["solid x"]
    for tri in tris:
        lines += ["facet normal 0 0 0", "outer loop"] + [f"vertex {_V[i][0]} {_V[i][1]} {_V[i][2]}" for i in tri] + ["endloop", "endfacet"]
    lines.append("endsolid x")
    path = tmp_path / name
    path.write_text("\n".join(lines))
    return path


def test_clean_cube_reports_nothing(tmp_path):
    for write in (_binary, _ascii):
        report = analyze_stl(write(tmp_path, "c.stl", _T))
        assert report is not None and not report.fixed and not report.warnings


def test_holes_are_a_warning_not_a_fix(tmp_path):
    report = analyze_stl(_binary(tmp_path, "h.stl", _T[:10]))
    assert report.open_edges == 4
    assert len(report.warnings) == 1 and "4 open edges" in report.warnings[0]
    assert report.fixed == []


def test_flipped_face_is_found(tmp_path):
    tris = [(a, c, b) if i == 3 else (a, b, c) for i, (a, b, c) in enumerate(_T)]
    report = analyze_stl(_binary(tmp_path, "f.stl", tris))
    assert report.inconsistent_edges > 0
    assert "flipped faces corrected" in report.fixed
    assert report.warnings == []


def test_duplicate_and_degenerate_faces_are_counted(tmp_path):
    report = analyze_stl(_ascii(tmp_path, "d.stl", [*_T, _T[0], (0, 0, 1)]))
    assert report.duplicate_faces == 1
    assert report.degenerate_faces == 1
    assert report.fixed == ["1 duplicate face removed", "1 degenerate face removed"]


def test_inside_out_mesh(tmp_path):
    report = analyze_stl(_binary(tmp_path, "i.stl", [(a, c, b) for a, b, c in _T]))
    assert report.inverted and report.inconsistent_edges == 0
    assert report.fixed == ["inside-out mesh turned the right way round"]


def test_unreadable_returns_none(tmp_path):
    path = tmp_path / "x.stl"
    path.write_bytes(b"fake stl bytes")
    assert analyze_stl(path) is None
