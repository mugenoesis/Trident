import io
import json
import zipfile

import pytest

from app import cli_runner, profiles as profiles_module, userprofiles
from app.profiles import ProfileCatalog
from app.config import settings


def _write(vendor_dir, subdir, name, kind, extra=None):
    d = vendor_dir / subdir
    d.mkdir(parents=True, exist_ok=True)
    data = {"name": name, "type": kind, **(extra or {})}
    (d / f"{name}.json").write_text(json.dumps(data))


@pytest.fixture()
def catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "models_dir", tmp_path / "models")
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "Acme.json").write_text(json.dumps({"name": "Acme"}))
    vendor = profiles_dir / "Acme"
    _write(vendor, "machine", "fdm_base", "machine", {"instantiation": "false", "belt_printer": "1", "from_base": "yes"})
    _write(vendor, "machine", "Acme One 0.4", "machine", {"inherits": "fdm_base"})
    cat = profiles_module.ProfileCatalog(profiles_dir)
    cat.load()
    return cat


def _preset(name="My Printer", kind="machine", **extra):
    return json.dumps({"name": name, "version": "1.0.0.0", "type": kind, **extra}).encode()


def test_single_json_preset_is_parsed():
    presets, issues = userprofiles.parse_upload("p.json", _preset(inherits="Acme One 0.4", print_host="http://x", printhost_apikey="secret"))
    assert issues == []
    (p,) = presets
    assert (p.kind, p.name) == ("machine", "My Printer")
    assert "print_host" not in p.data and "printhost_apikey" not in p.data  # credentials are dropped
    assert p.data["from"] == "User" and p.data["instantiation"] == "true"


def test_kind_falls_back_to_the_settings_id_key():
    raw = json.dumps({"name": "Old Style", "filament_settings_id": "x"}).encode()
    (p,), _ = userprofiles.parse_upload("f.json", raw)
    assert p.kind == "filament"


@pytest.mark.parametrize("bad", [b"not json", b"[1, 2]", json.dumps({"name": "../evil", "type": "machine"}).encode(), json.dumps({"name": "x"}).encode()])
def test_bad_presets_are_reported_not_raised(bad):
    presets, issues = userprofiles.parse_upload("bad.json", bad)
    assert presets == [] and len(issues) == 1


def test_bundle_zip_reads_every_json_and_ignores_structure_file():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("bundle_structure.json", json.dumps({"id": "abc"}))
        zf.writestr("printer/My Printer.json", _preset("My Printer", "machine"))
        zf.writestr("filament/My PLA.json", _preset("My PLA", "filament"))
        zf.writestr("readme.txt", "hello")
    presets, issues = userprofiles.parse_upload("set.orca_bundle", buf.getvalue())
    assert issues == []
    assert sorted((p.kind, p.name) for p in presets) == [("filament", "My PLA"), ("machine", "My Printer")]


def test_corrupt_bundle_is_reported():
    presets, issues = userprofiles.parse_upload("x.zip", b"nope")
    assert presets == [] and "bundle" in issues[0].reason


def test_import_merges_over_a_builtin_parent_and_stays_private(catalog):
    (p,), _ = userprofiles.parse_upload("p.json", _preset(inherits="Acme One 0.4", bed="mine"))
    result = catalog.import_for_user("alice", [p], [], overwrite=False)
    assert [i.name for i in result.imported] == ["My Printer"] and result.imported[0].warning is None

    detail = catalog.get(userprofiles.IMPORTED_VENDOR, "machine", "My Printer", "alice")
    assert detail.data["from_base"] == "yes" and detail.data["belt_printer"] == "1" and detail.data["bed"] == "mine"
    assert "inherits" not in detail.data
    assert catalog.get_by_name("machine", "My Printer", "alice") is not None
    # another user sees neither the listing nor the profile
    assert "My Printer" not in {s.name for s in catalog.list("bob")}
    assert catalog.get_by_name("machine", "My Printer", "bob") is None
    assert "My Printer" in {s.name for s in catalog.list("alice")}


def test_unknown_parent_is_a_warning(catalog):
    (p,), _ = userprofiles.parse_upload("p.json", _preset(inherits="Does Not Exist"))
    (ref,) = catalog.import_for_user("alice", [p], [], False).imported
    assert "Does Not Exist" in ref.warning


def test_name_used_by_a_builtin_is_refused(catalog):
    (p,), _ = userprofiles.parse_upload("p.json", _preset("Acme One 0.4"))
    result = catalog.import_for_user("alice", [p], [], False)
    assert result.imported == [] and "built-in" in result.skipped[0].reason


def test_conflict_needs_overwrite(catalog):
    (p,), _ = userprofiles.parse_upload("p.json", _preset(marker="one"))
    catalog.import_for_user("alice", [p], [], False)
    (p2,), _ = userprofiles.parse_upload("p.json", _preset(marker="two"))
    first = catalog.import_for_user("alice", [p2], [], False)
    assert [c.name for c in first.conflicts] == ["My Printer"] and first.imported == []
    assert catalog.get_by_name("machine", "My Printer", "alice").data["marker"] == "one"
    second = catalog.import_for_user("alice", [p2], [], True)
    assert [i.name for i in second.imported] == ["My Printer"]
    assert catalog.get_by_name("machine", "My Printer", "alice").data["marker"] == "two"


def test_delete_removes_it(catalog):
    (p,), _ = userprofiles.parse_upload("p.json", _preset())
    catalog.import_for_user("alice", [p], [], False)
    assert catalog.delete_imported("alice", "machine", "My Printer") is True
    assert catalog.get_by_name("machine", "My Printer", "alice") is None
    assert catalog.delete_imported("alice", "machine", "My Printer") is False


def test_slice_resolution_uses_the_users_profile(catalog, monkeypatch):
    monkeypatch.setattr(profiles_module, "catalog", catalog)
    (p,), _ = userprofiles.parse_upload("p.json", _preset())
    catalog.import_for_user("alice", [p], [], False)
    assert cli_runner._resolve_profile_detail("machine", "My Printer", "alice").vendor == userprofiles.IMPORTED_VENDOR
    with pytest.raises(ValueError):
        cli_runner._resolve_profile_detail("machine", "My Printer", "bob")


def test_import_routes_end_to_end(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "models_dir", tmp_path / "models")
    files = [("files", ("mine.json", _preset("Route Printer"), "application/json")), ("files", ("junk.json", b"{", "application/json"))]
    body = client.post("/profiles/import", files=files).json()
    assert [i["name"] for i in body["imported"]] == ["Route Printer"]
    assert len(body["skipped"]) == 1
    assert [p["name"] for p in client.get("/profiles/imported").json()] == ["Route Printer"]
    assert "Route Printer" in {p["name"] for p in client.get("/profiles").json()}
    detail = client.get(f"/profiles/{userprofiles.IMPORTED_VENDOR}/machine/Route Printer")
    assert detail.status_code == 200
    assert client.delete("/profiles/imported/machine/Route Printer").status_code == 200
    assert client.delete("/profiles/imported/machine/Route Printer").status_code == 404


# --- materials made with the "New material" form -------------------------------------------

_BASE_FILAMENT = {
    "instantiation": "true",
    "filament_type": ["PLA"],
    "filament_vendor": ["Acme"],
    "nozzle_temperature": ["200", "200"],  # two extruder variants
    "nozzle_temperature_initial_layer": ["205", "205"],
    "nozzle_temperature_range_low": ["190", "190"],
    "nozzle_temperature_range_high": ["230", "230"],
    "hot_plate_temp": ["60"],
    "hot_plate_temp_initial_layer": ["60"],
    "cool_plate_temp": ["0"],
    "filament_flow_ratio": ["0.98"],
    "filament_max_volumetric_speed": ["12"],
    "filament_density": ["1.24"],
    "filament_diameter": ["1.75"],
    "fan_min_speed": ["100"],
    "fan_max_speed": ["100"],
    "compatible_printers": ["Acme One 0.4"],
    "compatible_printers_condition": "",
}


@pytest.fixture()
def material_catalog(catalog, tmp_path):
    _write(tmp_path / "profiles" / "Acme", "filament", "Acme PLA", "filament", _BASE_FILAMENT)
    catalog.load()
    return catalog


def _form(**over):
    form = {
        "filament_type": "PLA", "filament_vendor": "Polymaker",
        "nozzle_temperature": 215, "nozzle_temperature_initial_layer": 220,
        "nozzle_temperature_range_low": 190, "nozzle_temperature_range_high": 240,
        "hot_plate_temp": 65, "cool_plate_temp": 0,
        "filament_flow_ratio": 0.97, "filament_max_volumetric_speed": 14, "filament_density": 1.24,
        "filament_diameter": 1.75, "fan_min_speed": 80, "fan_max_speed": 100,
    }
    form.update(over)
    return form


def test_new_material_inherits_the_base_and_keeps_list_lengths(material_catalog):
    ref = material_catalog.save_filament("u1", "Teal PLA", _form(), base_name="Acme PLA")
    assert (ref.kind, ref.name, ref.inherits) == ("filament", "Teal PLA", "Acme PLA")
    detail = material_catalog.get(userprofiles.IMPORTED_VENDOR, "filament", "Teal PLA", "u1")
    d = detail.data
    assert d["nozzle_temperature"] == ["215", "215"]  # both extruder variants set
    assert d["filament_flow_ratio"] == ["0.97"] and d["fan_min_speed"] == ["80"]
    assert d["filament_vendor"] == ["Polymaker"]
    # a bed temperature also sets the first-layer twin; one the form did not send keeps the base value
    assert d["hot_plate_temp"] == ["65"] and d["hot_plate_temp_initial_layer"] == ["65"]
    # the base's printer whitelist is cleared so the material shows for every printer
    assert d["compatible_printers"] == [] and d["from"] == "User"
    # a setting the form never touches comes from the base
    assert d["compatible_printers_condition"] == ""


def test_new_material_name_clashes_are_refused(material_catalog):
    material_catalog.save_filament("u1", "Teal PLA", _form(), base_name="Acme PLA")
    with pytest.raises(userprofiles.MaterialConflict):
        material_catalog.save_filament("u1", "Teal PLA", _form(), base_name="Acme PLA")
    with pytest.raises(userprofiles.MaterialConflict):
        material_catalog.save_filament("u1", "Acme PLA", _form(), base_name="Acme PLA")  # a built-in name
    # another user is unaffected by the first user's material
    material_catalog.save_filament("u2", "Teal PLA", _form(), base_name="Acme PLA")


def test_a_material_can_be_based_on_another_of_the_users_materials(material_catalog):
    material_catalog.save_filament("u1", "Teal PLA", _form(nozzle_temperature=215), base_name="Acme PLA")
    material_catalog.save_filament("u1", "Teal PLA fast", _form(filament_max_volumetric_speed=20), base_name="Teal PLA")
    d = material_catalog.get(userprofiles.IMPORTED_VENDOR, "filament", "Teal PLA fast", "u1").data
    assert d["filament_max_volumetric_speed"] == ["20"] and d["nozzle_temperature"] == ["215", "215"]


def test_editing_a_material_keeps_its_base_and_other_keys(material_catalog):
    material_catalog.save_filament("u1", "Teal PLA", _form(), base_name="Acme PLA")
    stored = userprofiles.store.load_all("u1")[("filament", "Teal PLA")]
    stored["filament_notes"] = "kept"  # a key the form does not know about
    userprofiles.store.save("u1", userprofiles.ParsedPreset("filament", "Teal PLA", stored))
    material_catalog._user_cache.pop("u1", None)
    ref = material_catalog.save_filament("u1", "Teal PLA", _form(nozzle_temperature=205), edit=True)
    assert ref.inherits == "Acme PLA"
    d = material_catalog.get(userprofiles.IMPORTED_VENDOR, "filament", "Teal PLA", "u1").data
    assert d["nozzle_temperature"] == ["205", "205"] and d["filament_notes"] == "kept"
    with pytest.raises(userprofiles.MaterialNotFound):
        material_catalog.save_filament("u1", "Nope", _form(), edit=True)


@pytest.mark.parametrize(
    "bad, message",
    [
        ({"nozzle_temperature": "hot"}, "must be a number"),
        ({"nozzle_temperature": 900}, "between"),
        ({"filament_flow_ratio": 0}, "between"),
        ({"nozzle_temperature_range_low": 250}, "lowest nozzle temperature is above"),
        ({"fan_min_speed": 90, "fan_max_speed": 50}, "minimum fan speed is above"),
        ({"filament_type": ""}, "material type"),
        ({"nozzle_temperature": float("nan")}, "between"),
    ],
)
def test_material_form_values_are_validated(material_catalog, bad, message):
    with pytest.raises(userprofiles.MaterialError, match=message):
        material_catalog.save_filament("u1", "Teal PLA", _form(**bad), base_name="Acme PLA")
    assert ("filament", "Teal PLA") not in userprofiles.store.load_all("u1")  # nothing half-saved


def test_material_names_must_be_plain_text(material_catalog):
    for name in ("../evil", "a/b", " padded ", ""):
        with pytest.raises(userprofiles.MaterialError):
            material_catalog.save_filament("u1", name, _form(), base_name="Acme PLA")


def test_material_with_an_unknown_base_is_refused(material_catalog):
    with pytest.raises(userprofiles.MaterialNotFound):
        material_catalog.save_filament("u1", "Teal PLA", _form(), base_name="Does not exist")
    with pytest.raises(userprofiles.MaterialNotFound):
        material_catalog.save_filament("u1", "Teal PLA", _form())


def _api_form(**over):
    form = {
        "name": "Teal PLA", "base_name": "Acme PLA", "filament_type": "PLA", "filament_vendor": "Polymaker",
        "nozzle_temperature": 215, "nozzle_temperature_initial_layer": 220,
        "nozzle_temperature_range_low": 190, "nozzle_temperature_range_high": 240,
        "plate_temps": {"hot_plate_temp": 65, "cool_plate_temp": 0},
        "filament_flow_ratio": 0.97, "filament_max_volumetric_speed": 14, "filament_density": 1.24,
        "filament_diameter": 1.75, "fan_min_speed": 80, "fan_max_speed": 100,
    }
    form.update(over)
    return form


def test_filament_routes_create_edit_and_delete(client, material_catalog, monkeypatch):
    monkeypatch.setattr(profiles_module, "catalog", material_catalog)
    created = client.post("/profiles/filaments", json=_api_form())
    assert created.status_code == 200 and created.json()["inherits"] == "Acme PLA"
    assert "Teal PLA" in {p["name"] for p in client.get("/profiles").json()}
    detail = client.get(f"/profiles/{userprofiles.IMPORTED_VENDOR}/filament/Teal PLA").json()["data"]
    assert detail["nozzle_temperature"] == ["215", "215"] and detail["hot_plate_temp"] == ["65"]

    assert client.post("/profiles/filaments", json=_api_form()).status_code == 409  # same name again
    assert client.post("/profiles/filaments", json=_api_form(name="Other", base_name="Nope")).status_code == 404
    bad = client.post("/profiles/filaments", json=_api_form(name="Hot", nozzle_temperature=900))
    assert bad.status_code == 422 and "between" in bad.json()["detail"]
    bad_plate = client.post("/profiles/filaments", json=_api_form(name="Plate", plate_temps={"bogus_temp": 5}))
    assert bad_plate.status_code == 422

    edited = client.put("/profiles/filaments/Teal PLA", json=_api_form(nozzle_temperature=205))
    assert edited.status_code == 200 and edited.json()["inherits"] == "Acme PLA"
    detail = client.get(f"/profiles/{userprofiles.IMPORTED_VENDOR}/filament/Teal PLA").json()["data"]
    assert detail["nozzle_temperature"] == ["205", "205"]
    assert client.put("/profiles/filaments/Teal PLA", json=_api_form(name="Renamed")).status_code == 422  # no rename
    assert client.put("/profiles/filaments/Missing", json=_api_form(name="Missing")).status_code == 404

    assert client.delete("/profiles/imported/filament/Teal PLA").status_code == 200
    assert "Teal PLA" not in {p["name"] for p in client.get("/profiles").json()}


def test_material_printer_scope_is_stored_listed_and_kept_on_edit(material_catalog):
    material_catalog.save_filament("u1", "U1 only", _form(printers=["Acme U1 (0.4)", " Acme U1 (0.4)", ""]), base_name="Acme PLA")
    material_catalog.save_filament("u1", "Anywhere", _form(), base_name="Acme PLA")
    listed = {p.name: p for p in material_catalog.list("u1") if p.vendor == userprofiles.IMPORTED_VENDOR}
    assert listed["U1 only"].compatible_printers == ["Acme U1 (0.4)"]  # trimmed, de-duplicated
    assert listed["Anywhere"].compatible_printers == []
    # editing without a choice keeps the stored scope; an explicit choice changes it
    material_catalog.save_filament("u1", "U1 only", _form(nozzle_temperature=210), edit=True)
    assert material_catalog.get(userprofiles.IMPORTED_VENDOR, "filament", "U1 only", "u1").data["compatible_printers"] == ["Acme U1 (0.4)"]
    material_catalog.save_filament("u1", "U1 only", _form(printers=[]), edit=True)
    assert material_catalog.get(userprofiles.IMPORTED_VENDOR, "filament", "U1 only", "u1").data["compatible_printers"] == []


def test_built_in_profiles_report_no_printer_scope(material_catalog):
    assert all(p.compatible_printers == [] for p in material_catalog.list("u1") if p.vendor != userprofiles.IMPORTED_VENDOR)


# --- printers made in the app ------------------------------------------------

@pytest.fixture
def printer_catalog(tmp_path, monkeypatch):
    """A catalog with a built-in printer (a copy of which is made) and the slicer's generic ones."""
    monkeypatch.setattr(userprofiles.settings, "models_dir", tmp_path / "models")
    monkeypatch.setattr(userprofiles, "_allowed_values", lambda key: None)
    cat = ProfileCatalog(tmp_path / "profiles")
    vendor = tmp_path / "profiles" / "Acme" / "machine"
    vendor.mkdir(parents=True)
    (tmp_path / "profiles" / "Acme.json").write_text("{}")
    (vendor / "Acme X 0.4 nozzle.json").write_text(json.dumps({
        "name": "Acme X 0.4 nozzle", "type": "machine", "instantiation": "true", "printer_model": "Acme X",
        "nozzle_diameter": ["0.4"], "printable_area": ["0x0", "220x0", "220x220", "0x220"], "printable_height": "250",
        "gcode_flavor": "marlin2", "machine_start_gcode": "G28\nM109 S[nozzle_temperature_initial_layer]",
        "machine_max_speed_x": ["500", "200"], "machine_max_speed_y": ["500", "200"],
        "retraction_length": ["0.8", "0.8"], "z_hop": ["0.4", "0.4"],
        "default_print_profile": "0.20mm Standard @Acme", "default_filament_profile": ["Acme PLA"],
    }))
    custom = tmp_path / "profiles" / "Custom" / "machine"
    custom.mkdir(parents=True)
    (tmp_path / "profiles" / "Custom.json").write_text("{}")
    for generic, extra in (
        ("MyMarlin 0.4 nozzle", {"gcode_flavor": "marlin"}),
        ("MyKlipper 0.4 nozzle", {"gcode_flavor": "klipper"}),
        ("MyBeltPrinter 0.4 nozzle", {"gcode_flavor": "klipper", "belt_printer": "1", "belt_printer_infinite_y": "1", "belt_slice_rotation_angle": "45"}),
    ):
        (custom / f"{generic}.json").write_text(json.dumps({
            "name": generic, "type": "machine", "instantiation": "true", "nozzle_diameter": ["0.4"],
            "printable_area": ["0x0", "250x0", "250x250", "0x250"], "printable_height": "250",
            "machine_start_gcode": "G28", **extra,
        }))
    cat.load()
    return cat


def _pform(**over):
    form = {"width": 300, "depth": 220, "height": 250, "start_gcode": "G28", "nozzle_diameter": 0.4}
    form.update(over)
    return form


def test_printer_copy_inherits_the_base_and_sets_the_bed(printer_catalog):
    ref = printer_catalog.save_printer("u1", "My Acme", _pform(origin_x=5, origin_y=-3, max_speed=300, retraction_length=1.2, z_hop=0.6), base_name="Acme X 0.4 nozzle")
    assert (ref.kind, ref.name, ref.inherits) == ("machine", "My Acme", "Acme X 0.4 nozzle")
    d = printer_catalog.get(userprofiles.IMPORTED_VENDOR, "machine", "My Acme", "u1").data
    assert d["printable_area"] == ["5x-3", "305x-3", "305x217", "5x217"] and d["printable_height"] == "250"
    assert d["machine_max_speed_x"] == ["300", "300"]  # keeps the base's list length
    assert d["retraction_length"] == ["1.2", "1.2"] and d["z_hop"] == ["0.6", "0.6"]
    assert d["printer_model"] == "Acme X"  # inherited, not copied
    assert d["default_filament_profile"] == ["Acme PLA"]


def test_printer_with_no_base_starts_from_the_generic_printer_for_the_firmware(printer_catalog):
    marlin = printer_catalog.save_printer("u1", "From nothing", _pform(gcode_flavor="marlin2"))
    klipper = printer_catalog.save_printer("u1", "Klipper one", _pform(gcode_flavor="klipper"))
    assert marlin.inherits == "MyMarlin 0.4 nozzle" and klipper.inherits == "MyKlipper 0.4 nozzle"
    assert printer_catalog.get(userprofiles.IMPORTED_VENDOR, "machine", "From nothing", "u1").data["gcode_flavor"] == "marlin2"


def test_endless_belt_gets_a_long_plate_and_the_flag(printer_catalog):
    printer_catalog.save_printer("u1", "Belt", _pform(width=250, belt=True, belt_endless=True, belt_angle=40))
    d = printer_catalog.get(userprofiles.IMPORTED_VENDOR, "machine", "Belt", "u1").data
    assert d["belt_printer"] == "1" and d["belt_printer_infinite_y"] == "1" and d["belt_slice_rotation_angle"] == "40"
    assert d["printable_area"] == ["0x0", "250x0", "250x2000", "0x2000"]
    assert printer_catalog.stored_preset("u1", "machine", "Belt")["inherits"] == "MyBeltPrinter 0.4 nozzle"


def test_limited_belt_uses_the_given_length(printer_catalog):
    printer_catalog.save_printer("u1", "Short belt", _pform(width=95, belt=True, belt_endless=False, belt_length=500))
    d = printer_catalog.get(userprofiles.IMPORTED_VENDOR, "machine", "Short belt", "u1").data
    assert d["belt_printer_infinite_y"] == "0" and d["printable_area"] == ["0x0", "95x0", "95x500", "0x500"]
    with pytest.raises(userprofiles.PrinterError):
        printer_catalog.save_printer("u1", "No length", _pform(belt=True, belt_endless=False))


def test_centred_and_round_beds(printer_catalog):
    printer_catalog.save_printer("u1", "Centred", _pform(origin_centre=True))
    assert printer_catalog.get(userprofiles.IMPORTED_VENDOR, "machine", "Centred", "u1").data["printable_area"] == ["-150x-110", "150x-110", "150x110", "-150x110"]
    printer_catalog.save_printer("u1", "Round", _pform(shape="circle", width=200, origin_centre=True))
    pts = printer_catalog.get(userprofiles.IMPORTED_VENDOR, "machine", "Round", "u1").data["printable_area"]
    assert len(pts) == 48 and "100x0" in pts


def test_printer_advanced_settings_keep_the_base_shape_and_can_be_removed(printer_catalog):
    printer_catalog.save_printer("u1", "Adv", _pform(advanced={"machine_pause_gcode": "M601", "bed_exclude_area": "0x0, 20x0, 20x20"}), base_name="Acme X 0.4 nozzle")
    stored = printer_catalog.stored_preset("u1", "machine", "Adv")
    assert stored["machine_pause_gcode"] == "M601" and stored["bed_exclude_area"] == "0x0, 20x0, 20x20"  # base has none: kept as text
    # editing without one drops it; with another keeps the others
    printer_catalog.save_printer("u1", "Adv", _pform(advanced={"machine_pause_gcode": "M25"}), edit=True)
    stored = printer_catalog.stored_preset("u1", "machine", "Adv")
    assert stored["machine_pause_gcode"] == "M25" and "bed_exclude_area" not in stored and stored["inherits"] == "Acme X 0.4 nozzle"


@pytest.mark.parametrize(
    "over,message",
    [
        ({"width": 5}, "bed width"),
        ({"height": 99999}, "maximum height"),
        ({"nozzle_diameter": 5}, "nozzle diameter"),
        ({"start_gcode": "   "}, "can't be empty"),
        ({"shape": "triangle"}, "rectangle or a circle"),
        ({"advanced": {"filament_type": "PLA"}}, "not a printer setting"),
        ({"advanced": {"printable_area": "0x0"}}, "not a printer setting"),
        ({"max_speed": "fast"}, "must be a number"),
    ],
)
def test_printer_form_values_are_validated(printer_catalog, over, message):
    with pytest.raises(userprofiles.PrinterError, match=message):
        printer_catalog.save_printer("u1", "Bad", _pform(**over), base_name="Acme X 0.4 nozzle")


def test_printer_name_clashes_and_unknown_bases_are_refused(printer_catalog):
    with pytest.raises(userprofiles.PrinterConflict):
        printer_catalog.save_printer("u1", "Acme X 0.4 nozzle", _pform())
    printer_catalog.save_printer("u1", "Mine", _pform())
    with pytest.raises(userprofiles.PrinterConflict):
        printer_catalog.save_printer("u1", "Mine", _pform())
    with pytest.raises(userprofiles.PrinterNotFound):
        printer_catalog.save_printer("u1", "Other", _pform(), base_name="Nope")
    with pytest.raises(userprofiles.PrinterNotFound):
        printer_catalog.save_printer("u1", "Ghost", _pform(), edit=True)
    with pytest.raises(userprofiles.PrinterError):
        printer_catalog.save_printer("u1", "a/b", _pform())


def test_export_round_trips_through_the_importer(printer_catalog):
    printer_catalog.save_printer("u1", "Export me", _pform(advanced={"machine_pause_gcode": "M601"}), base_name="Acme X 0.4 nozzle")
    data, filename = userprofiles.build_export("u1", [("machine", "Export me")])
    assert filename == "Export me.orca_printer"
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert "printer/Export me.json" in zf.namelist() and "bundle_structure.json" in zf.namelist()
        meta = json.loads(zf.read("bundle_structure.json"))
        assert meta["printer_preset_name"] == ["Export me"]
    presets, issues = userprofiles.parse_upload(filename, data)
    assert not issues and [(p.kind, p.name) for p in presets] == [("machine", "Export me")]
    assert presets[0].data["inherits"] == "Acme X 0.4 nozzle" and presets[0].data["machine_pause_gcode"] == "M601"
    two, name2 = userprofiles.build_export("u1", [("machine", "Export me"), ("machine", "Export me")])
    assert name2 == "Export me.orca_printer"  # duplicates collapse
    with pytest.raises(userprofiles.PrinterNotFound):
        userprofiles.build_export("u1", [("machine", "nope")])
    with pytest.raises(userprofiles.PrinterError):
        userprofiles.build_export("u1", [])


def test_printer_routes_create_edit_export_and_delete(client, printer_catalog, monkeypatch):
    monkeypatch.setattr(profiles_module, "catalog", printer_catalog)
    body = {"name": "Route printer", "base_name": "Acme X 0.4 nozzle", "width": 300, "depth": 220, "height": 250, "start_gcode": "G28", "advanced": {"machine_pause_gcode": "M601"}}
    created = client.post("/profiles/printers", json=body)
    assert created.status_code == 200 and created.json()["inherits"] == "Acme X 0.4 nozzle"
    assert "Route printer" in {p["name"] for p in client.get("/profiles").json() if p["kind"] == "machine"}
    stored = client.get("/stored-profiles/machine/Route printer").json()
    assert stored["machine_pause_gcode"] == "M601" and stored["inherits"] == "Acme X 0.4 nozzle"
    assert client.get("/stored-profiles/machine/Nope").status_code == 404
    keys = client.get("/profiles/printer-keys").json()
    assert "machine_pause_gcode" in keys and "printable_area" not in keys and "filament_type" not in keys

    assert client.post("/profiles/printers", json=body).status_code == 409
    assert client.post("/profiles/printers", json={**body, "name": "Other", "base_name": "Nope"}).status_code == 404
    assert client.post("/profiles/printers", json={**body, "name": "Wide", "width": 1}).status_code == 422
    edited = client.put("/profiles/printers/Route printer", json={**body, "width": 310, "advanced": {}})
    assert edited.status_code == 200
    assert client.get("/stored-profiles/machine/Route printer").json().get("machine_pause_gcode") is None
    assert client.put("/profiles/printers/Route printer", json={**body, "name": "Renamed"}).status_code == 422

    exported = client.post("/profiles/export", json={"items": [{"kind": "machine", "name": "Route printer"}]})
    assert exported.status_code == 200 and 'filename="Route printer.orca_printer"' in exported.headers["content-disposition"]
    assert zipfile.ZipFile(io.BytesIO(exported.content)).namelist()
    assert client.post("/profiles/export", json={"items": [{"kind": "machine", "name": "Nope"}]}).status_code == 404
    assert client.post("/profiles/export", json={"items": []}).status_code == 422

    assert client.delete("/profiles/imported/machine/Route printer").status_code == 200


# --- materials: the Advanced settings ----------------------------------------

def test_material_advanced_settings_keep_the_base_shape_and_can_be_removed(material_catalog):
    material_catalog.save_filament("u1", "Adv PLA", _form(advanced={"filament_cost": "27.5", "slow_down_layer_time": "6, 8"}), base_name="Acme PLA")
    stored = material_catalog.stored_preset("u1", "filament", "Adv PLA")
    assert stored["filament_cost"] == "27.5"
    assert stored["slow_down_layer_time"] == "6, 8"  # base has no value for it: kept as typed
    resolved = material_catalog.get(userprofiles.IMPORTED_VENDOR, "filament", "Adv PLA", "u1").data
    assert resolved["filament_cost"] == "27.5"
    # a form with no advanced list leaves them as they are; one with a list makes it exact
    material_catalog.save_filament("u1", "Adv PLA", _form(nozzle_temperature=205), edit=True)
    assert material_catalog.stored_preset("u1", "filament", "Adv PLA")["filament_cost"] == "27.5"
    material_catalog.save_filament("u1", "Adv PLA", _form(advanced={"slow_down_layer_time": "9"}), edit=True)
    stored = material_catalog.stored_preset("u1", "filament", "Adv PLA")
    assert "filament_cost" not in stored and stored["slow_down_layer_time"] == "9" and stored["inherits"] == "Acme PLA"
    material_catalog.save_filament("u1", "Adv PLA", _form(advanced={}), edit=True)
    assert "slow_down_layer_time" not in material_catalog.stored_preset("u1", "filament", "Adv PLA")


@pytest.mark.parametrize("advanced", [{"nozzle_temperature": "999"}, {"layer_height": "0.1"}, {"machine_start_gcode": "G28"}, {"name": "x"}])
def test_material_advanced_refuses_managed_and_non_filament_settings(material_catalog, advanced):
    with pytest.raises(userprofiles.MaterialError, match="not a material setting"):
        material_catalog.save_filament("u1", "Bad Adv", _form(advanced=advanced), base_name="Acme PLA")


def test_material_advanced_routes(client, material_catalog, monkeypatch):
    monkeypatch.setattr(profiles_module, "catalog", material_catalog)
    body = _api_form(name="Route Adv", advanced={"filament_cost": "30"})
    assert client.post("/profiles/filaments", json=body).status_code == 200
    assert client.get("/stored-profiles/filament/Route Adv").json()["filament_cost"] == "30"
    assert client.get("/stored-profiles/filament/Nope").status_code == 404
    assert client.get("/stored-profiles/bogus/Route Adv").status_code == 404
    keys = client.get("/profiles/filament-keys").json()
    assert "filament_cost" in keys and "nozzle_temperature" not in keys and "machine_start_gcode" not in keys
    bad = client.post("/profiles/filaments", json=_api_form(name="Bad", advanced={"layer_height": "1"}))
    assert bad.status_code == 422
