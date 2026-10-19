"""Reading a Klipper printer's live status, controlling the print, and its webcams, through Moonraker (what the printer page uses)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.printhost import PrintHostError, print_control, read_status, webcam_list, webcam_snapshot

BASE = "http://voron.local:7125"
OBJECTS = [
    "webhooks",
    "print_stats",
    "virtual_sdcard",
    "display_status",
    "toolhead",
    "extruder",
    "extruder1",
    "heater_bed",
    "heater_generic chamber_heater",
    "temperature_sensor cavity",
    "fan",
    "tmc2209 extruder",
    "gcode_macro START_PRINT",
]
STATUS = {"print_stats": {"state": "printing"}, "extruder": {"temperature": 200, "target": 210}}
CAMERAS = {
    "result": {
        "webcams": [
            {
                "name": "off",
                "enabled": False,
                "snapshot_url": "/webcam/?action=snapshot",
                "stream_url": "/webcam/?action=stream",
            },
            {
                "name": "tool",
                "enabled": True,
                "snapshot_url": "/webcam/?action=snapshot",
                "stream_url": "/webcam/?action=stream",
            },
            {
                "name": "far",
                "enabled": True,
                "snapshot_url": "http://cam.local:8080/snap.jpg",
                "stream_url": "http://cam.local:8080/stream",
            },
        ]
    }
}


def _printer(**overrides):
    base = {
        "host_type": "moonraker",
        "print_host": f"{BASE}/",
        "printhost_apikey": None,
        "printhost_user": None,
        "printhost_password": None,
    }
    base.update(overrides)
    return base


def _run(coro_fn, printer, handler, *args):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return asyncio.run(coro_fn(printer, *args, client=client))


def _moonraker(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/printer/objects/list":
        return httpx.Response(200, json={"result": {"objects": OBJECTS}})
    if path == "/printer/objects/query":
        return httpx.Response(200, json={"result": {"status": STATUS}})
    if path == "/server/webcams/list":
        return httpx.Response(200, json=CAMERAS)
    if path.startswith("/printer/print/") and request.method == "POST":
        return httpx.Response(200, json={"result": "ok"})
    if path == "/webcam/" or path == "/snap.jpg":
        return httpx.Response(200, content=b"\xff\xd8jpegbytes", headers={"content-type": "image/jpeg"})
    return httpx.Response(404)


# ---- the status ----


def test_it_asks_for_the_print_and_the_heaters_and_sensors_and_nothing_else():
    asked = []

    def handler(request):
        if request.url.path == "/printer/objects/query":
            asked.append(str(request.url))
        return _moonraker(request)

    assert _run(read_status, _printer(), handler) == STATUS
    query = asked[0]
    for wanted in (
        "print_stats",
        "virtual_sdcard",
        "webhooks",
        "heater_bed",
        "extruder1",
        "heater_generic%20chamber_heater",
        "temperature_sensor%20cavity",
    ):
        assert wanted in query, wanted
    for unwanted in ("fan", "tmc2209", "gcode_macro", "toolhead"):
        assert unwanted not in query, unwanted


def test_the_status_is_only_ever_read():
    methods = []

    def handler(request):
        methods.append(request.method)
        return _moonraker(request)

    _run(read_status, _printer(), handler)
    assert set(methods) == {"GET"}


def test_an_api_key_is_sent_with_every_request():
    keys = []

    def handler(request):
        keys.append(request.headers.get("x-api-key"))
        return _moonraker(request)

    _run(read_status, _printer(printhost_apikey="s3cret"), handler)
    assert keys and set(keys) == {"s3cret"}


@pytest.mark.parametrize(
    ("response", "match"),
    [
        (httpx.Response(401), "API key"),
        (httpx.Response(404), "Moonraker"),
        (httpx.Response(200, text="<html>login</html>"), "Moonraker"),
    ],
)
def test_a_printer_that_cannot_be_read_says_why(response, match):
    with pytest.raises(PrintHostError, match=match):
        _run(read_status, _printer(), lambda request: response)


def test_a_printer_that_is_off_says_it_could_not_be_reached():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(PrintHostError, match="reach"):
        _run(read_status, _printer(), handler)


def test_only_a_klipper_printer_has_a_live_status():
    with pytest.raises(PrintHostError, match="Klipper"):
        _run(read_status, _printer(host_type="octoprint"), _moonraker)


# ---- pause, resume, cancel ----


@pytest.mark.parametrize("action", ["pause", "resume", "cancel"])
def test_each_control_is_one_post_to_the_printer(action):
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        return _moonraker(request)

    _run(print_control, _printer(), handler, action)
    assert seen == [("POST", f"/printer/print/{action}")]


def test_nothing_but_those_three_can_be_asked_of_the_printer():
    called = []

    def handler(request):
        called.append(request.url.path)
        return _moonraker(request)

    for bad in ("emergency_stop", "restart", "../server/restart", ""):
        with pytest.raises(PrintHostError, match="pause, resume or cancel"):
            _run(print_control, _printer(), handler, bad)
    assert called == []


def test_a_refusal_from_the_printer_is_passed_on_in_its_words():
    def handler(request):
        return httpx.Response(400, json={"error": {"code": 400, "message": "Klippy Disconnected"}})

    with pytest.raises(PrintHostError, match="Klippy Disconnected"):
        _run(print_control, _printer(), handler, "pause")


# ---- webcams ----


def test_the_enabled_webcams_are_listed_with_addresses_made_whole():
    cams = _run(webcam_list, _printer(), _moonraker)
    assert [c["name"] for c in cams] == ["tool", "far"]
    assert cams[0]["snapshot_url"] == f"{BASE}/webcam/?action=snapshot"
    assert cams[1]["snapshot_url"] == "http://cam.local:8080/snap.jpg"


def test_a_printer_with_no_webcam_lists_none():
    def handler(request):
        return httpx.Response(200, json={"result": {"webcams": []}})

    assert _run(webcam_list, _printer(), handler) == []


def test_a_snapshot_is_the_picture_and_its_type():
    data, kind = _run(webcam_snapshot, _printer(), _moonraker, 0)
    assert data == b"\xff\xd8jpegbytes"
    assert kind == "image/jpeg"


def test_a_snapshot_from_another_address_is_fetched_from_there():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return _moonraker(request)

    _run(webcam_snapshot, _printer(), handler, 1)
    assert "http://cam.local:8080/snap.jpg" in seen


def test_no_such_camera_is_an_error_not_a_crash():
    with pytest.raises(PrintHostError, match="camera"):
        _run(webcam_snapshot, _printer(), _moonraker, 7)


def test_something_that_is_not_a_picture_is_refused():
    def handler(request):
        if request.url.path == "/webcam/":
            return httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"})
        return _moonraker(request)

    with pytest.raises(PrintHostError, match="picture"):
        _run(webcam_snapshot, _printer(), handler, 0)


def test_a_picture_that_is_too_big_is_refused():
    def handler(request):
        if request.url.path == "/webcam/":
            return httpx.Response(200, content=b"x" * (6 * 1024 * 1024), headers={"content-type": "image/jpeg"})
        return _moonraker(request)

    with pytest.raises(PrintHostError, match="large"):
        _run(webcam_snapshot, _printer(), handler, 0)


def test_the_printers_key_goes_only_to_the_printer_never_to_a_camera_elsewhere():
    seen = {}

    def handler(request):
        seen[request.url.host] = request.headers.get("x-api-key")
        return _moonraker(request)

    _run(webcam_snapshot, _printer(printhost_apikey="s3cret"), handler, 1)
    assert seen["voron.local"] == "s3cret"  # the printer's own list of cameras
    assert seen["cam.local"] is None  # the other address
