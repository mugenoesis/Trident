"""A Klipper printer's status (print state, progress, temperatures) as Moonraker reports it, made into what the printer page shows.

The U1 fixture is a trimmed copy of a real response from a four-nozzle toolchanger that had just finished a print.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.klipper_status import status_from_klipper

U1 = json.loads((Path(__file__).parent / "fixtures" / "klipper_u1_status.json").read_text())


def _names(status):
    return [t["name"] for t in status["temperatures"]]


def _temp(status, name):
    return next(t for t in status["temperatures"] if t["name"] == name)


def _printing(**overrides):
    base = {
        "print_stats": {
            "state": "printing",
            "filename": "part.gcode",
            "print_duration": 600,
            "info": {"current_layer": 12, "total_layer": 80},
        },
        "virtual_sdcard": {"progress": 0.25},
        "extruder": {"temperature": 214.6, "target": 215},
        "heater_bed": {"temperature": 59.96, "target": 60},
    }
    base.update(overrides)
    return base


# ---- a real printer that has just finished ----


def test_a_finished_print_says_so_with_the_file_and_the_layers():
    status = status_from_klipper(U1)
    assert status["state"] == "complete"
    assert status["file"] == "plate_1.gcode"
    assert status["progress"] == 1
    assert status["layer"] == {"current": 99, "total": 99}
    assert status["elapsed_s"] == 6485
    assert status["remaining_s"] is None
    assert status["can"] == {"pause": False, "resume": False, "cancel": False}


def test_several_nozzles_are_numbered_and_the_bed_and_the_chamber_follow():
    status = status_from_klipper(U1)
    assert _names(status) == ["Nozzle 1", "Nozzle 2", "Nozzle 3", "Nozzle 4", "Bed", "Chamber"]
    assert _temp(status, "Nozzle 2") == {"name": "Nozzle 2", "kind": "nozzle", "current": 16, "target": 0}
    assert _temp(status, "Bed") == {"name": "Bed", "kind": "bed", "current": 14, "target": 0}
    assert _temp(status, "Chamber") == {"name": "Chamber", "kind": "chamber", "current": 17, "target": None}


# ---- while printing ----


def test_a_print_under_way_has_progress_layers_and_a_time_left():
    status = status_from_klipper(_printing())
    assert status["state"] == "printing"
    assert status["progress"] == 0.25
    assert status["layer"] == {"current": 12, "total": 80}
    assert status["elapsed_s"] == 600
    assert status["remaining_s"] == 1800  # a quarter done in 600 s: three times as long again
    assert status["can"] == {"pause": True, "resume": False, "cancel": True}


def test_no_time_left_is_guessed_at_the_very_start():
    status = status_from_klipper(_printing(virtual_sdcard={"progress": 0.002}))
    assert status["remaining_s"] is None


def test_a_paused_print_can_be_resumed_or_cancelled_and_has_no_time_left():
    status = status_from_klipper(
        _printing(print_stats={"state": "paused", "filename": "part.gcode", "print_duration": 600})
    )
    assert status["state"] == "paused"
    assert status["can"] == {"pause": False, "resume": True, "cancel": True}
    assert status["remaining_s"] is None


def test_without_layer_information_there_are_no_layers():
    status = status_from_klipper(
        _printing(
            print_stats={
                "state": "printing",
                "filename": "part.gcode",
                "print_duration": 60,
                "info": {"current_layer": None, "total_layer": None},
            }
        )
    )
    assert status["layer"] is None


# ---- idle, and things going wrong ----


def test_an_idle_printer_has_no_file_and_no_progress():
    status = status_from_klipper(
        {"print_stats": {"state": "standby", "filename": ""}, "virtual_sdcard": {"progress": 0}}
    )
    assert status["state"] == "standby"
    assert status["file"] is None
    assert status["progress"] is None
    assert status["layer"] is None


def test_an_error_carries_the_printers_own_message():
    status = status_from_klipper(
        {
            "print_stats": {
                "state": "error",
                "filename": "part.gcode",
                "message": "Heater extruder not heating at expected rate",
            }
        }
    )
    assert status["state"] == "error"
    assert status["state_message"] == "Heater extruder not heating at expected rate"


def test_a_klipper_that_has_shut_down_says_so_whatever_the_print_state_was():
    status = status_from_klipper(
        {
            "print_stats": {"state": "printing"},
            "webhooks": {"state": "shutdown", "state_message": "MCU 'mcu' shutdown: Timer too close"},
        }
    )
    assert status["state"] == "shutdown"
    assert status["state_message"] == "MCU 'mcu' shutdown: Timer too close"
    assert status["can"] == {"pause": False, "resume": False, "cancel": False}


def test_a_printer_that_reports_nothing_is_idle_with_nothing_to_show():
    status = status_from_klipper({})
    assert status["state"] == "standby"
    assert status["temperatures"] == []
    assert status["file"] is None


# ---- temperatures ----


def test_one_nozzle_is_just_the_nozzle_and_temperatures_are_rounded():
    status = status_from_klipper(_printing())
    assert _names(status) == ["Nozzle", "Bed"]
    assert _temp(status, "Nozzle")["current"] == 214.6
    assert _temp(status, "Bed")["current"] == 60


def test_other_heaters_and_sensors_come_after_with_their_own_names():
    status = status_from_klipper(
        {
            "heater_bed": {"temperature": 30, "target": 0},
            "extruder": {"temperature": 25, "target": 0},
            "heater_generic chamber_heater": {"temperature": 40, "target": 45},
            "temperature_sensor raspberry_pi": {"temperature": 51.2},
            "temperature_sensor chamber": {"temperature": 38},
        }
    )
    assert _names(status) == ["Nozzle", "Bed", "chamber_heater", "Chamber", "raspberry_pi"]
    assert _temp(status, "chamber_heater")["kind"] == "heater"
    assert _temp(status, "chamber_heater")["target"] == 45
    assert _temp(status, "raspberry_pi")["kind"] == "sensor"


def test_only_what_the_page_shows_is_sent_on():
    text = json.dumps(status_from_klipper(U1))
    assert "power" not in text
    assert set(status_from_klipper(U1)) == {
        "state",
        "state_message",
        "file",
        "progress",
        "layer",
        "elapsed_s",
        "remaining_s",
        "temperatures",
        "can",
    }
