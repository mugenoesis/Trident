"""A Bambu printer's status report (what it publishes on MQTT in LAN/Developer mode) made into what the printer page shows.

The reports below follow the community's documentation of the protocol (the field names and the states). The same shape comes out as for a
Klipper printer, so the one page shows both.
"""

from __future__ import annotations

from app.bambu_status import merge_report, status_from_bambu

X1C = "00M00A000000000"  # a serial number that starts like an X1 Carbon's
P1S = "01P00A000000000"  # ... like a P1S's


def _running(**overrides):
    base = {
        "gcode_state": "RUNNING",
        "subtask_name": "benchy",
        "gcode_file": "/data/Metadata/plate_1.gcode",
        "mc_percent": 42,
        "mc_remaining_time": 98,
        "layer_num": 118,
        "total_layer_num": 281,
        "nozzle_temper": 214.8,
        "nozzle_target_temper": 215,
        "bed_temper": 59.9,
        "bed_target_temper": 60,
        "chamber_temper": 31.4,
        "print_error": 0,
        "hms": [],
    }
    base.update(overrides)
    return base


def _names(status):
    return [t["name"] for t in status["temperatures"]]


# ---- a print under way ----


def test_a_print_under_way_has_everything_the_page_shows():
    status = status_from_bambu(_running(), X1C)
    assert status["state"] == "printing"
    assert status["file"] == "benchy"
    assert status["progress"] == 0.42
    assert status["layer"] == {"current": 118, "total": 281}
    assert status["remaining_s"] == 98 * 60  # the printer says minutes
    assert status["can"] == {"pause": True, "resume": False, "cancel": True}
    assert status["state_message"] == ""


def test_the_temperatures_are_the_nozzle_the_bed_and_an_x1s_chamber():
    status = status_from_bambu(_running(), X1C)
    assert _names(status) == ["Nozzle", "Bed", "Chamber"]
    assert status["temperatures"][0] == {"name": "Nozzle", "kind": "nozzle", "current": 214.8, "target": 215}
    assert status["temperatures"][2] == {"name": "Chamber", "kind": "chamber", "current": 31.4, "target": None}


def test_a_printer_with_no_chamber_sensor_shows_no_chamber():
    # a P1S reports a chamber figure that is not a measurement
    assert _names(status_from_bambu(_running(chamber_temper=5), P1S)) == ["Nozzle", "Bed"]
    assert _names(status_from_bambu(_running(), "")) == ["Nozzle", "Bed"]


def test_the_file_is_the_prints_name_or_else_the_gcode_files():
    assert status_from_bambu(_running(subtask_name=""), X1C)["file"] == "plate_1.gcode"
    assert status_from_bambu(_running(subtask_name="", gcode_file=""), X1C)["file"] is None


def test_no_time_left_is_shown_for_a_print_that_is_not_under_way():
    assert status_from_bambu(_running(gcode_state="PAUSE"), X1C)["remaining_s"] is None


# ---- the other states ----


def test_a_paused_print_can_be_resumed_or_cancelled():
    status = status_from_bambu(_running(gcode_state="PAUSE"), X1C)
    assert status["state"] == "paused"
    assert status["can"] == {"pause": False, "resume": True, "cancel": True}


def test_a_printer_getting_ready_counts_as_printing_and_can_be_stopped():
    status = status_from_bambu(_running(gcode_state="PREPARE", mc_percent=0), X1C)
    assert status["state"] == "printing"
    assert status["can"]["cancel"] is True


def test_a_finished_print_is_complete_at_a_hundred_percent():
    status = status_from_bambu(_running(gcode_state="FINISH", mc_percent=100, mc_remaining_time=0), X1C)
    assert status["state"] == "complete"
    assert status["progress"] == 1
    assert status["can"] == {"pause": False, "resume": False, "cancel": False}


def test_an_idle_printer_has_no_file_and_no_progress():
    status = status_from_bambu(_running(gcode_state="IDLE", mc_percent=0), X1C)
    assert status["state"] == "standby"
    assert status["file"] is None
    assert status["progress"] is None
    assert status["layer"] is None


def test_a_failed_print_is_an_error():
    status = status_from_bambu(_running(gcode_state="FAILED"), X1C)
    assert status["state"] == "error"
    assert status["can"] == {"pause": False, "resume": False, "cancel": False}


def test_an_error_code_is_passed_on_so_it_can_be_looked_up():
    status = status_from_bambu(_running(gcode_state="PAUSE", print_error=0x0300400C), X1C)
    assert "0300_400C" in status["state_message"]
    status = status_from_bambu(_running(hms=[{"attr": 0x03000100, "code": 0x00020001}]), X1C)
    assert "0300_0100_0002_0001" in status["state_message"]


def test_an_unknown_state_is_passed_on_as_it_is():
    assert status_from_bambu(_running(gcode_state="SLICING"), X1C)["state"] == "slicing"


# ---- odd reports ----


def test_progress_is_kept_between_nothing_and_everything():
    assert status_from_bambu(_running(mc_percent=140), X1C)["progress"] == 1
    assert status_from_bambu(_running(mc_percent=-3), X1C)["progress"] == 0


def test_a_report_with_nothing_in_it_is_an_idle_printer():
    status = status_from_bambu({}, X1C)
    assert status["state"] == "standby"
    assert status["temperatures"] == []


def test_the_same_fields_come_out_as_for_a_klipper_printer():
    assert set(status_from_bambu(_running(), X1C)) == {
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


# ---- a P1 or A1 sends only what changed ----


def test_a_report_with_only_what_changed_is_laid_over_what_is_known():
    known = _running()
    merged = merge_report(known, {"mc_percent": 43, "nozzle_temper": 215.1})
    assert merged["mc_percent"] == 43
    assert merged["nozzle_temper"] == 215.1
    assert merged["subtask_name"] == "benchy"  # kept from before
    assert known["mc_percent"] == 42  # the old report is not changed
