"""Mixed filaments: a slot that is a mix of two or three physical filaments, turned into the options the slicer takes."""

from __future__ import annotations

import io

import pytest

from app import cli_runner, mixed_filaments
from app.cli_runner import SliceResult
from app.mixed_filaments import MixedFilament

THREE = ["PLA red", "PLA blue", "PLA yellow"]


def test_a_mix_adds_a_slot_after_the_physical_ones():
    profiles, overrides = mixed_filaments.expand(THREE, [MixedFilament(components=[1, 2], weights=[3, 1])])
    # the mixed slot is sliced with its first component's material
    assert profiles == [*THREE, "PLA red"]
    assert overrides["filament_is_mixed"] == "0,0,0,1"
    assert overrides["filament_mixed_components"] == '"";"";"";"1,2"'
    assert overrides["filament_mixed_sublayer_ratios"] == '"";"";"";"0.7500,0.2500"'
    assert "enable_mixed_color_sublayer" not in overrides


def test_several_mixes_follow_one_another_and_three_components_are_allowed():
    mixes = [
        MixedFilament(components=[1, 2], weights=[1, 1]),
        MixedFilament(components=[1, 2, 3], weights=[2, 1, 1]),
    ]
    profiles, overrides = mixed_filaments.expand(THREE, mixes, sublayers=True)
    assert profiles == [*THREE, "PLA red", "PLA red"]
    assert overrides["filament_is_mixed"] == "0,0,0,1,1"
    assert overrides["filament_mixed_components"] == '"";"";"";"1,2";"1,2,3"'
    assert overrides["filament_mixed_sublayer_ratios"].endswith('"0.5000,0.5000";"0.5000,0.2500,0.2500"')
    assert overrides["enable_mixed_color_sublayer"] == "1"


def test_no_mix_leaves_the_job_as_it_was():
    """The engine refuses mix options when no slot is mixed, so none may be sent."""
    assert mixed_filaments.expand(THREE, []) == (THREE, {})


@pytest.mark.parametrize(
    "mix,problem",
    [
        (MixedFilament(components=[1], weights=[1]), "2 or 3"),
        (MixedFilament(components=[1, 2, 3, 4], weights=[1, 1, 1, 1]), "2 or 3"),
        (MixedFilament(components=[1, 1], weights=[1, 1]), "twice"),
        (MixedFilament(components=[1, 4], weights=[1, 1]), "physical"),
        (MixedFilament(components=[0, 1], weights=[1, 1]), "physical"),
        (MixedFilament(components=[1, 2], weights=[1]), "one weight"),
        (MixedFilament(components=[1, 2], weights=[1, 0]), "positive"),
    ],
)
def test_a_mix_the_slicer_would_refuse_is_refused_first(mix, problem):
    with pytest.raises(ValueError, match=problem):
        mixed_filaments.expand(THREE, [mix])


def test_ratios_are_written_as_the_engine_writes_them():
    assert mixed_filaments.ratio_text([1, 1, 1]) == "0.3333,0.3333,0.3333"
    assert mixed_filaments.ratio_text([75, 25]) == "0.7500,0.2500"
    assert mixed_filaments.ratio_text([0.2, 0.8]) == "0.2000,0.8000"


def test_a_mix_previews_as_the_blend_of_its_components():
    colours = ["#FF0000", "#002185", "#FCD300"]
    mix = MixedFilament(components=[2, 3], weights=[1, 1])
    assert mixed_filaments.preview(colours, mix) == "#2F8D38"  # blue and yellow: the green the model's header gives


def _upload(client) -> str:
    return client.post("/models", files={"file": ("cube.stl", io.BytesIO(b"fake stl bytes"), "model/stl")}).json()[
        "model_id"
    ]


def _job(model_id: str, **extra) -> dict:
    return {
        "model_id": model_id,
        "printer_profile": "Generic Printer",
        "process_profile": "0.20mm Standard",
        "filament_profiles": THREE,
        **extra,
    }


def test_a_job_with_a_mix_slices_with_the_mix_options(client, monkeypatch):
    captured: dict = {}

    def fake_run_slice(**kwargs):
        captured.update(kwargs)
        return SliceResult(
            return_code=0,
            result_json={"return_code": 0, "error_string": ""},
            stdout="",
            stderr="",
            used_result_json=True,
        )

    monkeypatch.setattr(cli_runner, "run_slice", fake_run_slice)
    body = _job(
        _upload(client),
        mixed_filaments=[{"components": [1, 2], "weights": [3, 1]}],
        mixed_sublayers=True,
        setting_overrides={"layer_height": 0.2},
    )
    job = client.post("/jobs", json=body)
    assert job.status_code == 200
    assert captured["filament_profiles"] == [*THREE, "PLA red"]
    assert captured["setting_overrides"]["layer_height"] == 0.2
    assert captured["setting_overrides"]["filament_is_mixed"] == "0,0,0,1"
    assert captured["setting_overrides"]["enable_mixed_color_sublayer"] == "1"
    # the job record shows what was sliced, so a mix can be read back out of it
    assert job.json()["setting_overrides"]["filament_mixed_components"] == '"";"";"";"1,2"'
    assert job.json()["filament_profiles"] == [*THREE, "PLA red"]


def test_a_job_with_a_bad_mix_is_refused(client):
    resp = client.post("/jobs", json=_job(_upload(client), mixed_filaments=[{"components": [1, 9], "weights": [1, 1]}]))
    assert resp.status_code == 400
    assert "physical" in resp.json()["detail"]


def test_a_mix_cannot_be_combined_with_hand_set_mix_options(client):
    resp = client.post(
        "/jobs",
        json=_job(
            _upload(client),
            mixed_filaments=[{"components": [1, 2], "weights": [1, 1]}],
            setting_overrides={"filament_is_mixed": "0,0,0,1"},
        ),
    )
    assert resp.status_code == 400
    assert "filament_is_mixed" in resp.json()["detail"]


def test_a_mix_is_not_for_a_resin_job(client):
    resp = client.post(
        "/jobs",
        json=_job(_upload(client), technology="resin", mixed_filaments=[{"components": [1, 2], "weights": [1, 1]}]),
    )
    assert resp.status_code == 400


PHYSICAL = ["#FF0000", "#002185", "#FCD300", "#FFFFFF"]


def test_the_best_suggestion_for_a_colour_that_is_a_mix_is_that_mix():
    target = mixed_filaments.preview(PHYSICAL, MixedFilament(components=[2, 3], weights=[7, 3]))
    best = mixed_filaments.suggest(PHYSICAL, target)[0]
    assert best.mix.components == [2, 3]
    assert [round(w) for w in best.mix.weights] == [7, 3]
    assert best.colour == target
    assert best.distance == 0


def test_suggestions_are_ordered_by_how_close_they_are_and_limited():
    found = mixed_filaments.suggest(PHYSICAL, "#4A9A40", count=5)
    assert len(found) == 5
    assert [s.distance for s in found] == sorted(s.distance for s in found)
    assert found[0].distance < 10


def test_suggestions_can_be_limited_to_two_components_and_never_repeat_a_filament():
    found = mixed_filaments.suggest(PHYSICAL, "#808080", count=200, max_components=2)
    assert {len(s.mix.components) for s in found} == {2}
    assert all(len(set(s.mix.components)) == len(s.mix.components) for s in found)


def test_with_one_physical_filament_there_is_nothing_to_mix():
    assert mixed_filaments.suggest(["#FF0000"], "#808080") == []


def test_the_preview_and_suggest_routes(client):
    body = {"colours": PHYSICAL, "mixes": [{"components": [2, 3], "weights": [1, 1]}]}
    resp = client.post("/mixes/preview", json=body)
    assert resp.status_code == 200
    assert resp.json() == {"colours": ["#2F8D38"]}

    resp = client.post("/mixes/suggest", json={"colours": PHYSICAL, "target": "#2F8D38", "count": 3})
    assert resp.status_code == 200
    first = resp.json()["suggestions"][0]
    assert first["components"] == [2, 3] and first["colour"] == "#2F8D38" and first["distance"] == 0


def test_the_routes_refuse_what_they_cannot_read(client):
    bad_mix = {"colours": PHYSICAL, "mixes": [{"components": [2, 9], "weights": [1, 1]}]}
    assert client.post("/mixes/preview", json=bad_mix).status_code == 400
    bad_colour = {"colours": PHYSICAL, "target": "green"}
    assert client.post("/mixes/suggest", json=bad_colour).status_code == 400
    assert client.post("/mixes/preview", json={"colours": ["nonsense"], "mixes": []}).status_code == 400
