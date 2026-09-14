from pathlib import Path

from app.printerstore import PrinterStore


def _printer_fields(**overrides):
    fields = dict(
        name="Living room A1",
        vendor="BBL",
        machine_profile="Bambu Lab A1 0.4 nozzle",
        process_profile="0.20mm Standard @BBL A1",
        filament_profile="Bambu PLA Basic @BBL A1",
        bed_width=256.0,
        bed_depth=256.0,
        bed_height=256.0,
        host_type=None,
        print_host=None,
        printhost_apikey=None,
        printhost_user=None,
        printhost_password=None,
    )
    fields.update(overrides)
    return fields


def test_create_and_get_printer_roundtrip(tmp_path: Path):
    db = PrinterStore(tmp_path / "printers.sqlite3")
    printer = db.create_printer(user_id="alice", **_printer_fields())
    assert printer.name == "Living room A1"
    assert printer.has_credentials is False

    fetched = db.get_printer(printer.id)
    assert fetched is not None
    assert fetched.vendor == "BBL"


def test_credentials_are_masked_but_flagged(tmp_path: Path):
    db = PrinterStore(tmp_path / "printers.sqlite3")
    printer = db.create_printer(
        user_id="alice", **_printer_fields(host_type="moonraker", print_host="http://printer.local", printhost_apikey="secret123")
    )
    assert printer.has_credentials is True
    # PrinterRecord has no field that could leak the raw key.
    assert "secret123" not in printer.model_dump_json()


def test_update_printer_only_touches_given_fields(tmp_path: Path):
    db = PrinterStore(tmp_path / "printers.sqlite3")
    printer = db.create_printer(
        user_id="alice", **_printer_fields(host_type="octoprint", print_host="http://old.local")
    )

    updated = db.update_printer(printer.id, print_host="http://new.local")
    assert updated is not None
    assert updated.print_host == "http://new.local"
    assert updated.host_type == "octoprint"  # untouched
    assert updated.vendor == "BBL"  # untouched, not even an updatable column


def test_update_printer_ignores_non_updatable_columns(tmp_path: Path):
    db = PrinterStore(tmp_path / "printers.sqlite3")
    printer = db.create_printer(user_id="alice", **_printer_fields())

    # vendor isn't in _UPDATABLE_COLUMNS -- silently dropped, not an error.
    updated = db.update_printer(printer.id, vendor="Prusa", name="Renamed")
    assert updated is not None
    assert updated.name == "Renamed"
    assert updated.vendor == "BBL"


def test_update_printer_can_clear_a_credential(tmp_path: Path):
    db = PrinterStore(tmp_path / "printers.sqlite3")
    printer = db.create_printer(
        user_id="alice", **_printer_fields(host_type="moonraker", print_host="http://x", printhost_apikey="k")
    )
    assert printer.has_credentials is True

    updated = db.update_printer(printer.id, printhost_apikey="")
    assert updated is not None
    assert updated.has_credentials is False


def test_list_printers_scoped_to_user(tmp_path: Path):
    db = PrinterStore(tmp_path / "printers.sqlite3")
    mine = db.create_printer(user_id="alice", **_printer_fields())
    db.create_printer(user_id="bob", **_printer_fields(name="Bob's printer"))
    ids = [p.id for p in db.list_printers("alice")]
    assert ids == [mine.id]


def test_delete_printer_cascades_material_profiles(tmp_path: Path):
    db = PrinterStore(tmp_path / "printers.sqlite3")
    printer = db.create_printer(user_id="alice", **_printer_fields())
    material = db.create_material(
        printer_id=printer.id,
        user_id="alice",
        name="PLA",
        quick_settings={"layer_height": "0.2"},
        advanced_overrides={},
        process_profile=None,
        filament_profile=None,
    )
    db.delete_printer(printer.id)
    assert db.get_printer(printer.id) is None
    assert db.get_material(material.id) is None


def test_material_profile_roundtrip(tmp_path: Path):
    db = PrinterStore(tmp_path / "printers.sqlite3")
    printer = db.create_printer(user_id="alice", **_printer_fields())
    material = db.create_material(
        printer_id=printer.id,
        user_id="alice",
        name="PETG",
        quick_settings={"layer_height": "0.24", "sparse_infill_density": "25"},
        advanced_overrides={"cool_plate_temp": "70"},
        process_profile="0.24mm Draft @BBL A1",
        filament_profile="Bambu PETG HF @BBL A1",
    )
    fetched = db.get_material(material.id)
    assert fetched is not None
    assert fetched.quick_settings == {"layer_height": "0.24", "sparse_infill_density": "25"}
    assert fetched.advanced_overrides == {"cool_plate_temp": "70"}

    materials = db.list_materials(printer.id)
    assert [m.id for m in materials] == [material.id]


def _material(db: PrinterStore, printer_id: str, **overrides):
    fields = dict(
        printer_id=printer_id,
        user_id="alice",
        name="PLA",
        quick_settings={"layer_height": "0.2"},
        advanced_overrides={},
        process_profile=None,
        filament_profile=None,
    )
    fields.update(overrides)
    return db.create_material(**fields)


def test_update_material_rename_only(tmp_path: Path):
    db = PrinterStore(tmp_path / "printers.sqlite3")
    printer = db.create_printer(user_id="alice", **_printer_fields())
    material = _material(db, printer.id)

    updated = db.update_material(material.id, name="PLA Renamed")
    assert updated is not None
    assert updated.name == "PLA Renamed"
    assert updated.quick_settings == {"layer_height": "0.2"}  # untouched


def test_update_material_overwrites_settings(tmp_path: Path):
    db = PrinterStore(tmp_path / "printers.sqlite3")
    printer = db.create_printer(user_id="alice", **_printer_fields())
    material = _material(db, printer.id)

    updated = db.update_material(
        material.id,
        quick_settings={"layer_height": "0.28"},
        advanced_overrides={"cool_plate_temp": "60"},
    )
    assert updated is not None
    assert updated.name == "PLA"  # untouched
    assert updated.quick_settings == {"layer_height": "0.28"}
    assert updated.advanced_overrides == {"cool_plate_temp": "60"}


def test_duplicate_material_increments_name(tmp_path: Path):
    db = PrinterStore(tmp_path / "printers.sqlite3")
    printer = db.create_printer(user_id="alice", **_printer_fields())
    original = _material(db, printer.id, name="PLA", quick_settings={"layer_height": "0.2"})

    dup1 = db.duplicate_material(original.id, user_id="alice")
    assert dup1 is not None
    assert dup1.name == "PLA (2)"
    assert dup1.quick_settings == {"layer_height": "0.2"}
    assert dup1.id != original.id

    dup2 = db.duplicate_material(original.id, user_id="alice")
    assert dup2 is not None
    assert dup2.name == "PLA (3)"

    # Duplicating a duplicate strips the existing suffix rather than chaining.
    dup_of_dup = db.duplicate_material(dup1.id, user_id="alice")
    assert dup_of_dup is not None
    assert dup_of_dup.name == "PLA (4)"


def test_duplicate_missing_material_returns_none(tmp_path: Path):
    db = PrinterStore(tmp_path / "printers.sqlite3")
    assert db.duplicate_material("does-not-exist", user_id="alice") is None
