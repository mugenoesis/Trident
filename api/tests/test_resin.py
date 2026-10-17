import json
from pathlib import Path

import pytest

from app import resin as resin_module
from app.resin import ResinCatalog, choose_row, match_kind

TWO_ROW_MATERIAL = {
    "type": "material",
    "name": "Test resin",
    "vendor": "Test",
    "settings": [
        {
            "printers": ["Elegoo Mars 3"],
            "layer_height": 0.05,
            "exposure_time": 2.5,
            "initial_exposure_time": 30,
            "source": "a",
        },
        {
            "printers": ["Elegoo Mars 3"],
            "layer_height": 0.1,
            "exposure_time": 4,
            "initial_exposure_time": 40,
            "source": "b",
        },
        {
            "printers": ["Elegoo *"],
            "layer_height": 0.05,
            "exposure_time": 3,
            "initial_exposure_time": 35,
            "source": "c",
        },
        {"printers": ["*"], "layer_height": 0.05, "exposure_time": 5, "initial_exposure_time": 45, "source": "d"},
        {"printers": ["Anycubic Photon Mono"], "layer_height": 0.07, "exposure_time": 6, "initial_exposure_time": 50},
    ],
}


def exposure(row):
    return row["exposure_time"] if row else None


# These cases are the engine's own (tests/sla_print/sla_resin_material_tests.cpp): the numbers shown before slicing
# must be the ones the slicer uses.
def test_the_printers_own_row_then_its_vendor_then_any_printer():
    assert exposure(choose_row(TWO_ROW_MATERIAL, ["Mars 3", "Elegoo Mars 3"], 0.05)) == 2.5
    assert exposure(choose_row(TWO_ROW_MATERIAL, ["Saturn", "Elegoo Saturn"], 0.05)) == 3
    assert exposure(choose_row(TWO_ROW_MATERIAL, ["Halot One", "Creality Halot One CL-60"], 0.05)) == 5


def test_a_row_at_the_asked_layer_height_beats_the_printers_row_at_another():
    assert exposure(choose_row(TWO_ROW_MATERIAL, ["Mars 3"], 0.1)) == 4
    row = choose_row(TWO_ROW_MATERIAL, ["Photon Mono", "Anycubic Photon Mono"], 0.07)
    assert exposure(row) == 6


def test_with_no_row_at_the_layer_height_the_nearest_is_used():
    row = choose_row(TWO_ROW_MATERIAL, ["Mars 3"], 0.07)
    assert row is not None
    assert row["layer_height"] == pytest.approx(0.05)


def test_a_model_name_that_only_ends_the_same_is_another_printer():
    material = {"settings": [{"printers": ["Elegoo Mars 3 Pro"], "layer_height": 0.05, "exposure_time": 9}]}
    assert choose_row(material, ["Mars 3", "Elegoo Mars 3"], 0.05) is None


def test_no_row_for_the_printer_is_none():
    material = {"settings": [{"printers": ["Anycubic Photon"], "layer_height": 0.05, "exposure_time": 9}]}
    assert choose_row(material, ["Mars 3"], 0.05) is None


def test_the_kind_of_match():
    assert match_kind(TWO_ROW_MATERIAL["settings"][0], ["Elegoo Mars 3"]) == "exact"
    assert match_kind(TWO_ROW_MATERIAL["settings"][2], ["Elegoo Saturn"]) == "vendor"
    assert match_kind(TWO_ROW_MATERIAL["settings"][3], ["Anything"]) == "any"


@pytest.fixture()
def resin_dir(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "resin"
    (root / "printers" / "Elegoo").mkdir(parents=True)
    (root / "printers" / "Elegoo" / "Mars 3.json").write_text(
        json.dumps(
            {
                "type": "machine",
                "name": "Elegoo Mars 3",
                "printer_technology": "SLA",
                "printer_model": "Mars 3",
                "display_width": "143.43",
                "display_height": "89.6",
                "display_pixels_x": "4098",
                "display_pixels_y": "2560",
                "printable_height": "175",
                "sla_archive_format": "CTBENCRYPTED",
            }
        )
    )
    (root / "printers" / "Elegoo" / "Old.json").write_text(json.dumps({"type": "machine", "name": "Elegoo Old"}))
    (root / "index.json").write_text(
        json.dumps(
            {
                "printers": [
                    {
                        "vendor": "Elegoo",
                        "model": "Mars 3",
                        "file": "printers/Elegoo/Mars 3.json",
                        "format": "CTBENCRYPTED",
                        "supported": True,
                        "nonsquare_pixels": False,
                    },
                    {
                        "vendor": "Elegoo",
                        "model": "Old",
                        "file": "printers/Elegoo/Old.json",
                        "format": "lgs",
                        "supported": False,
                        "nonsquare_pixels": False,
                    },
                ]
            }
        )
    )
    (root / "materials" / "Test").mkdir(parents=True)
    (root / "materials" / "Test" / "Resin.json").write_text(json.dumps(TWO_ROW_MATERIAL))
    (root / "materials-index.json").write_text(
        json.dumps(
            {
                "materials": [
                    {
                        "name": "Test resin",
                        "vendor": "Test",
                        "family": "Std",
                        "color": "Grey",
                        "resin_type": "standard",
                        "file": "materials/Test/Resin.json",
                        "rows": 5,
                    }
                ]
            }
        )
    )
    catalog = ResinCatalog(root)
    catalog.load()
    monkeypatch.setattr(resin_module, "catalog", catalog)
    return root


def test_the_catalogue_lists_printers_with_their_screen_and_format(resin_dir):
    printers = {p["name"]: p for p in resin_module.catalog.printers()}
    mars = printers["Elegoo Mars 3"]
    assert mars["supported"] is True
    assert mars["format"] == "CTBENCRYPTED"
    assert mars["pixels_x"] == 4098
    assert mars["build_height_mm"] == 175.0
    assert mars["pixel_size_mm"] == pytest.approx(0.035, abs=1e-3)
    assert printers["Elegoo Old"]["supported"] is False
    assert "file" not in mars


def test_a_missing_catalogue_is_empty_not_an_error(tmp_path):
    catalog = ResinCatalog(tmp_path / "nowhere")
    catalog.load()
    assert catalog.printers() == []
    assert catalog.resins() == []
    assert catalog.get_resin("x") is None


def test_the_router_lists_printers_and_resins(client, resin_dir):
    printers = client.get("/resin/printers").json()
    assert {p["name"] for p in printers} == {"Elegoo Mars 3", "Elegoo Old"}
    resins = client.get("/resin/resins").json()
    assert resins == [
        {"name": "Test resin", "vendor": "Test", "family": "Std", "color": "Grey", "resin_type": "standard"}
    ]


def test_the_choice_endpoint_returns_the_row_the_slicer_will_use(client, resin_dir):
    r = client.get("/resin/choice", params={"resin": "Test resin", "printer": "Elegoo Mars 3", "layer_height": 0.05})
    assert r.status_code == 200
    body = r.json()
    assert body["match"] == "exact"
    assert body["exact_layer_height"] is True
    assert body["settings"] == {"exposure_time": 2.5, "initial_exposure_time": 30}
    assert body["source"] == "a"


def test_the_choice_endpoint_says_when_the_layer_height_is_the_nearest(client, resin_dir):
    body = client.get(
        "/resin/choice", params={"resin": "Test resin", "printer": "Elegoo Mars 3", "layer_height": 0.07}
    ).json()
    assert body["exact_layer_height"] is False
    assert body["layer_height"] == pytest.approx(0.05)


def test_the_choice_endpoint_rejects_unknown_names_and_printers_without_a_row(client, resin_dir, tmp_path):
    base = {"layer_height": 0.05}
    assert client.get("/resin/choice", params={**base, "resin": "Nope", "printer": "Elegoo Mars 3"}).status_code == 404
    assert client.get("/resin/choice", params={**base, "resin": "Test resin", "printer": "Nope"}).status_code == 404
    # a resin whose rows do not fit the printer
    material_file = resin_dir / "materials" / "Test" / "Resin.json"
    material_file.write_text(
        json.dumps(
            {
                "type": "material",
                "name": "Test resin",
                "settings": [{"printers": ["Anycubic Photon"], "layer_height": 0.05, "exposure_time": 9}],
            }
        )
    )
    r = client.get("/resin/choice", params={**base, "resin": "Test resin", "printer": "Elegoo Mars 3"})
    assert r.status_code == 404
    assert "no settings" in r.json()["detail"]
