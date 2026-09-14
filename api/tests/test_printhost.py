from __future__ import annotations

import asyncio

import httpx
import pytest

from app.printhost import PrintHostError, send_gcode
from app.printhost import test_connection as ping_printer


def _printer(**overrides):
    base = {
        "host_type": "moonraker",
        "print_host": "http://printer.local:7125",
        "printhost_apikey": None,
        "printhost_user": None,
        "printhost_password": None,
    }
    base.update(overrides)
    return base


def _client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_moonraker_upload_hits_expected_url_and_field(tmp_path):
    gcode = tmp_path / "part.gcode"
    gcode.write_text("; hello\n")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["content_type_header"] = request.headers.get("content-type", "")
        return httpx.Response(200, json={"ok": True})

    asyncio.run(send_gcode(_printer(), gcode, False, client=_client_for(handler)))
    assert seen["url"] == "http://printer.local:7125/server/files/upload"
    assert "multipart/form-data" in seen["content_type_header"]


def test_octoprint_upload_hits_expected_url(tmp_path):
    gcode = tmp_path / "part.gcode"
    gcode.write_text("; hello\n")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(201, json={"done": True})

    asyncio.run(
        send_gcode(_printer(host_type="octoprint"), gcode, False, client=_client_for(handler))
    )
    assert seen["url"] == "http://printer.local:7125/api/files/local"


def test_apikey_sent_as_header(tmp_path):
    gcode = tmp_path / "part.gcode"
    gcode.write_text("; hello\n")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["apikey"] = request.headers.get("x-api-key")
        return httpx.Response(200)

    asyncio.run(
        send_gcode(_printer(printhost_apikey="secret123"), gcode, False, client=_client_for(handler))
    )
    assert seen["apikey"] == "secret123"


def test_start_print_flag_included_when_true(tmp_path):
    gcode = tmp_path / "part.gcode"
    gcode.write_text("; hello\n")

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode("utf-8", errors="ignore")
        assert 'name="print"' in body
        return httpx.Response(200)

    asyncio.run(send_gcode(_printer(), gcode, True, client=_client_for(handler)))


def test_error_response_raises_printhosterror(tmp_path):
    gcode = tmp_path / "part.gcode"
    gcode.write_text("; hello\n")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    with pytest.raises(PrintHostError, match="500"):
        asyncio.run(send_gcode(_printer(), gcode, False, client=_client_for(handler)))


def test_network_error_raises_printhosterror(tmp_path):
    gcode = tmp_path / "part.gcode"
    gcode.write_text("; hello\n")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(PrintHostError, match="reach the printer"):
        asyncio.run(send_gcode(_printer(), gcode, False, client=_client_for(handler)))


def test_missing_print_host_raises_before_any_request(tmp_path):
    with pytest.raises(PrintHostError, match="no host address"):
        asyncio.run(send_gcode(_printer(print_host=None), tmp_path / "part.gcode", False))


def test_unsupported_host_type_raises(tmp_path):
    with pytest.raises(PrintHostError, match="isn't supported"):
        asyncio.run(send_gcode(_printer(host_type="prusalink"), tmp_path / "part.gcode", False))


def test_test_connection_moonraker_reports_klippy_state():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://printer.local:7125/server/info"
        return httpx.Response(200, json={"result": {"klippy_state": "ready"}})

    message = asyncio.run(ping_printer(_printer(), client=_client_for(handler)))
    assert "ready" in message


def test_test_connection_octoprint_reports_server_text():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://printer.local:7125/api/version"
        return httpx.Response(200, json={"text": "OctoPrint 1.10.0"})

    message = asyncio.run(
        ping_printer(_printer(host_type="octoprint"), client=_client_for(handler))
    )
    assert message == "OctoPrint 1.10.0"


def test_test_connection_sends_apikey():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["apikey"] = request.headers.get("x-api-key")
        return httpx.Response(200, json={})

    asyncio.run(
        ping_printer(_printer(printhost_apikey="secret123"), client=_client_for(handler))
    )
    assert seen["apikey"] == "secret123"


def test_test_connection_error_response_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    with pytest.raises(PrintHostError, match="401"):
        asyncio.run(ping_printer(_printer(), client=_client_for(handler)))


def test_test_connection_missing_host_raises():
    with pytest.raises(PrintHostError, match="no host address"):
        asyncio.run(ping_printer(_printer(print_host=None)))
