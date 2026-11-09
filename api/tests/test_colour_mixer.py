"""The Python colour mixer against the engine's own: api/tests/fixtures/colour_mixer_reference.json is what the real
FilamentMixerModel.hpp computes (scripts/mixer-reference.sh makes it), so every number here is the slicer's."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import colour_mixer

REFERENCE = json.loads((Path(__file__).parent / "fixtures" / "colour_mixer_reference.json").read_text())


def test_lerp_gives_what_the_engine_gives():
    # One test for the whole set: every test here pays for the suite's per-test reset of its stores.
    wrong = []
    for r1, g1, b1, r2, g2, b2, t, *expected in REFERENCE["lerp"]:
        got = colour_mixer.lerp((r1, g1, b1), (r2, g2, b2), t)
        if got != tuple(expected):
            wrong.append(((r1, g1, b1), (r2, g2, b2), t, tuple(expected), got))
    assert not wrong, f"{len(wrong)} of {len(REFERENCE['lerp'])} differ from the engine, first: {wrong[:3]}"


def test_blue_and_yellow_make_green():
    """The example in the model's own header."""
    assert colour_mixer.lerp((0, 33, 133), (252, 211, 0), 0.5) == (47, 141, 56)


def test_the_ends_of_the_range_are_the_colours_themselves():
    assert colour_mixer.lerp((10, 20, 30), (200, 100, 50), 0) == (10, 20, 30)
    assert colour_mixer.lerp((10, 20, 30), (200, 100, 50), 1) == (200, 100, 50)


def test_blend_gives_what_the_engine_gives():
    wrong = [
        (case, got)
        for case in REFERENCE["multi"]
        if (got := colour_mixer.blend(case["colours"], case["weights"])) != case["result"]
    ]
    assert not wrong, f"{len(wrong)} of {len(REFERENCE['multi'])} differ from the engine, first: {wrong[:3]}"


def test_blend_of_nothing_is_black_and_of_one_colour_is_that_colour():
    assert colour_mixer.blend([], []) == "#000000"
    assert colour_mixer.blend(["#12ab34"], [5]) == "#12AB34"


def test_blend_skips_zero_weights_and_reads_hex_in_any_case():
    assert colour_mixer.blend(["#ff0000", "#00ff00", "#0000ff"], [1, 0, 1]) == colour_mixer.blend(
        ["#FF0000", "#0000FF"], [1, 1]
    )


def test_a_hex_that_cannot_be_read_counts_as_grey_like_the_engine_does():
    assert colour_mixer.blend(["nonsense"], [1]) == "#808080"


def test_identical_colours_are_no_distance_apart_and_black_from_white_is_far():
    assert colour_mixer.distance("#336699", "#336699") == 0
    assert colour_mixer.distance("#000000", "#FFFFFF") == pytest.approx(100, abs=0.5)
    assert colour_mixer.distance("#336699", "#336688") < colour_mixer.distance("#336699", "#cc6699")


def test_distance_is_the_cie76_difference():
    """sRGB red and green are (53.24, 80.09, 67.20) and (87.73, -86.18, 83.18) in L*a*b*."""
    assert colour_mixer.distance("#FF0000", "#00FF00") == pytest.approx(170.56, abs=0.1)
