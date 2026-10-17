"""Saved resin printers: a printer of the resin catalogue with its resin and slice settings, kept next to the filament printers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from resin_support import build_resin_dir

from app import resin as resin_module
from app.printerstore import PrinterStore
from app.resin import ResinCatalog


@pytest.fixture(autouse=True)
def resin_catalog(tmp_path: Path, monkeypatch):
    catalog = ResinCatalog(build_resin_dir(tmp_path / "resin"))
    catalog.load()
    monkeypatch.setattr(resin_module, "catalog", catalog)


def _resin_body(**overrides):
    body = {
        "technology": "resin",
        "name": "Resin corner",
        "vendor": "Elegoo",
        "machine_profile": "Elegoo Mars 3",
        "process_profile": "",
        "filament_profiles": ["Test resin"],
        "resin_settings": {"layer_height": 0.05, "supports": "medium", "exposure_time": 2.5},
    }
    body.update(overrides)
    return body


def test_a_resin_printer_is_saved_with_its_resin_and_settings(client):
    created = client.post("/printers", json=_resin_body())
    assert created.status_code == 200, created.text
    saved = created.json()
    assert saved["technology"] == "resin"
    assert saved["machine_profile"] == "Elegoo Mars 3"
    assert saved["filament_profiles"] == ["Test resin"]
    assert saved["resin_settings"] == {"layer_height": 0.05, "supports": "medium", "exposure_time": 2.5}
    listed = client.get("/printers").json()
    assert [p["technology"] for p in listed] == ["resin"]


def test_a_filament_printer_stays_a_filament_printer(client):
    body = {
        "name": "Bench",
        "vendor": "BBL",
        "machine_profile": "Bambu Lab A1 0.4 nozzle",
        "process_profile": "0.20mm Standard @BBL A1",
        "filament_profiles": ["Bambu PLA Basic @BBL A1"],
        "filament_colors": ["#ffffff"],
    }
    saved = client.post("/printers", json=body).json()
    assert saved["technology"] == "fdm"
    assert saved["resin_settings"] == {}


def test_a_resin_printer_need_not_name_a_resin(client):
    saved = client.post("/printers", json=_resin_body(filament_profiles=[], resin_settings={}))
    assert saved.status_code == 200
    assert saved.json()["filament_profiles"] == []


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"machine_profile": "Nobody Nothing"}, "Unknown resin printer"),
        ({"machine_profile": "Elegoo Old"}, "cannot write"),
        ({"filament_profiles": ["No such resin"]}, "Unknown resin"),
        ({"filament_profiles": ["Test resin", "Test resin"]}, "one resin"),
    ],
)
def test_a_resin_printer_that_cannot_slice_is_refused(client, overrides, message):
    resp = client.post("/printers", json=_resin_body(**overrides))
    assert resp.status_code == 400
    assert message in resp.json()["detail"]


def test_the_settings_of_a_saved_resin_printer_can_be_updated(client):
    printer_id = client.post("/printers", json=_resin_body()).json()["id"]
    resp = client.put(f"/printers/{printer_id}", json={"resin_settings": {"layer_height": 0.025}})
    assert resp.status_code == 200
    assert resp.json()["resin_settings"] == {"layer_height": 0.025}
    assert resp.json()["filament_profiles"] == ["Test resin"]


def test_a_database_from_before_resin_printers_still_reads(tmp_path: Path):
    db = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE printers (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, name TEXT NOT NULL, vendor TEXT NOT NULL,
        machine_profile TEXT NOT NULL, process_profile TEXT NOT NULL, filament_profile TEXT NOT NULL,
        filament_profiles TEXT, filament_colors TEXT, bed_width REAL, bed_depth REAL, bed_height REAL,
        host_type TEXT, print_host TEXT, printhost_apikey TEXT, printhost_user TEXT, printhost_password TEXT,
        created_at TEXT NOT NULL)"""
    )
    conn.execute(
        "INSERT INTO printers (id, user_id, name, vendor, machine_profile, process_profile, filament_profile,"
        " filament_profiles, filament_colors, created_at) VALUES ('p1','u','Old','V','M','P','F','[\"F\"]','[\"#fff\"]','2026-01-01')"
    )
    conn.commit()
    conn.close()
    printer = PrinterStore(db).get_printer("p1")
    assert printer is not None
    assert printer.technology == "fdm"
    assert printer.resin_settings == {}
