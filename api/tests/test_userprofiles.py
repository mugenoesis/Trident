import io
import json
import zipfile

import pytest

from app import cli_runner, profiles as profiles_module, userprofiles
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
