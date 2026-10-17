"""Resin printers made by the user: a printer that is not in the catalogue, from its screen and file format, or copied from one that is."""

from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pytest
from resin_support import FAKE_BIN, build_resin_dir

from app import resin as resin_module
from app.config import settings
from app.resin import ResinCatalog
from app.resin_printers_user import UserResinPrinters


@pytest.fixture(autouse=True)
def setup(tmp_path: Path, monkeypatch):
    catalog = ResinCatalog(build_resin_dir(tmp_path / "resin"))
    catalog.load()
    monkeypatch.setattr(resin_module, "catalog", catalog)
    monkeypatch.setattr(settings, "models_dir", tmp_path / "models")
    monkeypatch.setattr(settings, "orcaslicer_bin", str(FAKE_BIN))


def _printer(**overrides):
    body = {
        "name": "My Saturn",
        "display_width_mm": 218.88,
        "display_height_mm": 122.88,
        "pixels_x": 7680,
        "pixels_y": 4320,
        "build_height_mm": 250,
        "format": "CTBENCRYPTED",
    }
    body.update(overrides)
    return body


def _mine(client, name="My Saturn"):
    return next((p for p in client.get("/resin/printers").json() if p["name"] == name), None)


def test_a_printer_made_from_its_screen_is_listed_with_the_others(client):
    resp = client.post("/resin/my-printers", json=_printer())
    assert resp.status_code == 200, resp.text
    mine = _mine(client)
    assert mine["vendor"] == "My printers"
    assert mine["supported"] is True
    assert mine["extension"] == "ctb"
    assert (mine["pixels_x"], mine["pixels_y"]) == (7680, 4320)
    assert mine["build_height_mm"] == 250
    assert mine["pixel_size_mm"] == pytest.approx(0.0285, abs=1e-4)
    assert _mine(client, "Elegoo Mars 3") is not None


def test_a_printer_copied_from_the_catalogue_keeps_what_the_form_does_not_ask(client):
    client.post("/resin/my-printers", json=_printer(copy_from="Elegoo Mars 3", pixels_x=4000, pixels_y=2250))
    preset = resin_module.catalog.printer_preset("My Saturn", _user(client))
    assert preset["display_mirror_x"] == "1"  # the Mars 3's mirroring
    assert preset["display_pixels_x"] == "4000"  # what the form gave wins
    assert preset["name"] == "My Saturn"
    assert preset["printer_settings_id"] == "My Saturn"
    assert preset["printer_technology"] == "SLA"
    assert preset["sla_archive_format"] == "CTBENCRYPTED"


def test_mirroring_can_be_set_for_a_printer_made_from_nothing(client):
    client.post("/resin/my-printers", json=_printer(mirror_x=True, mirror_y=False))
    preset = resin_module.catalog.printer_preset("My Saturn", _user(client))
    assert (preset["display_mirror_x"], preset["display_mirror_y"]) == ("1", "0")


def test_the_formats_that_can_be_written_are_offered_with_their_file_ending(client):
    formats = {f["id"]: f for f in client.get("/resin/formats").json()}
    assert formats["CTBENCRYPTED"]["extension"] == "ctb"
    assert "Chitubox" in formats["CTBENCRYPTED"]["label"]
    assert "lgs" not in formats  # the catalogue has a printer of that format, but nothing writes it


@pytest.mark.parametrize(
    ("overrides", "status", "message"),
    [
        ({"name": "Elegoo Mars 3"}, 409, "already"),
        ({"format": "lgs"}, 400, "cannot write"),
        ({"format": "nothing"}, 400, "cannot write"),
        ({"pixels_y": 3000}, 400, "pixel"),  # 0.0285 x 0.0410 mm pixels: the numbers do not fit one screen
        ({"pixels_x": 100, "pixels_y": 60}, 400, "pixel"),  # 2.2 mm pixels
        ({"copy_from": "Nobody"}, 400, "Unknown resin printer"),
        ({"name": ""}, 422, ""),
        ({"pixels_x": -4}, 422, ""),
        ({"display_width_mm": 0}, 422, ""),
        ({"build_height_mm": 0}, 422, ""),
    ],
)
def test_a_printer_whose_numbers_do_not_make_sense_is_refused(client, overrides, status, message):
    resp = client.post("/resin/my-printers", json=_printer(**overrides))
    assert resp.status_code == status
    if message:
        assert message in resp.json()["detail"]


def test_rectangular_pixels_are_accepted_when_said_to_be(client):
    assert client.post("/resin/my-printers", json=_printer(pixels_y=3000)).status_code == 400
    assert client.post("/resin/my-printers", json=_printer(pixels_y=3000, rectangular_pixels=True)).status_code == 200


def test_a_name_of_mine_cannot_be_used_twice(client):
    client.post("/resin/my-printers", json=_printer())
    assert client.post("/resin/my-printers", json=_printer()).status_code == 409


def test_a_printer_of_mine_can_be_read_back_changed_and_deleted(client):
    client.post("/resin/my-printers", json=_printer(copy_from="Elegoo Mars 3"))
    form = client.get("/resin/my-printers/My Saturn").json()
    assert form["pixels_x"] == 7680
    assert form["copy_from"] == "Elegoo Mars 3"
    changed = client.put(
        "/resin/my-printers/My Saturn",
        json=_printer(pixels_x=3840, pixels_y=2160, display_width_mm=218.88, display_height_mm=123.12),
    )
    assert changed.status_code == 200, changed.text
    assert _mine(client)["pixels_x"] == 3840
    assert client.delete("/resin/my-printers/My Saturn").status_code == 200
    assert _mine(client) is None
    assert client.get("/resin/my-printers/My Saturn").status_code == 404
    assert client.put("/resin/my-printers/My Saturn", json=_printer()).status_code == 404
    assert client.delete("/resin/my-printers/Elegoo Mars 3").status_code == 404


def test_one_users_printers_are_not_another_users(tmp_path: Path):
    store = UserResinPrinters(tmp_path)
    preset = {"name": "Alice's", "sla_archive_format": "CTBENCRYPTED", "printer_technology": "SLA"}
    store.save("alice", "Alice's", preset, {"name": "Alice's"})
    assert [p["name"] for p in store.list("alice")] == ["Alice's"]
    assert store.list("bob") == []
    assert store.preset("bob", "Alice's") is None
    assert store.preset("alice", "Alice's") == preset


def _user(client) -> str:
    return client.get("/auth/status").json().get("username") or "local"


def test_a_printer_of_mine_is_a_printer_to_slice_for(client):
    client.post("/resin/my-printers", json=_printer(name="My Saturn"))
    up = client.post("/models", files={"file": ("cube.stl", io.BytesIO(b"fake stl bytes"), "model/stl")})
    body = {
        "technology": "resin",
        "model_id": up.json()["model_id"],
        "printer_profile": "My Saturn",
        "filament_profiles": ["Test resin"],
        "setting_overrides": {"layer_height": 0.05},
    }
    resp = client.post("/jobs", json=body)
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["id"]
    job: dict = {}
    for _ in range(200):
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "succeeded", job
    printer = json.loads(Path(settings.output_dir, job_id, "args.json").read_text())["printer"]
    assert (printer["display_pixels_x"], printer["display_pixels_y"]) == ("7680", "4320")
    assert printer["name"] == "My Saturn"


def test_the_choice_and_a_saved_printer_know_my_printer(client):
    client.post("/resin/my-printers", json=_printer())
    choice = client.get("/resin/choice", params={"resin": "Test resin", "printer": "My Saturn", "layer_height": 0.05})
    assert choice.status_code == 200, choice.text
    saved = client.post(
        "/printers",
        json={
            "technology": "resin",
            "name": "Mine",
            "vendor": "My printers",
            "machine_profile": "My Saturn",
            "process_profile": "",
            "filament_profiles": ["Test resin"],
        },
    )
    assert saved.status_code == 200, saved.text


def test_the_screen_of_my_printer_is_known_to_the_layer_measuring(client):
    client.post("/resin/my-printers", json=_printer())
    assert resin_module.catalog.screen_mm("My Saturn", _user(client)) == (218.88, 122.88)
    assert resin_module.catalog.screen_mm("My Saturn") == (0.0, 0.0)  # not without its owner


def _choice(client, resin, printer="My Saturn"):
    return client.get("/resin/choice", params={"resin": resin, "printer": printer, "layer_height": 0.05})


def test_a_printer_copied_from_the_catalogue_uses_that_printers_resin_settings(client):
    client.post("/resin/my-printers", json=_printer(copy_from="Elegoo Mars 3"))
    choice = _choice(client, "Specific resin")
    assert choice.status_code == 200, choice.text
    assert choice.json()["settings"]["exposure_time"] == pytest.approx(7)


def test_a_printer_made_from_nothing_has_no_settings_for_a_resin_that_names_printers(client):
    client.post("/resin/my-printers", json=_printer())
    assert _choice(client, "Specific resin").status_code == 404
    assert _choice(client, "Test resin").status_code == 200  # its row is for any printer


def test_the_slicer_is_given_the_resins_row_under_the_name_of_my_printer(client):
    client.post("/resin/my-printers", json=_printer(copy_from="Elegoo Mars 3"))
    up = client.post("/models", files={"file": ("cube.stl", io.BytesIO(b"fake stl bytes"), "model/stl")})
    body = {
        "technology": "resin",
        "model_id": up.json()["model_id"],
        "printer_profile": "My Saturn",
        "filament_profiles": ["Specific resin"],
        "setting_overrides": {"layer_height": 0.05},
    }
    job_id = client.post("/jobs", json=body).json()["id"]
    job: dict = {}
    for _ in range(200):
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "succeeded", job
    rows = json.loads(Path(settings.output_dir, job_id, "args.json").read_text())["material"]["settings"]
    assert rows[0]["printers"] == ["Elegoo Mars 3", "My Saturn"]
    assert rows[0]["exposure_time"] == 7
