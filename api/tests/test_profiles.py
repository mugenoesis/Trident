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


def test_catalog_resolves_inherits_from_same_vendor_base(data_dirs):
    """A leaf profile's `inherits` parent isn't loadable/selectable on its own
    (instantiation:false) but its keys must still reach the leaf's merged
    config -- this is the belt-printer root cause fix: `belt_printer`,
    `gcode_remap_*` etc. are declared only on a base like "fdm_belt_common",
    never repeated on the leaf machine profile.
    """
    profiles_dir = data_dirs["profiles"]
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "Acme.json").write_text(json.dumps({"name": "Acme"}))
    vendor_dir = profiles_dir / "Acme"
    _write_profile(
        vendor_dir,
        "machine",
        "fdm_common_base",
        "machine",
        extra={"instantiation": "false", "belt_printer": "1", "shared_key": "from_base"},
    )
    _write_profile(
        vendor_dir,
        "machine",
        "Acme Belt",
        "machine",
        extra={"inherits": "fdm_common_base", "shared_key": "from_leaf"},
    )

    catalog = profiles_module.ProfileCatalog(profiles_dir)
    catalog.load()

    # The base preset itself stays hidden (instantiation:false).
    assert catalog.get("Acme", "machine", "fdm_common_base") is None
    assert "fdm_common_base" not in {p.name for p in catalog.list()}

    detail = catalog.get("Acme", "machine", "Acme Belt")
    assert detail is not None
    # Inherited-only key reaches the leaf's merged config.
    assert detail.data["belt_printer"] == "1"
    # Leaf's own value wins over the base's for a key both declare.
    assert detail.data["shared_key"] == "from_leaf"


def test_catalog_resolves_inherits_across_vendors_and_multiple_levels(data_dirs):
    """Some chains cross vendor directories on purpose (e.g. a filament's
    "Generic ... @System" parent lives under a separate shared vendor) and
    can be more than one level deep -- both must resolve.
    """
    profiles_dir = data_dirs["profiles"]
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "Shared.json").write_text(json.dumps({"name": "Shared"}))
    (profiles_dir / "Acme.json").write_text(json.dumps({"name": "Acme"}))

    shared_dir = profiles_dir / "Shared"
    _write_profile(shared_dir, "filament", "root_base", "filament", extra={"root_key": "root"})
    _write_profile(
        shared_dir,
        "filament",
        "Generic PLA @System",
        "filament",
        extra={"inherits": "root_base", "mid_key": "system"},
    )

    vendor_dir = profiles_dir / "Acme"
    _write_profile(
        vendor_dir,
        "filament",
        "Generic PLA @Acme",
        "filament",
        extra={"inherits": "Generic PLA @System", "leaf_key": "acme"},
    )

    catalog = profiles_module.ProfileCatalog(profiles_dir)
    catalog.load()

    detail = catalog.get("Acme", "filament", "Generic PLA @Acme")
    assert detail is not None
    assert detail.data["root_key"] == "root"
    assert detail.data["mid_key"] == "system"
    assert detail.data["leaf_key"] == "acme"


def test_catalog_inherits_missing_parent_falls_back_to_own_keys(data_dirs):
    profiles_dir = data_dirs["profiles"]
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "Acme.json").write_text(json.dumps({"name": "Acme"}))
    vendor_dir = profiles_dir / "Acme"
    _write_profile(
        vendor_dir,
        "machine",
        "Orphan",
        "machine",
        extra={"inherits": "does_not_exist", "own_key": "own"},
    )

    catalog = profiles_module.ProfileCatalog(profiles_dir)
    catalog.load()

    detail = catalog.get("Acme", "machine", "Orphan")
    assert detail is not None
    assert detail.data["own_key"] == "own"


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
