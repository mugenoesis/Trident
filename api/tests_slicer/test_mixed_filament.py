"""A mixed (virtual) filament slot through the real slicer, set the way the app will set it: as setting overrides.

A mixed slot is not loaded in any nozzle; the slicer resolves it into its physical components, layer by layer (whole
layers, or sub-layers with `enable_mixed_color_sublayer`). These tests pin down what the engine does with the options on
its command line, since that is the only way the app talks to it. Each project has every object on the mixed slot, so
the G-code shows nothing but the mix.
"""

from __future__ import annotations

import re
import time
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.slicer

U1 = "Snapmaker U1 (0.4 nozzle)"
U1_PROCESS = "0.20 Standard @Snapmaker U1 (0.4 nozzle)"
U1_MATERIAL = "Snapmaker PLA Basic @U1"

TOOL_LINE = re.compile(r"^T(\d+)\s*(?:;.*)?$")


def mixed_overrides(components: str, ratios: str, slots: int, sublayer: bool = False) -> dict[str, str]:
    """Overrides that make the last of `slots` filament slots a mix of `components` (1-based, comma separated)."""
    others = slots - 1
    overrides = {
        "nozzle_diameter": ",".join(["0.4"] * 4),
        "nozzle_type": ",".join(["hardened_steel"] * 4),
        "enable_prime_tower": "1",
        "filament_is_mixed": ",".join(["0"] * others + ["1"]),
        "filament_mixed_components": ";".join(['""'] * others + [f'"{components}"']),
        "filament_mixed_sublayer_ratios": ";".join(['""'] * others + [f'"{ratios}"']),
    }
    if sublayer:
        overrides["enable_mixed_color_sublayer"] = "1"
    return overrides


def tools_per_layer(gcode: str) -> list[set[int]]:
    """The tools that print each layer: those selected on it, or else the one still loaded from the layer before."""
    layers: list[set[int]] = []
    carried: int | None = None
    for line in gcode.splitlines():
        if line.startswith(";LAYER_CHANGE"):
            layers.append(set())
            continue
        match = TOOL_LINE.match(line)
        if match and layers:
            layers[-1].add(int(match.group(1)))
        elif match:
            carried = int(match.group(1))
    for tools in layers:
        if tools:
            carried = max(tools)
        elif carried is not None:
            tools.add(carried)
    return layers


def share(layers: list[set[int]], tool: int) -> float:
    return sum(tool in tools for tools in layers) / len(layers)


def project_on_slot(source: Path, slot: int, dest: Path) -> Path:
    """A copy of a project with every object assigned to filament `slot`."""
    with zipfile.ZipFile(source) as zin, zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename.endswith("model_settings.config"):
                data = re.sub(r'(key="extruder" value=")\d+(")', rf"\g<1>{slot}\g<2>", data.decode()).encode()
            zout.writestr(info, data)
    return dest


@pytest.fixture
def slice_on_mix(client, projects, tmp_path):
    """slice_on_mix(slots, overrides) -> per-layer tool sets of a model printed on the last of `slots` slots."""

    def run(slots: int, overrides: dict[str, str], **job_fields) -> list[set[int]]:
        model = project_on_slot(projects(slots, style="objects"), slots, tmp_path / "on_mix.3mf")
        model_id = client.post("/models", files={"file": (model.name, model.read_bytes(), "model/3mf")}).json()[
            "model_id"
        ]
        job = client.post(
            "/jobs",
            json={
                "model_id": model_id,
                "printer_profile": U1,
                "process_profile": U1_PROCESS,
                "filament_profiles": [U1_MATERIAL] * (slots - len(job_fields.get("mixed_filaments", []))),
                "setting_overrides": overrides,
                **job_fields,
            },
        ).json()
        assert "id" in job, job
        deadline = time.time() + 300
        state: dict = {}
        while time.time() < deadline:
            state = client.get(f"/jobs/{job['id']}").json()
            if state["status"] in ("succeeded", "failed"):
                break
            time.sleep(0.5)
        assert state["status"] == "succeeded", state.get("error")
        return tools_per_layer(client.get(f"/jobs/{job['id']}/gcode").text)

    return run


def test_a_slot_that_is_not_mixed_prints_on_its_own_nozzle(slice_on_mix):
    """The control: with the flag off the same project prints on the third nozzle, so the tests below can tell."""
    overrides = {k: v for k, v in mixed_overrides("1,2", "0.5,0.5", slots=3).items() if "mixed" not in k}
    layers = slice_on_mix(3, overrides)
    assert all(tools == {2} for tools in layers)


def test_a_mixed_slot_prints_with_its_physical_components_only(slice_on_mix):
    layers = slice_on_mix(3, mixed_overrides("1,2", "0.5,0.5", slots=3))
    used = set().union(*layers)
    assert used == {0, 1}, f"expected nozzles 1 and 2 only, saw {sorted(used)}"


@pytest.mark.parametrize("ratios,first", [("0.5,0.5", 0.5), ("0.75,0.25", 0.75), ("0.8,0.2", 0.8)])
def test_the_ratio_sets_how_many_layers_each_component_prints(slice_on_mix, ratios, first):
    layers = slice_on_mix(3, mixed_overrides("1,2", ratios, slots=3))
    assert share(layers, 0) == pytest.approx(first, abs=0.04)
    assert share(layers, 1) == pytest.approx(1 - first, abs=0.04)


def test_three_components_share_the_layers(slice_on_mix):
    layers = slice_on_mix(4, mixed_overrides("1,2,3", "0.5,0.25,0.25", slots=4))
    assert set().union(*layers) == {0, 1, 2}
    assert share(layers, 0) == pytest.approx(0.5, abs=0.04)
    assert share(layers, 1) == pytest.approx(0.25, abs=0.04)


def test_sublayer_option_puts_every_component_on_each_layer(slice_on_mix):
    layers = slice_on_mix(3, mixed_overrides("1,2", "0.8,0.2", slots=3, sublayer=True))
    both = sum(tools == {0, 1} for tools in layers)
    assert both >= len(layers) - 3


def test_mix_options_without_a_mixed_slot_are_refused(slice_on_mix):
    """The engine rejects components and ratios when no slot is flagged, so the app sends them only with a mix."""
    overrides = mixed_overrides("1,2", "0.5,0.5", slots=3)
    overrides["filament_is_mixed"] = "0,0,0"
    with pytest.raises(AssertionError, match="filament_is_mixed: must be set"):
        slice_on_mix(3, overrides)


def test_a_mix_defined_through_the_job_prints_its_components_in_ratio(slice_on_mix):
    """The same as the options set by hand, asked for the way the app does it: three filaments and one mix of two."""
    layers = slice_on_mix(
        4,
        {"enable_prime_tower": "1"},
        mixed_filaments=[{"components": [1, 2], "weights": [3, 1]}],
    )
    assert set().union(*layers) == {0, 1}
    assert share(layers, 0) == pytest.approx(0.75, abs=0.04)


def test_a_mix_after_four_physical_filaments_on_a_four_nozzle_printer(slice_on_mix):
    """The fifth slot is not a nozzle: the mix prints on the nozzles that exist."""
    layers = slice_on_mix(
        5,
        {"enable_prime_tower": "1"},
        mixed_filaments=[{"components": [3, 4], "weights": [1, 1]}],
    )
    assert set().union(*layers) == {2, 3}


def test_a_mix_prints_without_a_prime_tower(slice_on_mix):
    """The web app leaves the prime tower to the user's own setting, so a mix has to slice with it off."""
    layers = slice_on_mix(5, {"enable_prime_tower": "0"}, mixed_filaments=[{"components": [3, 4], "weights": [1, 1]}])
    assert set().union(*layers) == {2, 3}


CUBE_STL = (
    "solid cube\n"
    + "".join(
        "facet normal 0 0 0\nouter loop\n" + "".join(f"vertex {x} {y} {z}\n" for x, y, z in tri) + "endloop\nendfacet\n"
        for tri in [
            ((0, 0, 0), (0, 20, 0), (20, 20, 0)),
            ((0, 0, 0), (20, 20, 0), (20, 0, 0)),
            ((0, 0, 20), (20, 0, 20), (20, 20, 20)),
            ((0, 0, 20), (20, 20, 20), (0, 20, 20)),
            ((0, 0, 0), (20, 0, 0), (20, 0, 20)),
            ((0, 0, 0), (20, 0, 20), (0, 0, 20)),
            ((20, 0, 0), (20, 20, 0), (20, 20, 20)),
            ((20, 0, 0), (20, 20, 20), (20, 0, 20)),
            ((20, 20, 0), (0, 20, 0), (0, 20, 20)),
            ((20, 20, 0), (0, 20, 20), (20, 20, 20)),
            ((0, 20, 0), (0, 0, 0), (0, 0, 20)),
            ((0, 20, 0), (0, 0, 20), (0, 20, 20)),
        ]
    )
    + "endsolid cube\n"
)


def test_a_mix_nobody_prints_with_changes_nothing_in_the_print(client):
    """The web app sends every mix it has; one that no part uses must leave the instructions to the printer as they were."""
    model_id = client.post("/models", files={"file": ("cube.stl", CUBE_STL.encode(), "model/stl")}).json()["model_id"]

    def run(**job_fields) -> str:
        job = client.post(
            "/jobs",
            json={
                "model_id": model_id,
                "printer_profile": U1,
                "process_profile": U1_PROCESS,
                "filament_profiles": [U1_MATERIAL] * 4,
                "setting_overrides": {"enable_prime_tower": "0"},
                **job_fields,
            },
        ).json()
        assert "id" in job, job
        deadline = time.time() + 300
        state: dict = {}
        while time.time() < deadline:
            state = client.get(f"/jobs/{job['id']}").json()
            if state["status"] in ("succeeded", "failed"):
                break
            time.sleep(0.5)
        assert state["status"] == "succeeded", state.get("error")
        return client.get(f"/jobs/{job['id']}/gcode").text

    def instructions(text: str) -> list[str]:
        return [line for line in text.splitlines() if not line.startswith(";")]

    plain = run()
    with_mix = run(mixed_filaments=[{"components": [3, 4], "weights": [1, 1]}])
    assert instructions(with_mix) == instructions(plain)
