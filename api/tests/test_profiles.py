import json

from app import profiles as profiles_module


def _write_profile(vendor_dir, subdir, name, kind, extra=None):
    d = vendor_dir / subdir
    d.mkdir(parents=True, exist_ok=True)
    data = {"name": name, "type": kind}
    if extra:
        data.update(extra)
    (d / f"{name}.json").write_text(json.dumps(data))


def test_catalog_loads_profiles_by_kind(data_dirs):
    profiles_dir = data_dirs["profiles"]
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "Generic.json").write_text(json.dumps({"name": "Generic"}))
    vendor_dir = profiles_dir / "Generic"
    _write_profile(vendor_dir, "machine", "Generic Printer", "machine")
    _write_profile(vendor_dir, "process", "0.20mm Standard", "process")
    _write_profile(vendor_dir, "filament", "Generic PLA", "filament")

    catalog = profiles_module.ProfileCatalog(profiles_dir)
    catalog.load()

    kinds = {p.kind for p in catalog.list()}
    assert kinds == {"machine", "process", "filament"}

    detail = catalog.get("Generic", "process", "0.20mm Standard")
    assert detail is not None
    assert detail.data["type"] == "process"


def test_catalog_get_missing_returns_none(data_dirs):
    catalog = profiles_module.ProfileCatalog(data_dirs["profiles"])
    catalog.load()
    assert catalog.get("Nope", "machine", "Nothing") is None


def test_profiles_endpoint_reflects_catalog(client, data_dirs):
    profiles_dir = data_dirs["profiles"]
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "Generic.json").write_text(json.dumps({"name": "Generic"}))
    vendor_dir = profiles_dir / "Generic"
    _write_profile(vendor_dir, "machine", "Generic Printer", "machine")

    profiles_module.catalog.load()  # lifespan already ran; reload after writing fixtures

    resp = client.get("/profiles")
    assert resp.status_code == 200
    names = [p["name"] for p in resp.json()]
    assert "Generic Printer" in names

    resp = client.get("/profiles/Generic/machine/Generic Printer")
    assert resp.status_code == 200
    assert resp.json()["data"]["type"] == "machine"

    resp = client.get("/profiles/Generic/machine/Nonexistent")
    assert resp.status_code == 404
