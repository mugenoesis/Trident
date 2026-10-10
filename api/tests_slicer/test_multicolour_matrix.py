"""Multi-colour 3MF projects through the real slicer, over colour counts, printers and nozzle assignments.

Each project is a cube painted in N colours and saved by the slicer for another printer, the way a downloaded
multi-colour model arrives. A job is started the way the app starts one: one filament profile per colour in the
file, and a remap from each colour to the nozzle the user chose. Every case must slice and write G-code.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.slicer

PRINTERS = {
    "U1 (4 nozzles)": dict(printer="Snapmaker U1 (0.4 nozzle)", process="0.20 Standard @Snapmaker U1 (0.4 nozzle)", material="Snapmaker PLA Basic @U1", nozzles=4),
    "Ender-3 (1 nozzle)": dict(printer="Creality Ender-3 0.4 nozzle", process="0.20mm Standard @Creality Ender3", material="CR-PLA @Ender-3-all", nozzles=1),
    "IR3 V2 (belt)": dict(printer="IdeaFormer IR3 V2 0.4 nozzle", process=None, material="Generic PLA @IdeaFormer IR3 V2", nozzles=1),
}


def default_remap(colours: int, nozzles: int) -> str:
    """Colours in order onto the nozzles; colours beyond the last nozzle share it."""
    return ",".join(f"{c}:{min(c, nozzles)}" for c in range(1, colours + 1) if c != min(c, nozzles))


def assert_slices(result, case: str):
    status, error, wrote_gcode = result
    assert status == "succeeded" and wrote_gcode, f"{case}: {status} {error}"


@pytest.mark.parametrize("colours", [1, 2, 3, 4, 5, 6])
@pytest.mark.parametrize("printer", list(PRINTERS))
def test_colours_in_order_onto_the_nozzles(projects, slice_project, printer, colours):
    """Up to six colours on one, a few or four nozzles; extra colours share the last nozzle."""
    p = PRINTERS[printer]
    result = slice_project(
        projects(colours), printer=p["printer"], process=p["process"], material=p["material"],
        profiles_count=colours, nozzles=p["nozzles"], remap=default_remap(colours, p["nozzles"]), colours=colours,
    )
    assert_slices(result, f"{colours} colours on {printer}")


@pytest.mark.parametrize(
    "colours,remap",
    [
        (2, "1:2,2:1"),  # swapped
        (2, "1:4,2:3"),  # the last two nozzles
        (3, "1:4,2:3,3:1"),  # the case that crashed the slicer in 0.4.0
        (3, "1:2,2:3,3:4"),  # shifted along
        (4, "1:4,2:3,3:2,4:1"),  # reversed
        (4, "1:1,2:1,3:2,4:2"),  # two colours on one nozzle
        (5, "1:4,2:3,3:2,4:1,5:1"),  # more colours than nozzles, reversed
        (6, "1:1,2:1,3:1,4:1,5:1,6:1"),  # everything on one nozzle
    ],
)
def test_colours_assigned_to_chosen_nozzles_on_the_u1(projects, slice_project, colours, remap):
    p = PRINTERS["U1 (4 nozzles)"]
    result = slice_project(
        projects(colours), printer=p["printer"], process=p["process"], material=p["material"],
        profiles_count=colours, nozzles=4, remap=remap, colours=colours,
    )
    assert_slices(result, f"{colours} colours, remap {remap}")


@pytest.mark.parametrize("colours", [2, 3])
def test_a_project_with_fewer_colours_than_nozzles_given_a_profile_per_nozzle(projects, slice_project, colours):
    """Four filament profiles for a file of two or three colours (the settings sized for fewer filaments are
    trimmed, and a slicer crash on the trimmed copy is retried with the project's own)."""
    p = PRINTERS["U1 (4 nozzles)"]
    result = slice_project(
        projects(colours), printer=p["printer"], process=p["process"], material=p["material"],
        profiles_count=4, nozzles=4, remap=default_remap(colours, 4), colours=colours,
    )
    assert_slices(result, f"{colours} colours with 4 profiles")


@pytest.mark.parametrize("colours", [2, 3, 4])
def test_a_project_saved_on_the_u1_itself(projects, slice_project, colours):
    p = PRINTERS["U1 (4 nozzles)"]
    result = slice_project(
        projects(colours, "u1"), printer=p["printer"], process=p["process"], material=p["material"],
        profiles_count=colours, nozzles=4, remap=default_remap(colours, 4), colours=colours,
    )
    assert_slices(result, f"{colours} colours saved on the U1")


@pytest.mark.xfail(
    strict=True,
    reason="The slicer corrupts its heap when given four filaments for a one-colour file. The app sends one filament "
    "per colour in the file, so it does not happen there; if this starts passing the slicer was fixed.",
)
def test_a_one_colour_file_given_four_profiles(projects, slice_project):
    p = PRINTERS["U1 (4 nozzles)"]
    result = slice_project(
        projects(1), printer=p["printer"], process=p["process"], material=p["material"], profiles_count=4, nozzles=4, colours=1
    )
    assert_slices(result, "1 colour with 4 profiles")
