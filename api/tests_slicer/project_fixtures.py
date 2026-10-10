"""Builds multi-colour 3MF projects the way a slicer would save them, using the real slicer, for the slicer tests."""
from __future__ import annotations

import re
import struct
import subprocess
import tempfile
import zipfile
from pathlib import Path


def _subdivided_cube_stl(path: Path, size: float = 30.0, grid: int = 8) -> None:
    """A cube whose faces are split into grid x grid squares, so triangles can be painted in many colours."""
    tris = []
    step = size / grid

    def quad(p, u, v):
        a = p
        b = (p[0] + u[0], p[1] + u[1], p[2] + u[2])
        c = (p[0] + u[0] + v[0], p[1] + u[1] + v[1], p[2] + u[2] + v[2])
        d = (p[0] + v[0], p[1] + v[1], p[2] + v[2])
        return [(a, b, c), (a, c, d)]

    for i in range(grid):
        for j in range(grid):
            x, y = i * step, j * step
            tris += quad((x, y, 0), (0, step, 0), (step, 0, 0))            # bottom (facing -z)
            tris += quad((x, y, size), (step, 0, 0), (0, step, 0))         # top
            tris += quad((x, 0, y), (step, 0, 0), (0, 0, step))            # front (-y)
            tris += quad((x, size, y), (0, 0, step), (step, 0, 0))         # back
            tris += quad((0, x, y), (0, 0, step), (0, step, 0))            # left
            tris += quad((size, x, y), (0, step, 0), (0, 0, step))         # right
    with path.open("wb") as fh:
        fh.write(b"\0" * 80 + struct.pack("<I", len(tris)))
        for a, b, c in tris:
            fh.write(struct.pack("<12fH", 0, 0, 0, *a, *b, *c, 0))


def paint_code(state: int) -> str:
    """The paint_color value for filament number `state` (1-based), as the slicer writes it."""
    if state <= 1:
        return "4"
    if state == 2:
        return "8"
    return format(((state - 3) << 4) | 0xC, "02X")


def make_project(out: Path, *, authoring_printer: str, authoring_process: str, authoring_filament: str, colours: int, bin_path: str, datadir: str, resolved_dir: Path, painted: bool = True) -> Path:
    """Export a project saved for `authoring_printer` with `colours` filaments, painted in all of them."""
    from app import cli_runner

    work = Path(tempfile.mkdtemp(prefix="mcfix-"))
    stl = work / "cube.stl"
    _subdivided_cube_stl(stl)
    printer = cli_runner._write_resolved_profile(cli_runner._resolve_profile_detail("machine", authoring_printer), resolved_dir, "printer")
    process = cli_runner._write_resolved_profile(cli_runner._resolve_profile_detail("process", authoring_process), resolved_dir, "process")
    filaments = [
        cli_runner._write_resolved_profile(cli_runner._resolve_profile_detail("filament", authoring_filament), resolved_dir, f"filament_{i}")
        for i in range(colours)
    ]
    raw = work / "raw.3mf"
    cmd = [bin_path, "--datadir", datadir, "--outputdir", str(work), "--arrange=1", "--load-settings", f"{printer};{process}",
           "--load-filaments", ";".join(filaments), "--export-3mf", raw.name, str(stl)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if not raw.is_file():
        raise RuntimeError(f"could not export the project (exit {proc.returncode}): {proc.stdout[-400:]} {proc.stderr[-400:]}")
    zin = zipfile.ZipFile(raw)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if painted and info.filename.startswith("3D/Objects/") and info.filename.endswith(".model"):
                text = data.decode()
                counter = [0]

                def repaint(match):
                    state = counter[0] % colours + 1
                    counter[0] += 1
                    return f'<triangle {match.group(1)} paint_color="{paint_code(state)}"/>' if state > 1 else match.group(0)

                text = re.sub(r"<triangle ([^>/]*?)/>", repaint, text)
                data = text.encode()
            if info.filename.endswith("project_settings.config"):
                import json
                proj = json.loads(data)
                palette = ["#F2754E", "#3F8E43", "#2A6FDB", "#E8C547", "#8A4FBF", "#D94F8C", "#4FC0C0", "#222222", "#FFFFFF", "#7A7A7A", "#A0522D", "#00FF7F", "#FF8C00", "#1E90FF", "#C71585", "#556B2F"]
                proj["filament_colour"] = palette[:colours]
                # A saved project sizes the purge matrix to its filament count (the exported default is always 4 x 4).
                proj["flush_volumes_matrix"] = [("0" if i == j else "280") for i in range(colours) for j in range(colours)]
                proj["flush_volumes_vector"] = ["140", "140"] * colours
                data = json.dumps(proj).encode()
            zout.writestr(info.filename, data)
    return out
