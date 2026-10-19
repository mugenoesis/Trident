"""Reading a Klipper printer's config through Moonraker (read-only: three GETs, nothing is changed on the printer)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.printhost import PrintHostError, read_klipper

INFO = {"result": {"state": "ready", "state_message": "Printer is ready", "hostname": "voron", "software_version": "v0.12.0"}}
CONFIG = {"result": {"status": {"configfile": {"settings": {"printer": {"kinematics": "corexy"}}}}}}
OBJECTS = {"result": {"objects": ["extruder", "exclude_object", "heater_bed"]}}


def _printer(**overrides):
    base = {
        "host_type": "moonraker",
        "print_host": "http://voron.local:7125/",
        "printhost_apikey": None,
        "printhost_user": None,
        "printhost_password": None,
    }
    base.update(overrides)
    return base


def _read(printer, handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return asyncio.run(read_klipper(printer, client=client))


def _moonraker(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/printer/info":
        return httpx.Response(200, json=INFO)
    if path == "/printer/objects/query":
        return httpx.Response(200, json=CONFIG)
    if path == "/printer/objects/list":
        return httpx.Response(200, json=OBJECTS)
    return httpx.Response(404)


def test_it_reads_the_info_the_settings_and_the_object_list():
    snapshot = _read(_printer(), _moonraker)
    assert snapshot["info"]["hostname"] == "voron"
    assert snapshot["settings"] == {"printer": {"kinematics": "corexy"}}
    assert snapshot["objects"] == ["extruder", "exclude_object", "heater_bed"]


def test_it_only_ever_reads():
    methods = []

    def handler(request):
        methods.append(request.method)
        return _moonraker(request)

    _read(_printer(), handler)
    assert set(methods) == {"GET"}


def test_the_config_is_asked_for_by_name_and_the_address_is_tidied():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return _moonraker(request)

    _read(_printer(), handler)
    assert "http://voron.local:7125/printer/objects/query?configfile" in seen
    assert "http://voron.local:7125/printer/info" in seen


def test_an_api_key_is_sent_as_a_header():
    keys = []

    def handler(request):
        keys.append(request.headers.get("x-api-key"))
        return _moonraker(request)

    _read(_printer(printhost_apikey="s3cret"), handler)
    assert set(keys) == {"s3cret"}


def test_a_refused_key_says_to_check_the_api_key():
    with pytest.raises(PrintHostError, match="API key"):
        _read(_printer(), lambda request: httpx.Response(401))


def test_an_address_that_is_not_moonraker_says_so():
    with pytest.raises(PrintHostError, match="Moonraker"):
        _read(_printer(), lambda request: httpx.Response(404))


def test_an_unreachable_printer_says_it_could_not_be_reached():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(PrintHostError, match="reach"):
        _read(_printer(), handler)


def test_a_klipper_that_is_not_ready_gives_its_own_message():
    def handler(request):
        if request.url.path == "/printer/info":
            return httpx.Response(200, json={"result": {"state": "shutdown", "state_message": "MCU 'mcu' shutdown: Timer too close"}})
        return httpx.Response(503)

    with pytest.raises(PrintHostError, match="Timer too close"):
        _read(_printer(), handler)


def test_an_answer_that_is_not_json_is_an_error_not_a_crash():
    with pytest.raises(PrintHostError, match="Moonraker"):
        _read(_printer(), lambda request: httpx.Response(200, text="<html>login</html>"))


def test_only_a_klipper_printer_can_be_read():
    with pytest.raises(PrintHostError, match="Klipper"):
        _read(_printer(host_type="octoprint"), _moonraker)


def test_a_printer_with_no_address_says_so():
    with pytest.raises(PrintHostError, match="address"):
        _read(_printer(print_host=""), _moonraker)
