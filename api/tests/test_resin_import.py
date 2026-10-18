"""Importing a resin profile from another slicer: a Chitubox .cfg or PrusaSlicer SLA material sections, saved as resins of your own.

The expected numbers are those of the engine's own tests for its importers (Pseudorca tests/sla_print/sla_resin_material_tests.cpp), run on
the same sample files, so the two stay in step."""

from __future__ import annotations

from pathlib import Path

import pytest
from resin_support import FAKE_BIN, build_resin_dir

from app import resin as resin_module
from app.config import settings
from app.resin import ResinCatalog
from app.resin_import import ImportProblem, from_chitubox_cfg, from_prusaslicer_ini

FIXTURES = Path(__file__).parent / "fixtures" / "resin"
CFG = (FIXTURES / "chitubox_siraya_blu_50um.cfg").read_text()
INI = (FIXTURES / "prusaslicer_anycubic_material.ini").read_text()


@pytest.fixture(autouse=True)
def setup(tmp_path: Path, monkeypatch):
    catalog = ResinCatalog(build_resin_dir(tmp_path / "resin"))
    catalog.load()
    monkeypatch.setattr(resin_module, "catalog", catalog)
    monkeypatch.setattr(settings, "models_dir", tmp_path / "models")
    monkeypatch.setattr(settings, "orcaslicer_bin", str(FAKE_BIN))


def test_a_chitubox_profile_gives_its_name_kind_and_the_values_of_its_row():
    material = from_chitubox_cfg(CFG)
    assert material["name"] == "Siraya Blu 50um"
    assert material["resin_type"] == "tough"
    row = material["row"]
    assert row["layer_height"] == pytest.approx(0.05)
    assert row["exposure_time"] == 15
    assert row["initial_exposure_time"] == 65
    assert row["bottom_layer_count"] == 5
    assert row["lift_distance"] == 10
    assert row["lift_speed"] == 48
    assert row["retract_speed"] == 150
    assert row["light_pwm"] == 255
    assert row["delay_before_exposure"] == 0
    assert row["material_density"] == pytest.approx(1.1)
    assert row["bottle_volume"] == 1000  # a price per litre is a bottle of one litre
    assert row["bottle_cost"] == 30


def test_a_file_that_is_not_a_chitubox_profile_is_refused():
    with pytest.raises(ImportProblem, match="Chitubox"):
        from_chitubox_cfg("layerHeight:0.05\n")


def test_prusaslicer_materials_are_imported_with_what_they_inherit():
    materials = from_prusaslicer_ini(INI)
    assert len(materials) == 3  # the two "*common*" sections are not resins
    blue, grey = materials[0], materials[1]
    assert blue["name"] == "Generic Blue Resin @MONO 0.05"
    assert blue["resin_type"] == "tough"
    assert blue["row"]["exposure_time"] == 2.5
    assert blue["row"]["initial_exposure_time"] == 40
    assert blue["row"]["layer_height"] == pytest.approx(0.05)
    assert blue["row"]["lift_distance"] == 8  # from the inherited notes
    assert blue["row"]["lift_speed"] == 150  # 2.5 mm/s
    assert blue["row"]["retract_speed"] == 180  # 3 mm/s
    assert grey["row"]["exposure_time"] == 2.3
    assert grey["row"]["lift_speed"] == 120  # the section's own notes replace the inherited ones
    assert "lift_distance" not in grey["row"]


def test_a_prusaslicer_file_with_no_resin_in_it_is_refused():
    with pytest.raises(ImportProblem, match="exposure time"):
        from_prusaslicer_ini("[sla_material:x]\nfoo = 1\n")


def _upload(client, name, text, **data):
    return client.post("/resin/my-resins/import", files={"file": (name, text.encode(), "text/plain")}, data=data)


def test_an_imported_chitubox_profile_is_a_resin_of_mine_for_the_printer_chosen(client):
    resp = _upload(client, "blu.cfg", CFG, printer="Elegoo Mars 3")
    assert resp.status_code == 200, resp.text
    assert [r["name"] for r in resp.json()["imported"]] == ["Siraya Blu 50um"]
    assert resp.json()["skipped"] == []
    assert any(
        r["name"] == "Siraya Blu 50um" and r["vendor"] == "My resins" for r in client.get("/resin/resins").json()
    )
    choice = client.get(
        "/resin/choice", params={"resin": "Siraya Blu 50um", "printer": "Elegoo Mars 3", "layer_height": 0.05}
    ).json()
    assert choice["settings"]["exposure_time"] == 15
    assert choice["match"] == "exact"
    assert "Chitubox" in choice["source"]


def test_without_a_printer_the_values_are_for_any_printer(client):
    _upload(client, "blu.cfg", CFG)
    choice = client.get(
        "/resin/choice", params={"resin": "Siraya Blu 50um", "printer": "Elegoo Mars 3", "layer_height": 0.05}
    )
    assert choice.status_code == 200
    assert choice.json()["match"] == "any"


def test_prusaslicer_materials_are_imported_together_and_again_without_doubling(client):
    first = _upload(client, "AnycubicSLA.ini", INI).json()
    assert len(first["imported"]) == 3
    _upload(client, "AnycubicSLA.ini", INI)
    mine = [r for r in client.get("/resin/resins").json() if r["vendor"] == "My resins"]
    assert len(mine) == 3


def test_a_profile_named_like_a_built_in_resin_is_skipped_and_says_so(client):
    resp = _upload(client, "x.cfg", CFG.replace("currProfile:Siraya Blu 50um", "currProfile:Test resin"))
    assert resp.status_code == 200
    assert resp.json()["imported"] == []
    assert "built-in" in resp.json()["skipped"][0]["reason"]


@pytest.mark.parametrize(
    ("name", "text", "data", "message"),
    [
        ("junk.txt", "hello", {}, "recognise"),
        ("x.cfg", "layerHeight:0.05\n", {}, "Chitubox"),
        ("blu.cfg", CFG, {"printer": "Nobody"}, "Unknown resin printer"),
    ],
)
def test_a_file_that_cannot_be_imported_says_why(client, name, text, data, message):
    resp = _upload(client, name, text, **data)
    assert resp.status_code == 400
    assert message in resp.json()["detail"]


def test_a_file_that_is_not_text_or_is_too_big_is_refused(client):
    assert (
        client.post(
            "/resin/my-resins/import", files={"file": ("a.cfg", b"\xff\xfe\x00\x01", "application/octet-stream")}
        ).status_code
        == 400
    )
    assert _upload(client, "big.cfg", "a:b\n" * 400_000).status_code == 413
