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
