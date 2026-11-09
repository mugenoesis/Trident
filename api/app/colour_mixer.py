"""Pigment-style colour mixing, for previewing a mixed filament: what two or three filaments printed in thin alternating
layers look like together.

A port of the engine's FilamentMixer (vendor/orcaslicer/src/libslic3r/FilamentMixerModel.hpp and `blend_color_multi`
in FilamentMixer.cpp): a degree-4 polynomial of the two colours and the mixing ratio, fitted to approximate Mixbox.
The numbers are in mixer_model/filament_mixer_model.json, which scripts/mixer-reference.sh reads out of the engine's header,
and tests/test_colour_mixer.py checks this module against what that header computes.

The engine also looks a blend up in a table of measured recipes first; this module does not carry that table, so the
colour here is the polynomial's estimate, which the engine's own preview may differ from for the filaments it measured.

The polynomial model is MIT licensed:

    Copyright (c) 2026 Justin Hayes

    Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
    documentation files (the "Software"), to deal in the Software without restriction, including without limitation
    the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
    permit persons to whom the Software is furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all copies or substantial portions of
    the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
    THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
    TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path

import numpy as np

Rgb = tuple[int, int, int]

_MODEL_FILE = Path(__file__).parent / "mixer_model" / "filament_mixer_model.json"
_GREY = (128, 128, 128)  # what the engine reads an unparseable colour as
_HEX = re.compile(r"#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})")


@cache
def _model() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    data = json.loads(_MODEL_FILE.read_text())
    return np.array(data["powers"], dtype=np.intp), np.array(data["coef"]), np.array(data["intercept"])


def lerp(first: Rgb, second: Rgb, t: float) -> Rgb:
    """Mix two colours: `t` 0 is all `first`, 1 is all `second`. As the engine's `filament_mixer::lerp`."""
    if t <= 0:
        return first
    if t >= 1:
        return second
    powers, coef, intercept = _model()
    # The engine takes t as a 32-bit float; it and the products below are built the engine's way so they round the same.
    x = [float(v) for v in (*first, *second)] + [float(np.float32(t))]
    table = np.ones((5, 7))
    for exponent in range(1, 5):
        table[exponent] = table[exponent - 1] * x
    features = np.ones(len(powers))
    for j in range(7):
        features = features * table[powers[:, j], j]
    # Summed one term after another, like the engine's loop, since the order changes the last bits and the result is truncated.
    sums = np.cumsum(np.vstack([intercept, features[:, None] * coef]), axis=0)[-1]
    red, green, blue = (min(255, max(0, int(v))) for v in sums)
    return red, green, blue


def parse_hex(text: str) -> Rgb:
    match = _HEX.fullmatch(text.strip())
    if not match:
        return _GREY
    red, green, blue = (int(group, 16) for group in match.groups())
    return red, green, blue


def to_hex(colour: Rgb) -> str:
    return "#{:02X}{:02X}{:02X}".format(*colour)


def blend(colours: list[str], weights: list[int]) -> str:
    """The colour of `colours` (`#RRGGBB`) mixed in the proportions `weights`, as the engine's `blend_color_multi`
    without its measured-recipe lookup: the colours are folded in one at a time, each by its share of the total so far.
    A weight of zero or less leaves its colour out."""
    mixed: Rgb | None = None
    total = 0
    for colour, weight in zip(colours, weights, strict=True):
        if weight <= 0:
            continue
        rgb = parse_hex(colour)
        if mixed is None:
            mixed, total = rgb, weight
        else:
            total += weight
            mixed = lerp(mixed, rgb, float(np.float32(weight) / np.float32(total)))
    return "#000000" if mixed is None else to_hex(mixed)


def is_hex(text: str) -> bool:
    """Whether `text` is a `#RRGGBB` colour (`parse_hex` reads anything else as grey, as the engine does)."""
    return _HEX.fullmatch(text.strip()) is not None


def _to_lab(colour: Rgb) -> tuple[float, float, float]:
    """CIE L*a*b* (D65) of an sRGB colour."""
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (v / 255 for v in colour)]
    red, green, blue = linear
    xyz = (
        (0.4124564 * red + 0.3575761 * green + 0.1804375 * blue) / 0.95047,
        0.2126729 * red + 0.7151522 * green + 0.0721750 * blue,
        (0.0193339 * red + 0.1191920 * green + 0.9503041 * blue) / 1.08883,
    )
    x, y, z = (v ** (1 / 3) if v > 216 / 24389 else (24389 / 27 * v + 16) / 116 for v in xyz)
    return 116 * y - 16, 500 * (x - y), 200 * (y - z)


def distance(first: str, second: str) -> float:
    """How far apart two `#RRGGBB` colours look: the CIE76 colour difference (about 2 is just noticeable, 100 is black to white)."""
    return float(np.linalg.norm(np.subtract(_to_lab(parse_hex(first)), _to_lab(parse_hex(second)))))
