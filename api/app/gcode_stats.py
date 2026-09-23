"""Extracts the total filament weight (grams) OrcaSlicer's own engine
already computes and writes into the sliced gcode's footer comments --
`result.json` (see cli_runner.py) never carries this, only prepare/export
timing and per-plate triangle counts, so it has to come from the gcode
text itself.

vendor/orcaslicer/src/libslic3r/GCode.cpp's
DoExport::update_print_stats_and_format_filament_stats() writes one
comma-separated `; filament used [g] = 12.34, 5.67` line (one value per
extruder, always present regardless of printer vendor) near the very end
of the file, followed by a `; total filament used [g] = ...` convenience
line -- but that second line is skipped for Bambu printers specifically
(`if (!is_bbl_printers)`), so summing the per-extruder line ourselves is
the one approach that works for every printer this app supports.
"""
from __future__ import annotations

import re
from pathlib import Path

# Generous for a footer block that's only a handful of short comment lines
# -- comfortably covers it without reading the whole (often multi-MB) file.
_TAIL_BYTES = 65536

_FILAMENT_USED_G_RE = re.compile(rb"^; filament used \[g\] = (.+)$", re.MULTILINE)


def _sum_grams_line(line: bytes) -> float | None:
    try:
        values = [float(v) for v in line.decode("ascii").split(",")]
    except ValueError:
        return None
    return sum(values)


def parse_total_filament_grams(gcode_path: Path) -> float | None:
    """None on any missing/malformed/truncated file -- best-effort, never
    raises, since a job that sliced successfully shouldn't be blocked or
    marked failed just because this one extra number couldn't be found."""
    try:
        with gcode_path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - _TAIL_BYTES))
            tail = f.read()
    except OSError:
        return None

    match = _FILAMENT_USED_G_RE.search(tail)
    if not match:
        return None
    return _sum_grams_line(match.group(1))


def total_filament_grams_for_job(output_dir: Path) -> float | None:
    """Sums across every gcode file in the job's output dir -- covers both
    a single-plate job and a "slice all plates" one (plate_index=None)
    the same way, since either way this is "how much filament this job's
    output will use" as a whole."""
    total = 0.0
    found_any = False
    for gcode_path in output_dir.glob("*.gcode"):
        grams = parse_total_filament_grams(gcode_path)
        if grams is not None:
            total += grams
            found_any = True
    return total if found_any else None
