"""A Klipper printer's own config, read through Moonraker, turned into the "New printer" form.

The U1 fixture is a trimmed copy of a real response (a corexy toolchanger whose travel is bigger than its bed). The other
cases are small hand-made configs, one rule each.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.klipper_import import KlipperImportError, import_from_klipper
from app.schemas import PrinterForm
from app.userprofiles import build_printer_overrides

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "klipper_u1.json").read_text())


def _u1():
    return import_from_klipper(FIXTURE["info"], FIXTURE["settings"], FIXTURE["objects"])


def _cartesian(**sections):
    """A small cartesian printer with the sections given added to (or replacing) the basics."""
    settings = {
        "printer": {"kinematics": "cartesian", "max_velocity": 300, "max_accel": 3000},
        "stepper_x": {"position_min": 0, "position_max": 235},
        "stepper_y": {"position_min": 0, "position_max": 230},
        "stepper_z": {"position_min": 0, "position_max": 250},
        "extruder": {"nozzle_diameter": 0.4},
    }
    settings.update(sections)
    return import_from_klipper({"hostname": "voron", "state": "ready"}, settings, [])


def _notes(result):
    return " ".join(result["notes"])


# ---- the basics, from the real printer ----


def test_a_real_toolchanger_gives_the_bed_speeds_and_nozzle():
    form = _u1()["form"]
    assert form["gcode_flavor"] == "klipper"
    assert form["shape"] == "rectangle"
    assert (form["width"], form["depth"], form["height"]) == (271, 335, 275)
    assert (form["origin_x"], form["origin_y"], form["origin_centre"]) == (0, 0, False)
    assert form["nozzle_diameter"] == 0.4
    assert form["max_speed"] == 500
    assert form["max_acceleration"] == 20000


def test_the_name_suggested_is_the_printers_hostname():
    assert _u1()["form"]["name"] == "lava"
    assert _u1()["klipper"] == {"hostname": "lava", "version": "1.5.2.13_20260722102206", "state": "ready"}


def test_the_form_it_makes_is_one_the_printer_form_and_its_builder_accept():
    form = _u1()["form"]
    PrinterForm(**form)
    overrides = build_printer_overrides({}, {k: v for k, v in form.items() if k != "name"})
    assert overrides["printable_height"] == "275"
    assert overrides["gcode_flavor"] == "klipper"


def test_every_value_it_reads_says_where_it_came_from():
    result = _u1()
    by_field = {f["field"]: f for f in result["findings"]}
    for field in ("width", "depth", "height", "nozzle_diameter", "max_speed", "max_acceleration"):
        assert by_field[field]["source"], field
    assert "stepper_x" in by_field["width"]["source"]
    assert "stepper_z" in by_field["height"]["source"]
    assert by_field["max_acceleration"]["value"] == 20000


# ---- what to check (the part a printer's config cannot say for itself) ----


def test_travel_bigger_than_the_bed_mesh_is_flagged_with_both_numbers():
    notes = _notes(_u1())
    assert "335" in notes and "267" in notes  # Y travel against where the bed mesh reaches
    assert "check" in notes.lower()


def test_a_bed_mesh_that_covers_the_travel_raises_no_such_note():
    result = _cartesian(bed_mesh={"mesh_min": [10, 10], "mesh_max": [225, 220]})
    assert "bed mesh" not in _notes(result).lower()


def test_several_extruders_are_said_and_the_first_ones_nozzle_is_used():
    notes = _notes(_u1())
    assert "4 extruders" in notes


def test_extruders_with_different_nozzles_say_so():
    result = _cartesian(extruder={"nozzle_diameter": 0.6}, extruder1={"nozzle_diameter": 0.4})
    assert result["form"]["nozzle_diameter"] == 0.6
    assert "0.4" in _notes(result) and "0.6" in _notes(result)


# ---- the bed ----


def test_a_bed_centred_on_the_origin_is_said_to_be_centred():
    result = _cartesian(
        stepper_x={"position_min": -110, "position_max": 110}, stepper_y={"position_min": -110, "position_max": 110}
    )
    form = result["form"]
    assert (form["width"], form["depth"], form["origin_centre"]) == (220, 220, True)


def test_a_bed_that_starts_below_zero_keeps_its_offset():
    result = _cartesian(stepper_x={"position_min": -5, "position_max": 230})
    form = result["form"]
    assert (form["width"], form["origin_x"], form["origin_centre"]) == (235, -5, False)


def test_a_delta_is_a_round_bed_centred_on_the_origin():
    settings = {
        "printer": {"kinematics": "delta", "print_radius": 120, "max_velocity": 200, "max_accel": 2000},
        "stepper_a": {"position_endstop": 310},
        "extruder": {"nozzle_diameter": 0.4},
    }
    form = import_from_klipper({"hostname": "delta", "state": "ready"}, settings, [])["form"]
    assert form["shape"] == "circle"
    assert (form["width"], form["origin_centre"]) == (240, True)
    assert form["height"] == 310


def test_kinematics_it_cannot_draw_a_bed_for_are_refused_by_name():
    with pytest.raises(KlipperImportError, match="polar"):
        import_from_klipper({"state": "ready"}, {"printer": {"kinematics": "polar"}, "extruder": {}}, [])


def test_a_config_with_no_stepper_for_an_axis_is_refused_by_name():
    with pytest.raises(KlipperImportError, match="stepper_y"):
        import_from_klipper(
            {"state": "ready"},
            {
                "printer": {"kinematics": "cartesian"},
                "stepper_x": {"position_max": 200},
                "stepper_z": {"position_max": 200},
            },
            [],
        )


# ---- the start and end macros ----


def test_a_start_macro_that_takes_temperatures_gets_a_start_line_that_passes_them():
    macro = "{% set BED = params.BED_TEMP|default(60)|float %}\n{% set T = params.EXTRUDER_TEMP|default(200)|float %}\nM190 S{BED}"
    result = _cartesian(**{"gcode_macro start_print": {"gcode": macro}})
    assert result["form"]["start_gcode"] == (
        "START_PRINT BED_TEMP=[bed_temperature_initial_layer_single] EXTRUDER_TEMP=[nozzle_temperature_initial_layer]"
    )


def test_the_other_common_macro_name_and_spellings_of_the_parameters_are_found():
    macro = (
        "{% set b = params.BED|float %}{% set n = params.HOTEND_TEMP|float %}{% set c = params.CHAMBER_TEMP|float %}"
    )
    result = _cartesian(**{"gcode_macro print_start": {"gcode": macro}})
    assert result["form"]["start_gcode"] == (
        "PRINT_START BED=[bed_temperature_initial_layer_single] HOTEND_TEMP=[nozzle_temperature_initial_layer] CHAMBER_TEMP=[chamber_temperature]"
    )


def test_a_parameter_it_does_not_know_is_left_out_and_named():
    macro = "{% set b = params.BED_TEMP|float %}{% set m = params.MATERIAL|default('PLA') %}"
    result = _cartesian(**{"gcode_macro start_print": {"gcode": macro}})
    assert "MATERIAL" not in result["form"]["start_gcode"]
    assert "MATERIAL" in _notes(result)


def test_a_start_macro_that_takes_no_temperatures_is_not_guessed_at():
    result = _u1()
    assert "start_gcode" not in result["form"]
    assert "print_start" in _notes(result).lower()


def test_an_end_macro_becomes_the_end_line():
    assert _u1()["form"]["end_gcode"] == "PRINT_END"


def test_no_macros_leave_the_start_and_end_to_the_base_printer():
    form = _cartesian()["form"]
    assert "start_gcode" not in form and "end_gcode" not in form


def test_a_macros_own_code_is_never_sent_on():
    text = json.dumps(_u1())
    assert "SM_PRINT_START_LINE" not in text
    assert "FLOW_APPLY_CALIBRATE_K" not in text


# ---- retraction and object exclusion ----


def test_firmware_retraction_is_read_and_switched_on():
    result = _cartesian(firmware_retraction={"retract_length": 1.2, "retract_speed": 35})
    form = result["form"]
    assert (form["retraction_length"], form["retraction_speed"]) == (1.2, 35)
    assert form["advanced"]["use_firmware_retraction"] == "1"


def test_without_firmware_retraction_nothing_about_retraction_is_set():
    form = _cartesian()["form"]
    assert "retraction_length" not in form
    assert "use_firmware_retraction" not in form["advanced"]


def test_a_printer_that_can_exclude_objects_gets_it_switched_on():
    assert _u1()["form"]["advanced"]["exclude_object"] == "1"
    assert "exclude_object" not in _cartesian()["form"]["advanced"]
