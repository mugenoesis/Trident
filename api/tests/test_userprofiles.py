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
