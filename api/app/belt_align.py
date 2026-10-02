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

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Feature types that are not "the print": the start-gcode purge itself and the
# multi-material wipe tower, which sits elsewhere on the bed.
_NOT_PRINT_TYPES = {"Custom", "Prime tower", "Wipe tower"}

_REMAP_BY_STRING = {
    "pos_x": 0, "pos_y": 1, "pos_z": 2,
    "neg_x": 3, "neg_y": 4, "neg_z": 5,
    "rev_x": 6, "rev_y": 7, "rev_z": 8,
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
            try:
                out[p[0].upper()] = float(p[1:])
            except ValueError:
                pass
    return out


def measure_start(gcode: Path, t: BeltTransform) -> StartMeasure | None:
    """None if the file has no purge line or no printed material to compare."""
    x = y = z = e = 0.0
    xo = yo = zo = 0.0
    relative_e = False
    kind = ""
    purge: list[float] = []
    start = math.inf
    with gcode.open("r", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            if line[0] == ";":
                if line.startswith(";TYPE:"):
                    kind = line[6:].strip()
                continue
            line = line.split(";", 1)[0].strip()
            parts = line.split()
            cmd = parts[0].upper() if parts else ""
            if cmd == "M83":
                relative_e = True
            elif cmd == "M82":
                relative_e = False
            elif cmd == "G92":
                a = _args(parts)
                if "E" in a:
                    e = a["E"]
                if "X" in a:
                    xo += x - a["X"]
                    x = a["X"]
                if "Y" in a:
                    yo += y - a["Y"]
                    y = a["Y"]
                if "Z" in a:
                    zo += z - a["Z"]
                    z = a["Z"]
            elif cmd in ("G0", "G1"):
                a = _args(parts)
                nx, ny, nz = a.get("X", x), a.get("Y", y), a.get("Z", z)
                if "E" in a:
                    delta = a["E"] if relative_e else a["E"] - e
                    e = e + delta if relative_e else a["E"]
                else:
                    delta = 0.0
                if delta > 0 and (nx, ny, nz) != (x, y, z):
                    belt_y = back_transform(t, nx + xo, ny + yo, nz + zo)[1]
                    if kind == "Custom":
                        purge.append(belt_y)
                    elif kind not in _NOT_PRINT_TYPES:
                        start = min(start, belt_y)
                x, y, z = nx, ny, nz
    if not purge or start is math.inf:
        return None
    return StartMeasure(purge_y=sum(purge) / len(purge), start_y=start)
