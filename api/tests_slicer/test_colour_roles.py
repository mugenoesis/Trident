"""The app finds the right number of colours in each kind of project, since that is how many filaments it sends."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.slicer


@pytest.mark.parametrize("style", ["painted", "objects"])
@pytest.mark.parametrize("colours", [1, 2, 3, 4, 5, 6])
def test_the_colours_of_a_project_are_found(client, projects, colours, style):
    path = projects(colours, style=style)
    model_id = client.post("/models", files={"file": (path.name, path.read_bytes(), "model/3mf")}).json()["model_id"]
    info = client.get(f"/models/{model_id}/plates").json()
    # one colour per filament of the file: the app sends one filament profile for each
    assert len(info["embedded_filament_colors"]) == colours
    if style == "objects":
        assert sorted(info["extruder_indices"]) == list(range(1, colours + 1))
        assert len(info["objects"]) == colours
    else:
        assert len(info["objects"]) == 1
