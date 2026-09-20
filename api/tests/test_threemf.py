import json
import zipfile
from pathlib import Path

from app.threemf import inspect_3mf

_MODEL_SETTINGS_PATH = "Metadata/model_settings.config"
_PROJECT_SETTINGS_PATH = "Metadata/project_settings.config"


def _write_3mf(
    tmp_path: Path,
    name: str,
    model_settings: str | None,
    project_settings: str | None = None,
) -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("3D/3dmodel.model", "<model/>")  # minimal, never actually read
        if model_settings is not None:
            zf.writestr(_MODEL_SETTINGS_PATH, model_settings)
        if project_settings is not None:
            zf.writestr(_PROJECT_SETTINGS_PATH, project_settings)
    return path


_NS = 'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"'


def _write_3mf_with_parts(
    tmp_path: Path,
    name: str,
    *,
    root_model: str,
    model_settings: str | None = None,
    project_settings: str | None = None,
    extra_parts: dict[str, str] | None = None,
) -> Path:
    """Like _write_3mf, but with a real (namespaced) 3D/3dmodel.model
    body, plus optional Production-Extension sub-part .model files at
    3D/Objects/<key> -- for color_tree tests, which need genuine <object>/
    <components>/<build> structure, not the "<model/>" placeholder above.
    """
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("3D/3dmodel.model", f"<model {_NS}>{root_model}</model>")
        for filename, body in (extra_parts or {}).items():
            zf.writestr(f"3D/Objects/{filename}", f"<model {_NS}>{body}</model>")
        if model_settings is not None:
            zf.writestr(_MODEL_SETTINGS_PATH, model_settings)
        if project_settings is not None:
            zf.writestr(_PROJECT_SETTINGS_PATH, project_settings)
    return path


def test_no_model_settings_config_falls_back_to_single_plate(tmp_path: Path):
    path = _write_3mf(tmp_path, "plain.3mf", model_settings=None)
    result = inspect_3mf(path)
    assert len(result.plates) == 1
    assert result.plates[0].index == 1
    assert result.plates[0].name is None
    assert result.plates[0].object_count is None
    assert result.plates[0].thumbnail is None
    assert result.extruder_indices == []


def test_malformed_xml_falls_back_to_single_plate(tmp_path: Path):
    path = _write_3mf(tmp_path, "malformed.3mf", model_settings="<config><plate not closed")
    result = inspect_3mf(path)
    assert len(result.plates) == 1
    assert result.plates[0].index == 1
    assert result.extruder_indices == []


def test_not_a_zip_at_all_falls_back_to_single_plate(tmp_path: Path):
    path = tmp_path / "garbage.3mf"
    path.write_bytes(b"this is not a zip file at all")
    result = inspect_3mf(path)
    assert len(result.plates) == 1
    assert result.plates[0].index == 1


def test_two_well_formed_plates_are_parsed(tmp_path: Path):
    xml = """
    <config>
      <plate>
        <metadata key="plater_id" value="1"/>
        <metadata key="plater_name" value="First plate"/>
        <metadata key="thumbnail_file" value="Metadata/plate_1.png"/>
        <model_instance><metadata key="object_id" value="2"/></model_instance>
      </plate>
      <plate>
        <metadata key="plater_id" value="2"/>
        <metadata key="plater_name" value="Second plate"/>
        <metadata key="thumbnail_file" value="Metadata/plate_2.png"/>
        <model_instance><metadata key="object_id" value="3"/></model_instance>
        <model_instance><metadata key="object_id" value="4"/></model_instance>
      </plate>
    </config>
    """
    path = _write_3mf(tmp_path, "multiplate.3mf", model_settings=xml)
    result = inspect_3mf(path)
    assert [p.index for p in result.plates] == [1, 2]
    assert [p.name for p in result.plates] == ["First plate", "Second plate"]
    assert [p.thumbnail for p in result.plates] == ["Metadata/plate_1.png", "Metadata/plate_2.png"]
    assert [p.object_count for p in result.plates] == [1, 2]


def test_distinct_extruder_assignments_are_collected(tmp_path: Path):
    xml = """
    <config>
      <object id="1">
        <metadata key="name" value="Body"/>
        <metadata key="extruder" value="1"/>
      </object>
      <object id="2">
        <metadata key="name" value="Logo"/>
        <metadata key="extruder" value="2"/>
      </object>
      <plate>
        <metadata key="plater_id" value="1"/>
      </plate>
    </config>
    """
    path = _write_3mf(tmp_path, "multimaterial.3mf", model_settings=xml)
    result = inspect_3mf(path)
    assert result.extruder_indices == [1, 2]


def test_zero_plate_elements_falls_back_to_single_implicit_plate(tmp_path: Path):
    xml = """
    <config>
      <object id="1">
        <metadata key="extruder" value="1"/>
      </object>
    </config>
    """
    path = _write_3mf(tmp_path, "no_plates.3mf", model_settings=xml)
    result = inspect_3mf(path)
    assert len(result.plates) == 1
    assert result.plates[0].index == 1
    assert result.extruder_indices == [1]


def test_embedded_filament_colors_parsed_from_project_settings(tmp_path: Path):
    project_settings = json.dumps({"filament_colour": ["#000000", "#FFFF00"]})
    path = _write_3mf(tmp_path, "colored.3mf", model_settings=None, project_settings=project_settings)
    result = inspect_3mf(path)
    assert result.embedded_filament_colors == ["#000000", "#FFFF00"]


def test_embedded_filament_names_parsed_from_project_settings(tmp_path: Path):
    project_settings = json.dumps(
        {
            "filament_colour": ["#000000", "#FFFF00"],
            "filament_settings_id": ["Bambu PLA Basic @BBL A1M", "Bambu PLA Basic @BBL A1M"],
        }
    )
    path = _write_3mf(tmp_path, "named.3mf", model_settings=None, project_settings=project_settings)
    result = inspect_3mf(path)
    assert result.embedded_filament_names == ["Bambu PLA Basic @BBL A1M", "Bambu PLA Basic @BBL A1M"]


def test_embedded_filament_names_empty_when_missing(tmp_path: Path):
    project_settings = json.dumps({"filament_colour": ["#000000"]})
    path = _write_3mf(tmp_path, "unnamed.3mf", model_settings=None, project_settings=project_settings)
    result = inspect_3mf(path)
    assert result.embedded_filament_names == []


def test_paint_on_color_scenario_regression(tmp_path: Path):
    """The exact real-world shape that crashed OrcaSlicer (exit code -11):
    a single object whose model_settings.config only assigns it to
    extruder 1 (per-object metadata has no idea about per-triangle paint
    data), while project_settings.config's filament_colour reveals the
    file genuinely uses 2 filament roles. embedded_filament_colors must
    surface that second role even though extruder_indices misses it --
    this is the whole reason project_settings.config is consulted at all.
    """
    model_settings = """
    <config>
      <object id="1">
        <metadata key="extruder" value="1"/>
      </object>
      <plate>
        <metadata key="plater_id" value="1"/>
      </plate>
    </config>
    """
    project_settings = json.dumps(
        {"filament_colour": ["#000000", "#FFFF00"], "default_filament_colour": ["", ""]}
    )
    path = _write_3mf(tmp_path, "bee.3mf", model_settings=model_settings, project_settings=project_settings)
    result = inspect_3mf(path)
    assert result.extruder_indices == [1]
    assert result.embedded_filament_colors == ["#000000", "#FFFF00"]


def test_missing_project_settings_config_gives_empty_embedded_colors(tmp_path: Path):
    path = _write_3mf(tmp_path, "no_project_settings.3mf", model_settings="<config/>")
    result = inspect_3mf(path)
    assert result.embedded_filament_colors == []


def test_malformed_project_settings_config_gives_empty_embedded_colors(tmp_path: Path):
    path = _write_3mf(
        tmp_path, "malformed_project_settings.3mf", model_settings=None, project_settings="{not valid json"
    )
    result = inspect_3mf(path)
    assert result.embedded_filament_colors == []


def test_non_list_filament_colour_gives_empty_embedded_colors(tmp_path: Path):
    project_settings = json.dumps({"filament_colour": "not-a-list"})
    path = _write_3mf(tmp_path, "odd.3mf", model_settings=None, project_settings=project_settings)
    result = inspect_3mf(path)
    assert result.embedded_filament_colors == []


def test_color_tree_for_two_simple_leaf_objects(tmp_path: Path):
    """Two independent top-level objects (no composites), each assigned a
    different extruder -- the simple case, one ColorNode per <build><item>,
    each a leaf with its own resolved color."""
    root_model = """
    <resources>
      <object id="1" type="model"><mesh/></object>
      <object id="2" type="model"><mesh/></object>
    </resources>
    <build>
      <item objectid="1"/>
      <item objectid="2"/>
    </build>
    """
    model_settings = """
    <config>
      <object id="1"><metadata key="extruder" value="1"/></object>
      <object id="2"><metadata key="extruder" value="2"/></object>
      <plate><metadata key="plater_id" value="1"/></plate>
    </config>
    """
    project_settings = json.dumps({"filament_colour": ["#FF0000", "#00FF00"]})
    path = _write_3mf_with_parts(
        tmp_path,
        "two_leaves.3mf",
        root_model=root_model,
        model_settings=model_settings,
        project_settings=project_settings,
    )
    result = inspect_3mf(path)
    assert len(result.color_tree) == 2
    assert result.color_tree[0].color == "#FF0000"
    assert result.color_tree[0].children == []
    assert result.color_tree[1].color == "#00FF00"


def test_color_tree_for_composite_object_matches_real_orca_badge_shape(tmp_path: Path):
    """Reproduces the exact shape confirmed against the real bundled
    OrcaBadge.3mf sample: a single top-level composite object referencing
    2 parts in a separate Production-Extension sub-.model file (linked via
    <component objectid="Y">, matching Metadata/model_settings.config's
    <part id="Y">), each part independently colored."""
    root_model = """
    <resources>
      <object id="10" type="model">
        <components>
          <component objectid="11"/>
          <component objectid="12"/>
        </components>
      </object>
    </resources>
    <build>
      <item objectid="10"/>
    </build>
    """
    sub_model = """
    <resources>
      <object id="11" type="model"><mesh/></object>
      <object id="12" type="model"><mesh/></object>
    </resources>
    <build/>
    """
    model_settings = """
    <config>
      <object id="10">
        <metadata key="extruder" value="1"/>
        <part id="11"><metadata key="extruder" value="3"/></part>
        <part id="12"><metadata key="extruder" value="4"/></part>
      </object>
      <plate><metadata key="plater_id" value="1"/></plate>
    </config>
    """
    project_settings = json.dumps(
        {"filament_colour": ["#000000", "#111111", "#0000FF", "#FFFF00"]}
    )
    path = _write_3mf_with_parts(
        tmp_path,
        "badge.3mf",
        root_model=root_model,
        model_settings=model_settings,
        project_settings=project_settings,
        extra_parts={"badge_parts.model": sub_model},
    )
    result = inspect_3mf(path)
    assert len(result.color_tree) == 1
    top = result.color_tree[0]
    assert top.color is None  # composite -- color lives on its parts, not itself
    assert len(top.children) == 2
    assert top.children[0].color == "#0000FF"  # part 11 -> extruder 3
    assert top.children[1].color == "#FFFF00"  # part 12 -> extruder 4


def test_color_tree_empty_without_embedded_filament_colors(tmp_path: Path):
    """Per-object extruder metadata alone (no project_settings.config)
    isn't enough to resolve real colors -- color_tree stays empty rather
    than guessing at colors that were never actually confirmed."""
    root_model = """
    <resources><object id="1" type="model"><mesh/></object></resources>
    <build><item objectid="1"/></build>
    """
    model_settings = """
    <config>
      <object id="1"><metadata key="extruder" value="1"/></object>
      <plate><metadata key="plater_id" value="1"/></plate>
    </config>
    """
    path = _write_3mf_with_parts(
        tmp_path, "no_colors.3mf", root_model=root_model, model_settings=model_settings
    )
    result = inspect_3mf(path)
    assert result.color_tree == []


def test_color_tree_empty_when_build_section_missing(tmp_path: Path):
    model_settings = """
    <config>
      <object id="1"><metadata key="extruder" value="1"/></object>
      <plate><metadata key="plater_id" value="1"/></plate>
    </config>
    """
    project_settings = json.dumps({"filament_colour": ["#FF0000"]})
    path = _write_3mf_with_parts(
        tmp_path,
        "no_build.3mf",
        root_model="<resources><object id=\"1\" type=\"model\"><mesh/></object></resources>",
        model_settings=model_settings,
        project_settings=project_settings,
    )
    result = inspect_3mf(path)
    assert result.color_tree == []
