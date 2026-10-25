"""Cupping: a closed cavity in a resin print, which seals against the film and sucks on it when a layer peels off.

Layers are boolean images (True = cured resin) in the order they are printed, the first against the build plate. Empty space
that reaches the edge of a layer is open resin. A hole inside a layer is a cavity; it is vented when the layer before it had open
resin (or a vented cavity) at the same place, because resin can then flow in from there. Anything else is closed. Only closed
cavities of a certain size count: a small one does not pull on the film.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

# Rule of thumb of this app, not a figure from any resin or printer maker: a closed cavity under 25 mm2 (5 mm across) pulls too
# little to matter.
CUP_MIN_AREA_MM2 = 25.0


@dataclass(frozen=True)
class Cup:
    """The layer (from 0) with the largest closed cavity, and the area of that cavity in mm2."""

    layer: int
    area_mm2: float


def _closed_cavities(cured: np.ndarray, open_before: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(open resin, closed cavities) of one layer, as masks, given the open resin of the layer before it."""
    labels = np.zeros(cured.shape, dtype=np.int32)
    ndimage.label(~cured, output=labels)
    edge = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    reached = np.unique(labels[open_before & ~cured])
    open_labels = np.union1d(edge, reached)
    open_labels = open_labels[open_labels > 0]
    open_mask = np.isin(labels, open_labels)
    return open_mask, ~cured & ~open_mask


def find_worst_cup(
    layers: Iterable[np.ndarray], pixel_mm2: float, min_area_mm2: float = CUP_MIN_AREA_MM2
) -> Cup | None:
    """The layer with the largest closed cavity (the first of equals), or None when no cavity is closed and big enough."""
    worst: Cup | None = None
    open_before: np.ndarray | None = None
    for index, cured in enumerate(layers):
        if open_before is None or open_before.shape != cured.shape:
            open_before = np.zeros(cured.shape, dtype=bool)
        open_before, closed = _closed_cavities(cured, open_before)
        area = float(closed.sum()) * pixel_mm2
        if area >= min_area_mm2 and (worst is None or area > worst.area_mm2):
            worst = Cup(layer=index, area_mm2=area)
    return worst
