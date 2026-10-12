"""Where does a belt print start, relative to the purge line?

A belt printer's start gcode primes the nozzle in a line near the belt origin,
and the print should begin right at that line so the first material picks up
the purge. The model is placed by its own outline, but support (and brim) can
reach further toward the origin than the model does, so the real start of the
print is only known after slicing. This reads a sliced gcode, finds both, and
says how far the print must move along the belt to touch the purge line.

The gcode of a belt printer is not plain Cartesian; the profile's remap and
shear are undone first (a port of web/src/beltTransform.ts, itself a port of
OrcaSlicer's own BeltBackTransform).
"""

from __future__ import annotations

import contextlib
import math
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Feature types that are not "the print": the start-gcode purge itself and the
# multi-material wipe tower, which sits elsewhere on the bed.
_NOT_PRINT_TYPES = {"Custom", "Prime tower", "Wipe tower"}

_REMAP_BY_STRING = {
    "pos_x": 0,
    "pos_y": 1,
    "pos_z": 2,
    "neg_x": 3,
    "neg_y": 4,
    "neg_z": 5,
    "rev_x": 6,
    "rev_y": 7,
    "rev_z": 8,
}


@dataclass
class BeltTransform:
    rotation_axis: str  # "x" | "y"
    angle_deg: float
    remap_codes: tuple[int, int, int]  # one per gcode letter, in X, Y, Z order
    bounds_max: tuple[float, float, float]


def parse_belt_transform(data: dict[str, Any], bounds_max: tuple[float, float, float]) -> BeltTransform | None:
    """Same gates as the browser's parseBeltTransform; None for a printer
    without a machine-frame tilt (its gcode is plain Cartesian)."""
    if data.get("belt_printer") not in ("1", 1, True):
        return None
    axis = str(data.get("belt_slice_rotation", "")).lower()
    if axis not in ("x", "y"):
        return None
    decouple = data.get("belt_frame_tilt_decouple") in ("1", 1, True)
    try:
        angle = float(data.get("belt_frame_tilt_angle", 0) if decouple else data.get("belt_slice_rotation_angle", 0))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(angle) or abs(angle) < 1e-6:
        return None
    codes = tuple(_REMAP_BY_STRING.get(str(data.get(f"gcode_remap_{a}", "")), 0) for a in "xyz")
    return BeltTransform(axis, angle, codes, bounds_max)  # type: ignore[arg-type]


def back_transform(t: BeltTransform, gx: float, gy: float, gz: float) -> tuple[float, float, float]:
    rad = math.radians(t.angle_deg)
    sin_a, cos_a = math.sin(rad), math.cos(rad)
    pre = (gx, gy, gz)
    if abs(sin_a) > 1e-9:
        pre = (gx, gy * sin_a, gz - gy * cos_a) if t.rotation_axis == "x" else (gx * sin_a, gy, gz + gx * cos_a)
    upright = [0.0, 0.0, 0.0]
    for letter in range(3):
        code = t.remap_codes[letter]
        axis = code % 3
        value = pre[letter]
        upright[axis] = value if code < 3 else (-value if code < 6 else t.bounds_max[axis] - value)
    return upright[0], upright[1], upright[2]


@dataclass
class StartMeasure:
    purge_y: float  # belt-travel position (upright Y) of the purge line
    start_y: float  # lowest belt-travel position of any printed material

    @property
    def shift_needed(self) -> float:
        """How far to move the print along the belt (mm, + = away from the
        origin) so its start touches the purge line."""
        return self.purge_y - self.start_y


def _args(parts: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for p in parts[1:]:
        if p and p[0].isalpha():
            with contextlib.suppress(ValueError):
                out[p[0].upper()] = float(p[1:])
    return out


@dataclass
class _Head:
    """Where the print head is, as the file's own coordinates and the offset G92 has added to them."""

    pos: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    offset: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    e: float = 0.0
    relative_e: bool = False

    def reset(self, a: dict[str, float]) -> None:
        """G92: the head stays put but is now called something else."""
        if "E" in a:
            self.e = a["E"]
        for i, axis in enumerate("XYZ"):
            if axis in a:
                self.offset[i] += self.pos[i] - a[axis]
                self.pos[i] = a[axis]

    def move(self, a: dict[str, float]) -> tuple[bool, tuple[float, float, float]]:
        """G0/G1: (whether it extruded while moving, where it went in the machine's own coordinates)."""
        target = [a.get(axis, self.pos[i]) for i, axis in enumerate("XYZ")]
        delta = 0.0
        if "E" in a:
            delta = a["E"] if self.relative_e else a["E"] - self.e
            self.e = self.e + delta if self.relative_e else a["E"]
        extruded = delta > 0 and target != self.pos
        self.pos = target
        x, y, z = (target[i] + self.offset[i] for i in range(3))
        return extruded, (x, y, z)


def _commands(fh: Iterable[str]) -> Iterator[tuple[str, list[str]]]:
    """(the current ;TYPE: of the file, the words of each command line); comments and blank lines are skipped."""
    kind = ""
    for raw in fh:
        line = raw.strip()
        if not line:
            continue
        if line[0] == ";":
            if line.startswith(";TYPE:"):
                kind = line[6:].strip()
            continue
        parts = line.split(";", 1)[0].split()
        if parts:
            yield kind, parts


def measure_start(gcode: Path, t: BeltTransform) -> StartMeasure | None:
    """None if the file has no purge line or no printed material to compare."""
    head = _Head()
    purge: list[float] = []
    start = math.inf
    with gcode.open("r", errors="replace") as fh:
        for kind, parts in _commands(fh):
            cmd = parts[0].upper()
            if cmd in ("M83", "M82"):
                head.relative_e = cmd == "M83"
            elif cmd == "G92":
                head.reset(_args(parts))
            elif cmd in ("G0", "G1"):
                extruded, (x, y, z) = head.move(_args(parts))
                if not extruded:
                    continue
                belt_y = back_transform(t, x, y, z)[1]
                if kind == "Custom":
                    purge.append(belt_y)
                elif kind not in _NOT_PRINT_TYPES:
                    start = min(start, belt_y)
    if not purge or start is math.inf:
        return None
    return StartMeasure(purge_y=sum(purge) / len(purge), start_y=start)
