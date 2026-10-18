"""The resin list for a printer: only the resins that have settings that fit it, so a resin that would answer "no settings for this printer" is not offered."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from resin_support import build_resin_dir

from app import resin as resin_module
from app.config import settings
from app.resin import ResinCatalog

OLD_ONLY = {
    "type": "material",
    "name": "Old only resin",
    "vendor": "Test",
    "settings": [
        {
            "printers": ["Elegoo Old"],
            "layer_height": 0.05,
            "exposure_time": 8,
            "initial_exposure_time": 50,
            "bottom_layer_count": 6,
            "faded_layers": 4,
            "lift_distance": 5,
            "source": "https://example.org/old",
        }
    ],
}


@pytest.fixture(autouse=True)
def setup(tmp_path: Path, monkeypatch):
    root = build_resin_dir(tmp_path / "resin")
    (root / "materials" / "Test" / "Old.json").write_text(json.dumps(OLD_ONLY))
    index = json.loads((root / "materials-index.json").read_text())
    index["materials"].append({"name": "Old only resin", "vendor": "Test", "file": "materials/Test/Old.json"})
    (root / "materials-index.json").write_text(json.dumps(index))
    catalog = ResinCatalog(root)
    catalog.load()
    monkeypatch.setattr(resin_module, "catalog", catalog)
    monkeypatch.setattr(settings, "models_dir", tmp_path / "models")  # where a user's own resins are kept


def _names(client, printer=None):
    params = {} if printer is None else {"printer": printer}
    resp = client.get("/resin/resins", params=params)
    assert resp.status_code == 200, resp.text
    return {r["name"] for r in resp.json()}


def test_without_a_printer_every_resin_is_listed(client):
    assert _names(client) == {"Test resin", "Specific resin", "Old only resin"}


def test_a_printer_gets_the_resins_with_a_row_that_fits_it(client):
    # "Test resin" has a row for any printer, "Specific resin" one for the Mars 3, "Old only resin" one for another printer
    assert _names(client, "Elegoo Mars 3") == {"Test resin", "Specific resin"}
    assert _names(client, "Elegoo Old") == {"Test resin", "Old only resin"}


def test_a_row_for_a_makers_whole_range_fits_its_printers(client, tmp_path):
    root = tmp_path / "resin"
    (root / "materials" / "Test" / "Vendor.json").write_text(
        json.dumps(
            {
                "type": "material",
                "name": "Vendor resin",
                "vendor": "Test",
                "settings": [
                    {"printers": ["Elegoo *"], "layer_height": 0.05, "exposure_time": 3, "initial_exposure_time": 30}
                ],
            }
        )
    )
    index = json.loads((root / "materials-index.json").read_text())
    index["materials"].append({"name": "Vendor resin", "vendor": "Test", "file": "materials/Test/Vendor.json"})
    (root / "materials-index.json").write_text(json.dumps(index))
    resin_module.catalog.load()
    assert "Vendor resin" in _names(client, "Elegoo Mars 3")
    assert "Vendor resin" in _names(client, "Elegoo Old")


def test_an_unknown_printer_is_a_404(client):
    assert client.get("/resin/resins", params={"printer": "No such printer"}).status_code == 404


def test_a_resin_of_mine_is_listed_for_the_printers_it_has_settings_for(client):
    saved = client.post(
        "/resin/my-resins",
        json={
            "name": "My grey",
            "printer": "Elegoo Mars 3",
            "layer_height": 0.05,
            "settings": {"exposure_time": 3.1, "initial_exposure_time": 25},
            "based_on": None,
        },
    )
    assert saved.status_code == 200, saved.text
    assert "My grey" in _names(client, "Elegoo Mars 3")
    assert "My grey" not in _names(client, "Elegoo Old")
    assert "My grey" in _names(client)


def _choice(client, resin, printer, like=None, layer_height=0.05):
    params = {"resin": resin, "printer": printer, "layer_height": layer_height}
    if like is not None:
        params["like"] = like
    return client.get("/resin/choice", params=params)


def test_a_resin_with_no_settings_for_the_printer_is_still_a_404_unless_asked_for_a_starting_point(client):
    assert _choice(client, "Old only resin", "Elegoo Mars 3").status_code == 404
    assert _choice(client, "Old only resin", "Elegoo Mars 3", like="false").status_code == 404


def test_a_starting_point_carries_the_resins_own_values_and_leaves_the_printers_to_the_user(client):
    resp = _choice(client, "Old only resin", "Elegoo Mars 3", like="true")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["match"] == "other"
    # what belongs to the resin goes across (how many bottom layers, how many to fade over); exposure and lift are the printer's
    assert body["settings"] == {"bottom_layer_count": 6, "faded_layers": 4}
    assert body["reference_printer"] == "Elegoo Old"
    assert body["reference_settings"]["exposure_time"] == 8
    assert body["reference_settings"]["initial_exposure_time"] == 50
    assert body["reference_settings"]["lift_distance"] == 5
    assert body["source"] == "https://example.org/old"
    assert body["layer_height"] == pytest.approx(0.05)


def test_a_starting_point_takes_the_nearest_layer_height(client):
    body = _choice(client, "Old only resin", "Elegoo Mars 3", like="true", layer_height=0.1).json()
    assert body["layer_height"] == pytest.approx(0.05)
    assert body["exact_layer_height"] is False


def test_a_resin_that_has_settings_for_the_printer_is_not_a_starting_point(client):
    body = _choice(client, "Specific resin", "Elegoo Mars 3", like="true").json()
    assert body["match"] == "exact"
    assert body["settings"]["exposure_time"] == 7
    assert body["reference_printer"] is None
    assert body["reference_settings"] == {}


def test_a_resin_with_no_rows_at_all_has_no_starting_point(client, tmp_path):
    root = tmp_path / "resin"
    (root / "materials" / "Test" / "Empty.json").write_text(
        json.dumps({"type": "material", "name": "Empty resin", "vendor": "Test", "settings": []})
    )
    index = json.loads((root / "materials-index.json").read_text())
    index["materials"].append({"name": "Empty resin", "vendor": "Test", "file": "materials/Test/Empty.json"})
    (root / "materials-index.json").write_text(json.dumps(index))
    resin_module.catalog.load()
    assert _choice(client, "Empty resin", "Elegoo Mars 3", like="true").status_code == 404
