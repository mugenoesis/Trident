import json
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

from app.threemf_objects import list_objects, plates_of_selection, write_derived_3mf

_NS = 'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"'

# name, width, depth, height, plate, x, y (build-item translation)
_BOXES = [
    ("Block A", 30, 20, 20, 1, 80, 40),
    ("Tall B", 15, 15, 45, 1, 160, 60),
    ("Wide C", 60, 25, 12, 2, 420, 50),
    ("Cube D", 25, 25, 25, 3, 670, 40),
]


def _mesh(w: float, d: float, h: float) -> str:
    v = [(0, 0, 0), (w, 0, 0), (w, d, 0), (0, d, 0), (0, 0, h), (w, 0, h), (w, d, h), (0, d, h)]
    verts = "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in v)
    return f"<mesh><vertices>{verts}</vertices><triangles><triangle v1=\"0\" v2=\"1\" v3=\"2\"/></triangles></mesh>"


def _write_project(tmp_path: Path, name: str = "p.3mf") -> Path:
    objs = "".join(f'<object id="{i}" type="model">{_mesh(*b[1:4])}</object>' for i, b in enumerate(_BOXES, 1))
    items = "".join(
        f'<item objectid="{i}" transform="1 0 0 0 1 0 0 0 1 {b[5]} {b[6]} 0" printable="1"/>'
        for i, b in enumerate(_BOXES, 1)
    )
    model = f'<?xml version="1.0"?><model unit="millimeter" {_NS}><resources>{objs}</resources><build>{items}</build></model>'
    cfg_objects = "".join(
        f'<object id="{i}"><metadata key="name" value="{b[0]}"/></object>' for i, b in enumerate(_BOXES, 1)
    )
    plates: dict[int, list[int]] = {}
    for i, b in enumerate(_BOXES, 1):
        plates.setdefault(b[4], []).append(i)
    cfg_plates = "".join(
        f'<plate><metadata key="plater_id" value="{p}"/>'
        + "".join(
            f'<model_instance><metadata key="object_id" value="{i}"/><metadata key="instance_id" value="0"/></model_instance>'
            for i in ids
        )
        + "</plate>"
        for p, ids in plates.items()
    )
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("3D/3dmodel.model", model)
        zf.writestr("Metadata/model_settings.config", f"<config>{cfg_objects}{cfg_plates}</config>")
        zf.writestr("Metadata/extra.txt", "kept verbatim")
    return path


def test_list_objects_names_plates_sizes(tmp_path):
    objs = list_objects(_write_project(tmp_path))
    assert [o.name for o in objs] == ["Block A", "Tall B", "Wide C", "Cube D"]
    assert [o.plate for o in objs] == [1, 1, 2, 3]
    assert (objs[1].width_mm, objs[1].depth_mm, objs[1].height_mm) == (15, 15, 45)


def test_list_objects_never_raises_on_garbage(tmp_path):
    bad = tmp_path / "bad.3mf"
    bad.write_bytes(b"not a zip")
    assert list_objects(bad) == []


def test_plates_of_selection(tmp_path):
    path = _write_project(tmp_path)
    assert plates_of_selection(path, {1}) == {1, 2, 3}
    assert plates_of_selection(path, {2}) == {1, 3}  # object 2 is alone on plate 2
    assert plates_of_selection(path, {2, 3, 4}) == {1}


def test_exclusion_only_keeps_plates_and_positions(tmp_path):
    src = _write_project(tmp_path)
    dst = tmp_path / "out.3mf"
    kept = write_derived_3mf(src, dst, excluded={1})
    assert kept == [0, 2, 3]
    objs = list_objects(dst)
    assert [o.name for o in objs] == ["Block A", "Wide C", "Cube D"]
    assert [o.plate for o in objs] == [1, 2, 3]
    with zipfile.ZipFile(dst) as zf:
        assert zf.read("Metadata/extra.txt") == b"kept verbatim"
        model = zf.read("3D/3dmodel.model").decode()
    assert 'transform="1 0 0 0 1 0 0 0 1 420 50 0"' in model  # untouched


def test_row_layout_centres_x_stacks_y_and_merges_plates(tmp_path):
    src = _write_project(tmp_path)
    dst = tmp_path / "out.3mf"
    kept = write_derived_3mf(src, dst, excluded={1}, order=[3, 0, 2], gap_mm=10, center_x=125)
    assert kept == [3, 0, 2]
    with zipfile.ZipFile(dst) as zf:
        model = zf.read("3D/3dmodel.model").decode()
        cfg = zf.read("Metadata/model_settings.config").decode()
    # Object ids 4 (Cube D, 25 deep), 1 (Block A, 20 deep), 3 (Wide C, 25 deep) are rewritten in place
    # (item order in the file is unchanged); each is centred on x=125 with its min-Y at the running cursor.
    assert 'objectid="1" transform="1 0 0 0 1 0 0 0 1 110 35 0"' in model  # cursor 35 = 25 + 10
    assert 'objectid="4" transform="1 0 0 0 1 0 0 0 1 112.5 0 0"' in model
    assert 'objectid="3" transform="1 0 0 0 1 0 0 0 1 95 65 0"' in model  # cursor 65 = 35 + 20 + 10
    assert 'objectid="2"' not in model
    assert cfg.count("<plate>") == 1
    # instances follow the layout order: object 4, 1, 3
    root_cfg = ET.fromstring(cfg)
    ids = [
        next(m.get("value") for m in inst.findall("metadata") if m.get("key") == "object_id")
        for inst in root_cfg.find("plate").findall("model_instance")
    ]
    assert ids == ["4", "1", "3"]


def test_partial_and_stale_order_is_tolerated(tmp_path):
    src = _write_project(tmp_path)
    kept = write_derived_3mf(src, tmp_path / "o.3mf", excluded=set(), order=[3, 99, 1])
    assert kept == [3, 1, 0, 2]


def test_everything_excluded_is_an_error(tmp_path):
    src = _write_project(tmp_path)
    with pytest.raises(ValueError):
        write_derived_3mf(src, tmp_path / "o.3mf", excluded={0, 1, 2, 3})


def test_component_objects_in_external_model_file(tmp_path):
    # Production-extension layout: the root object is a <components> wrapper
    # whose mesh lives in a separate .model file, with its own transform.
    prod = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
    root = (
        f'<?xml version="1.0"?><model unit="millimeter" {_NS} xmlns:p="{prod}"><resources>'
        '<object id="9" type="model"><components>'
        '<component p:path="/3D/Objects/o.model" objectid="1" transform="1 0 0 0 1 0 0 0 1 5 0 0"/>'
        "</components></object></resources>"
        '<build><item objectid="9" p:UUID="abc" transform="1 0 0 0 1 0 0 0 1 100 0 0" printable="1"/></build></model>'
    )
    part = f'<?xml version="1.0"?><model {_NS}><resources><object id="1">{_mesh(10, 20, 30)}</object></resources></model>'
    path = tmp_path / "prod.3mf"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("3D/3dmodel.model", root)
        zf.writestr("3D/Objects/o.model", part)
    (obj,) = list_objects(path)
    assert (obj.width_mm, obj.depth_mm, obj.height_mm) == (10, 20, 30)
    out = tmp_path / "o.3mf"
    write_derived_3mf(path, out, excluded=set(), order=[0], center_x=50)
    with zipfile.ZipFile(out) as zf:
        model = zf.read("3D/3dmodel.model").decode()
    assert 'p:UUID="abc"' in model  # production attributes survive the text rewrite
    assert 'transform="1 0 0 0 1 0 0 0 1 40 0 0"' in model  # box spans x 105..115 -> centred on 50 means shift -60


def test_list_objects_reports_centres(tmp_path):
    objs = list_objects(_write_project(tmp_path))
    assert (objs[0].center_x_mm, objs[0].center_y_mm) == (95.0, 50.0)  # Block A: x 80..110, y 40..60


def test_placement_moves_the_group_centre_and_declares_the_bed(tmp_path):
    src = _write_project(tmp_path)
    dst = tmp_path / "placed.3mf"
    write_derived_3mf(
        src, dst, excluded={1, 2, 3}, placement=(125.0, 40.0), bed_area=["0x0", "250x0", "250x2000", "0x2000"], bed_height=250.0
    )
    (obj,) = list_objects(dst)
    assert (obj.center_x_mm, obj.center_y_mm) == (125.0, 40.0)
    with zipfile.ZipFile(dst) as zf:
        project = json.loads(zf.read("Metadata/project_settings.config"))
    assert project["printable_area"] == ["0x0", "250x0", "250x2000", "0x2000"]
    assert project["printable_height"] == "250"


def test_placement_keeps_the_spacing_between_several_objects(tmp_path):
    src = _write_project(tmp_path)
    dst = tmp_path / "placed.3mf"
    write_derived_3mf(src, dst, excluded={2, 3}, placement=(100.0, 100.0))
    a, b = list_objects(dst)
    assert (b.center_x_mm - a.center_x_mm, b.center_y_mm - a.center_y_mm) == (72.5, 17.5)  # unchanged from the file
    group_centre_x = ((a.center_x_mm - a.width_mm / 2) + (b.center_x_mm + b.width_mm / 2)) / 2
    assert round(group_centre_x, 3) == 100.0


def test_project_settings_are_updated_not_replaced(tmp_path):
    src = _write_project(tmp_path)
    with zipfile.ZipFile(src, "a") as zf:
        zf.writestr("Metadata/project_settings.config", json.dumps({"layer_height": "0.2", "printable_area": ["0x0", "200x0", "200x200", "0x200"]}))
    dst = tmp_path / "out.3mf"
    write_derived_3mf(src, dst, excluded=set(), bed_area=["0x0", "300x0", "300x300", "0x300"], bed_height=300.0)
    with zipfile.ZipFile(dst) as zf:
        project = json.loads(zf.read("Metadata/project_settings.config"))
    assert project["layer_height"] == "0.2" and project["printable_area"][1] == "300x0"


def test_copies_repeat_the_selection_in_a_row(tmp_path):
    src = _write_project(tmp_path)
    dst = tmp_path / "c.3mf"
    write_derived_3mf(src, dst, excluded={1, 2, 3}, order=[], gap_mm=10, center_x=125, copies=3)
    objs = list_objects(dst)
    assert len(objs) == 3 and {o.plate for o in objs} == {1}
    assert [o.center_y_mm for o in objs] == [10.0, 40.0, 70.0]  # Block A is 20 deep: 0..20, 30..50, 60..80
    assert {o.center_x_mm for o in objs} == {125.0}
    with zipfile.ZipFile(dst) as zf:
        cfg = ET.fromstring(zf.read("Metadata/model_settings.config"))
    ids = [
        next(m.get("value") for m in inst.findall("metadata") if m.get("key") == "instance_id")
        for inst in cfg.find("plate").findall("model_instance")
    ]
    assert ids == ["0", "1", "2"]  # numbered per object


def test_copies_of_a_selection_repeat_the_whole_set(tmp_path):
    src = _write_project(tmp_path)
    dst = tmp_path / "c.3mf"
    kept = write_derived_3mf(src, dst, excluded={2, 3}, order=[1, 0], copies=2, gap_mm=5, center_x=100)
    assert kept == [1, 0]
    names = [o.name for o in list_objects(dst)]
    assert names == ["Tall B", "Block A", "Tall B", "Block A"]


def test_copies_without_a_row_stay_stacked_and_get_their_own_uuid(tmp_path):
    prod = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
    root = (
        f'<?xml version="1.0"?><model unit="millimeter" {_NS} xmlns:p="{prod}"><resources>'
        f'<object id="1" type="model">{_mesh(10, 10, 10)}</object></resources>'
        '<build><item objectid="1" p:UUID="aaaaaaaa-0000-0000-0000-000000000001" transform="1 0 0 0 1 0 0 0 1 50 50 0" printable="1"/></build></model>'
    )
    path = tmp_path / "u.3mf"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("3D/3dmodel.model", root)
    out = tmp_path / "o.3mf"
    write_derived_3mf(path, out, excluded=set(), copies=3)
    objs = list_objects(out)
    assert len(objs) == 3 and {(o.center_x_mm, o.center_y_mm) for o in objs} == {(55.0, 55.0)}
    with zipfile.ZipFile(out) as zf:
        uuids = re.findall(r'p:UUID="([^"]*)"', zf.read("3D/3dmodel.model").decode())
    assert len(uuids) == 3 and len(set(uuids)) == 3 and uuids[0] == "aaaaaaaa-0000-0000-0000-000000000001"
