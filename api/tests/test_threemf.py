import zipfile
from pathlib import Path

from app.threemf import inspect_3mf

_MODEL_SETTINGS_PATH = "Metadata/model_settings.config"


def _write_3mf(tmp_path: Path, name: str, model_settings: str | None) -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("3D/3dmodel.model", "<model/>")  # minimal, never actually read
        if model_settings is not None:
            zf.writestr(_MODEL_SETTINGS_PATH, model_settings)
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
