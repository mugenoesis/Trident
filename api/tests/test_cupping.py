"""Cupping: a cavity that no resin can flow into, which sucks on the film when a layer peels off it. Found in the layer images."""

from __future__ import annotations

import numpy as np

from app import cupping

SIZE = 30


def _disk() -> np.ndarray:
    return np.ones((SIZE, SIZE), dtype=bool)


def _ring(hole: int = 6, gap: bool = False) -> np.ndarray:
    layer = _disk()
    lo = (SIZE - hole) // 2
    layer[lo : lo + hole, lo : lo + hole] = False
    if gap:  # a channel from the cavity to the edge of the layer
        layer[lo : lo + hole, lo + hole :] = False
    return layer


def _worst(layers, min_area_mm2: float = 4.0):
    return cupping.find_worst_cup(layers, pixel_mm2=1.0, min_area_mm2=min_area_mm2)


def test_solid_layers_have_no_cup():
    assert _worst([_disk()] * 5) is None


def test_a_cavity_closed_at_the_plate_side_is_a_cup():
    cup = _worst([_disk(), _disk(), _ring(), _ring(), _ring()])
    assert cup is not None
    assert cup.layer == 2  # the first of the equally large layers
    assert cup.area_mm2 == 36.0


def test_the_largest_closed_area_is_the_worst():
    cup = _worst([_disk(), _ring(4), _ring(8), _ring(6)])
    assert cup is not None and (cup.layer, cup.area_mm2) == (2, 64.0)


def test_a_cavity_with_a_channel_to_the_edge_is_not_a_cup():
    assert _worst([_disk(), _disk(), _ring(gap=True), _ring(gap=True)]) is None


def test_a_cavity_closed_over_a_channel_stays_vented():
    # the channel is open in layer 2; the cavity is a closed ring again in layers 3 and 4 but resin still reaches it from below
    assert _worst([_disk(), _disk(), _ring(gap=True), _ring(), _ring()]) is None


def test_a_cavity_below_the_minimum_area_is_ignored():
    assert _worst([_disk(), _ring(2), _ring(2)], min_area_mm2=5.0) is None


def test_empty_space_around_the_part_is_never_a_cup():
    layer = np.zeros((SIZE, SIZE), dtype=bool)
    layer[5:25, 5:25] = True
    assert _worst([layer] * 3) is None


def test_the_pixel_size_scales_the_area():
    cup = cupping.find_worst_cup([_disk(), _ring(), _ring()], pixel_mm2=0.25, min_area_mm2=4.0)
    assert cup is not None and cup.area_mm2 == 9.0


def test_a_scan_with_no_layers_has_no_cup():
    assert _worst([]) is None
