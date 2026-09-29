import json
import zipfile
from pathlib import Path

from app.threemf import (
    _decode_paint_color_states,
    _representative_extruder,
    inspect_3mf,
    read_project_scalar_settings,
)

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


def test_read_project_scalar_settings_keeps_only_string_values(tmp_path: Path):
    # Real-world shape (a downloaded "bee+multicolor.3mf") that failed to
    # slice with "Invalid parameter value(s) included in the 3mf file":
    # raft_first_layer_expansion was baked in as "-1", outside the engine's
    # own declared [0, inf) range for that key, even though this file's
    # raft_layers ("0") meant the value was never actually going to matter.
    project_settings = json.dumps(
        {
            "raft_first_layer_expansion": "-1",
            "raft_layers": "0",
            "filament_colour": ["#000000", "#FFFF00"],  # list -- not a scalar, must be dropped
        }
    )
    path = _write_3mf(tmp_path, "bee_multicolor.3mf", model_settings=None, project_settings=project_settings)
    result = read_project_scalar_settings(path)
    assert result == {"raft_first_layer_expansion": "-1", "raft_layers": "0"}


def test_read_project_scalar_settings_missing_file_gives_empty_dict(tmp_path: Path):
    path = _write_3mf(tmp_path, "no_project_settings.3mf", model_settings="<config/>")
    assert read_project_scalar_settings(path) == {}


def test_read_project_scalar_settings_malformed_json_gives_empty_dict(tmp_path: Path):
    path = _write_3mf(
        tmp_path, "malformed.3mf", model_settings=None, project_settings="{not valid json"
    )
    assert read_project_scalar_settings(path) == {}


def test_read_project_scalar_settings_not_a_zip_gives_empty_dict(tmp_path: Path):
    path = tmp_path / "not_a_zip.3mf"
    path.write_text("just some text, not a zip file at all")
    assert read_project_scalar_settings(path) == {}


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
    assert result.color_tree[0].extruder == 1
    assert result.color_tree[0].children == []
    assert result.color_tree[1].color == "#00FF00"
    assert result.color_tree[1].extruder == 2


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
    assert top.extruder is None
    assert len(top.children) == 2
    assert top.children[0].color == "#0000FF"  # part 11 -> extruder 3
    assert top.children[0].extruder == 3
    assert top.children[1].color == "#FFFF00"  # part 12 -> extruder 4
    assert top.children[1].extruder == 4


def test_color_tree_part_without_own_extruder_inherits_object_extruder(tmp_path: Path):
    """Reproduces the exact shape confirmed against a real downloaded
    painted model: a single top-level composite object with exactly ONE
    part, where the author only ever set "extruder" once, at the object
    level -- the part itself carries no <metadata key="extruder"> at all
    (matching OrcaSlicer's own ModelVolume::extruder_id(), which falls
    back to the parent object's config the same way). Before this
    inheritance, the part's id had no entry in id_extruders at all, so
    this leaf's color/extruder silently resolved to None -- the 3D
    preview fell back to its flat default color instead of the file's
    real (single, in this case) assigned color."""
    root_model = """
    <resources>
      <object id="2" type="model">
        <components>
          <component objectid="1"/>
        </components>
      </object>
    </resources>
    <build>
      <item objectid="2"/>
    </build>
    """
    sub_model = """
    <resources><object id="1" type="model"><mesh/></object></resources>
    <build/>
    """
    model_settings = """
    <config>
      <object id="2">
        <metadata key="extruder" value="1"/>
        <part id="1" subtype="normal_part">
          <metadata key="name" value="part.stl"/>
        </part>
      </object>
      <plate><metadata key="plater_id" value="1"/></plate>
    </config>
    """
    project_settings = json.dumps({"filament_colour": ["#000000", "#FFFF00"]})
    path = _write_3mf_with_parts(
        tmp_path,
        "single_part_inherits.3mf",
        root_model=root_model,
        model_settings=model_settings,
        project_settings=project_settings,
        extra_parts={"object_1.model": sub_model},
    )
    result = inspect_3mf(path)
    assert len(result.color_tree) == 1
    top = result.color_tree[0]
    assert top.color is None  # composite -- color lives on its one part
    assert len(top.children) == 1
    assert top.children[0].color == "#000000"  # inherited object's extruder 1
    assert top.children[0].extruder == 1


def test_color_tree_leaf_extruder_out_of_range_is_omitted(tmp_path: Path):
    """An extruder index with no corresponding embedded_filament_colors
    entry (e.g. the file references extruder 5 but only 2 colors were
    saved) must not expose a bogus/out-of-bounds index for the frontend to
    look up -- both color and extruder stay None for that leaf."""
    root_model = """
    <resources><object id="1" type="model"><mesh/></object></resources>
    <build><item objectid="1"/></build>
    """
    model_settings = """
    <config>
      <object id="1"><metadata key="extruder" value="5"/></object>
      <plate><metadata key="plater_id" value="1"/></plate>
    </config>
    """
    project_settings = json.dumps({"filament_colour": ["#FF0000", "#00FF00"]})
    path = _write_3mf_with_parts(
        tmp_path,
        "out_of_range.3mf",
        root_model=root_model,
        model_settings=model_settings,
        project_settings=project_settings,
    )
    result = inspect_3mf(path)
    assert len(result.color_tree) == 1
    assert result.color_tree[0].color is None
    assert result.color_tree[0].extruder is None


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


# -- per-triangle paint decoding -------------------------------------------
# Ground truth taken directly from vendor/orcaslicer's own Catch2 tests
# (tests/libslic3r/test_triangle_selector.cpp) and its CONST_FILAMENTS
# table (Model.cpp:54-57) -- these are OrcaSlicer's own confirmed
# hex-string <-> state mappings, not values we derived ourselves.

# From test_triangle_selector.cpp's parameterized leaf-state case.
_ORCA_TEST_VECTORS = [
    ("8", 2),
    ("0C", 3),
    ("DC", 16),
    ("EC", 17),
    ("0FC", 18),
    ("EFC", 32),
]

# CONST_FILAMENTS[k] (index 0 unused) is the paint_color string OrcaSlicer
# itself writes for a whole, unsplit object assigned to extruder k, for
# every k from 1 to 32.
_CONST_FILAMENTS = [
    "", "4", "8", "0C", "1C", "2C", "3C", "4C", "5C", "6C", "7C", "8C", "9C", "AC", "BC", "CC", "DC",
    "EC", "0FC", "1FC", "2FC", "3FC", "4FC", "5FC", "6FC", "7FC", "8FC", "9FC", "AFC", "BFC", "CFC", "DFC", "EFC",
]


def test_decode_paint_color_matches_orca_test_vectors():
    for hex_str, expected_state in _ORCA_TEST_VECTORS:
        assert _decode_paint_color_states(hex_str) == [expected_state]
        assert _representative_extruder(hex_str) == expected_state


def test_decode_paint_color_matches_const_filaments_table():
    for extruder, hex_str in enumerate(_CONST_FILAMENTS):
        if extruder == 0:
            continue  # index 0 is unused ("" -- not a real vector)
        assert _decode_paint_color_states(hex_str) == [extruder]
        assert _representative_extruder(hex_str) == extruder


def _hex_from_decode_order_nibbles(nibbles: list[int]) -> str:
    """Builds a paint_color wire string from a list of 4-bit nibbles given
    in DECODE order (the order _decode_paint_color_states's recursive
    descent will read them) -- the inverse of the reverse-string/LSB-first
    packing _decode_paint_color_states itself undoes, so a test can spell
    out "here's the tree I want to decode" directly instead of hand-deriving
    hex digits."""
    return "".join(f"{n:x}" for n in nibbles)[::-1]


def test_decode_paint_color_handles_a_split_node():
    """Hand-constructed: a split into 2 children (num_split_sides=1,
    special_side=0 -> nibble 0b0001=0x1), first child leaf state 1
    (nibble 0b0100=0x4), second child leaf state 2 (nibble 0b1000=0x8).
    Confirms the recursive-split branch, not just single-leaf strings."""
    hex_str = _hex_from_decode_order_nibbles([0x1, 0x4, 0x8])
    assert hex_str == "841"
    assert _decode_paint_color_states(hex_str) == [1, 2]
    # Equal counts (one leaf each) -> ties broken by first-encountered.
    assert _representative_extruder(hex_str) == 1


def test_decode_paint_color_majority_vote():
    """3 children (num_split_sides=2, special_side=0 -> nibble 0b0010=0x2),
    states [1, 1, 2] -- majority (2 of 3) should win regardless of order."""
    hex_str = _hex_from_decode_order_nibbles([0x2, 0x4, 0x4, 0x8])
    assert _decode_paint_color_states(hex_str) == [1, 1, 2]
    assert _representative_extruder(hex_str) == 1


def test_decode_paint_color_all_none_has_no_representative():
    # A single leaf, state 0 (NONE) -- nibble 0b0000 = 0x0.
    hex_str = _hex_from_decode_order_nibbles([0x0])
    assert _decode_paint_color_states(hex_str) == [0]
    assert _representative_extruder(hex_str) is None


def test_decode_paint_color_empty_string_has_no_representative():
    assert _decode_paint_color_states("") == []
    assert _representative_extruder("") is None


def test_color_tree_leaf_gets_triangle_colors_from_paint_data(tmp_path: Path):
    """A single part with two painted triangles (extruder 2) and one
    unpainted triangle (no paint_color attribute at all) -- confirms
    triangle_extruders/triangle_colors come out the right shape/order,
    resolved the same way the leaf's own singular color/extruder are,
    and that an unpainted triangle resolves to None (falls back to the
    leaf's own base color on the frontend)."""
    root_model = """
    <resources>
      <object id="2" type="model">
        <mesh>
          <vertices>
            <vertex x="0" y="0" z="0"/>
            <vertex x="1" y="0" z="0"/>
            <vertex x="0" y="1" z="0"/>
            <vertex x="0" y="0" z="1"/>
          </vertices>
          <triangles>
            <triangle v1="0" v2="1" v3="2" paint_color="8"/>
            <triangle v1="0" v2="1" v3="3"/>
            <triangle v1="1" v2="2" v3="3" paint_color="8"/>
          </triangles>
        </mesh>
      </object>
    </resources>
    <build>
      <item objectid="2"/>
    </build>
    """
    model_settings = """
    <config>
      <object id="2"><metadata key="extruder" value="1"/></object>
      <plate><metadata key="plater_id" value="1"/></plate>
    </config>
    """
    project_settings = json.dumps({"filament_colour": ["#000000", "#FFFF00"]})
    path = _write_3mf_with_parts(
        tmp_path,
        "painted_leaf.3mf",
        root_model=root_model,
        model_settings=model_settings,
        project_settings=project_settings,
    )
    result = inspect_3mf(path)
    assert len(result.color_tree) == 1
    leaf = result.color_tree[0]
    assert leaf.color == "#000000"  # base extruder 1
    assert leaf.extruder == 1
    assert leaf.triangle_extruders == [2, None, 2]
    assert leaf.triangle_colors == ["#FFFF00", None, "#FFFF00"]


def test_color_tree_leaf_without_paint_has_no_triangle_colors(tmp_path: Path):
    """A leaf with no paint_color attributes at all keeps
    triangle_extruders/triangle_colors as None (not an all-None list) --
    the common, unpainted case shouldn't bloat the payload."""
    root_model = """
    <resources>
      <object id="2" type="model">
        <mesh>
          <vertices>
            <vertex x="0" y="0" z="0"/>
            <vertex x="1" y="0" z="0"/>
            <vertex x="0" y="1" z="0"/>
          </vertices>
          <triangles>
            <triangle v1="0" v2="1" v3="2"/>
          </triangles>
        </mesh>
      </object>
    </resources>
    <build>
      <item objectid="2"/>
    </build>
    """
    model_settings = """
    <config>
      <object id="2"><metadata key="extruder" value="1"/></object>
      <plate><metadata key="plater_id" value="1"/></plate>
    </config>
    """
    project_settings = json.dumps({"filament_colour": ["#000000"]})
    path = _write_3mf_with_parts(
        tmp_path,
        "unpainted_leaf.3mf",
        root_model=root_model,
        model_settings=model_settings,
        project_settings=project_settings,
    )
    result = inspect_3mf(path)
    assert len(result.color_tree) == 1
    leaf = result.color_tree[0]
    assert leaf.triangle_extruders is None
    assert leaf.triangle_colors is None


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
