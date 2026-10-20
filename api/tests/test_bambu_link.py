"""The live link to a Bambu printer over MQTT: connecting, asking for everything, merging what it sends, and pause/resume/stop.

The tests use a fake transport (what talks MQTT), so nothing here needs a printer or a broker.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from app.bambu_link import BambuError, BambuLink, BambuLinks, PahoTransport

SERIAL = "00M00A000000000"
REPORT = f"device/{SERIAL}/report"
REQUEST = f"device/{SERIAL}/request"


class FakeTransport:
    """Records what is asked of it, and lets a test say what the printer sends."""

    def __init__(self, fail_connect: str | None = None, answers: list[dict] | None = None):
        self.fail_connect = fail_connect
        self.answers = answers if answers is not None else []
        self.connected_to: tuple[str, str, str] | None = None
        self.subscribed: list[str] = []
        self.published: list[tuple[str, dict]] = []
        self.closed = False
        self.handler: Callable[[str, bytes], None] = lambda topic, payload: None

    def set_on_message(self, handler):
        self.handler = handler

    def connect(self, host, username, password):
        if self.fail_connect:
            raise BambuError(self.fail_connect)
        self.connected_to = (host, username, password)

    def subscribe(self, topic):
        self.subscribed.append(topic)

    def publish(self, topic, payload):
        message = json.loads(payload)
        self.published.append((topic, message))
        # a pushall is answered with the whole report, as the printer does
        if "pushing" in message and self.answers and self.handler:
            self.send(self.answers.pop(0))

    def send(self, print_report: dict, command: str = "push_status"):
        self.handler(REPORT, json.dumps({"print": {"command": command, **print_report}}).encode())

    def close(self):
        self.closed = True


def _link(transport: FakeTransport, **kwargs) -> BambuLink:
    return BambuLink("192.168.1.50", SERIAL, "12345678", lambda: transport, reply_wait=0.05, **kwargs)


FULL = {"gcode_state": "RUNNING", "mc_percent": 42, "nozzle_temper": 200}


# ---- connecting ----


def test_it_connects_as_bblp_with_the_access_code_and_listens_to_the_printer():
    transport = FakeTransport(answers=[FULL])
    _link(transport).report()
    assert transport.connected_to == ("192.168.1.50", "bblp", "12345678")
    assert transport.subscribed == [REPORT]


def test_it_asks_the_printer_for_everything_it_knows():
    transport = FakeTransport(answers=[FULL])
    _link(transport).report()
    topic, message = transport.published[0]
    assert topic == REQUEST
    assert message["pushing"]["command"] == "pushall"


def test_a_printer_that_cannot_be_connected_to_says_why():
    transport = FakeTransport(fail_connect="The printer refused the access code")
    with pytest.raises(BambuError, match="access code"):
        _link(transport).report()


# ---- what it reports ----


def test_the_report_is_what_the_printer_sent():
    report = _link(FakeTransport(answers=[FULL])).report()
    assert report["gcode_state"] == "RUNNING"
    assert report["mc_percent"] == 42


def test_what_a_p1_sends_afterwards_is_merged_into_what_is_known():
    transport = FakeTransport(answers=[FULL])
    link = _link(transport)
    link.report()
    transport.send({"mc_percent": 43})
    report = link.report()
    assert report["mc_percent"] == 43
    assert report["nozzle_temper"] == 200  # kept


def test_answers_to_commands_and_junk_are_not_taken_for_status():
    transport = FakeTransport(answers=[FULL])
    link = _link(transport)
    link.report()
    transport.send({"mc_percent": 99}, command="gcode_line")
    transport.handler(REPORT, b"not json at all")
    transport.handler(REPORT, json.dumps({"info": {"command": "get_version"}}).encode())
    assert link.report()["mc_percent"] == 42


def test_a_printer_that_says_nothing_gets_asked_twice_and_then_the_user_is_told_what_to_check():
    transport = FakeTransport(answers=[])
    with pytest.raises(BambuError, match="Developer Mode"):
        _link(transport).report()
    assert len([m for _, m in transport.published if "pushing" in m]) == 2


# ---- commands ----


@pytest.mark.parametrize(("action", "command"), [("pause", "pause"), ("resume", "resume"), ("cancel", "stop")])
def test_pause_resume_and_cancel_are_sent_as_the_printers_own_commands(action, command):
    transport = FakeTransport(answers=[FULL])
    link = _link(transport)
    link.control(action)
    topic, message = transport.published[-1]
    assert topic == REQUEST
    assert message["print"]["command"] == command


def test_nothing_else_can_be_sent_through_it():
    transport = FakeTransport()
    link = _link(transport)
    for bad in ("gcode_line", "restart", "", "unload_filament"):
        with pytest.raises(BambuError, match="pause, resume or cancel"):
            link.control(bad)
    assert transport.published == []


# ---- keeping links ----


def test_the_same_printer_gets_the_same_link_and_a_changed_code_a_new_one():
    made = []

    def factory():
        made.append(FakeTransport(answers=[FULL]))
        return made[-1]

    links = BambuLinks(transport_factory=factory, reply_wait=0.05)
    a = links.get("p1", "192.168.1.50", SERIAL, "11111111")
    assert links.get("p1", "192.168.1.50", SERIAL, "11111111") is a
    a.report()
    b = links.get("p1", "192.168.1.50", SERIAL, "22222222")
    assert b is not a
    assert made[0].closed is True


def test_a_link_nobody_has_asked_after_for_a_minute_is_closed():
    now = [1000.0]
    made = []

    def factory():
        made.append(FakeTransport(answers=[FULL]))
        return made[-1]

    links = BambuLinks(transport_factory=factory, reply_wait=0.05, clock=lambda: now[0])
    links.get("p1", "192.168.1.50", SERIAL, "12345678").report()
    now[0] += 30
    links.reap()
    assert made[0].closed is False
    now[0] += 40
    links.reap()
    assert made[0].closed is True


# ---- the MQTT client itself (paho), with a stand-in for it ----


class FakeReason:
    def __init__(self, failed: bool, text: str = ""):
        self.is_failure = failed
        self.text = text

    def __str__(self):
        return self.text


class FakePaho:
    """The parts of paho's client the transport uses."""

    last: FakePaho

    def __init__(self, reason: FakeReason | None = None, fail_with: Exception | None = None):
        self.reason = reason or FakeReason(False)
        self.fail_with = fail_with
        self.calls: list[tuple] = []
        self.on_connect: Callable[..., None] = lambda *args: None
        self.on_message: Callable[..., None] = lambda *args: None
        FakePaho.last = self

    def tls_set(self, **kwargs):
        self.calls.append(("tls_set", kwargs))

    def tls_insecure_set(self, value):
        self.calls.append(("tls_insecure_set", value))

    def username_pw_set(self, username, password):
        self.calls.append(("auth", username, password))

    def connect(self, host, port, keepalive):
        if self.fail_with:
            raise self.fail_with
        self.calls.append(("connect", host, port))

    def loop_start(self):
        self.calls.append(("loop_start",))
        self.on_connect(self, None, {}, self.reason, None)

    def subscribe(self, topic, qos=0):
        self.calls.append(("subscribe", topic, qos))

    def publish(self, topic, payload, qos=0):
        self.calls.append(("publish", topic, payload, qos))

    def loop_stop(self):
        self.calls.append(("loop_stop",))

    def disconnect(self):
        self.calls.append(("disconnect",))


def _paho(**kwargs) -> PahoTransport:
    return PahoTransport(client_factory=lambda: FakePaho(**kwargs), connect_wait=0.5)


def test_the_real_transport_uses_tls_on_8883_without_checking_the_printers_own_certificate():
    transport = _paho()
    transport.connect("192.168.1.50", "bblp", "12345678")
    calls = FakePaho.last.calls
    assert ("auth", "bblp", "12345678") in calls
    assert ("tls_insecure_set", True) in calls  # a printer's certificate is its own
    assert ("connect", "192.168.1.50", 8883) in calls
    assert any(c[0] == "tls_set" for c in calls)


def test_a_wrong_access_code_is_said_to_be_that():
    transport = _paho(reason=FakeReason(True, "Not authorized"))
    with pytest.raises(BambuError, match="access code"):
        transport.connect("192.168.1.50", "bblp", "wrong")


def test_a_printer_that_is_off_is_said_to_be_unreachable():
    transport = _paho(fail_with=OSError("No route to host"))
    with pytest.raises(BambuError, match="reach"):
        transport.connect("192.168.1.50", "bblp", "12345678")


def test_messages_commands_and_closing_go_through_paho():
    transport = _paho()
    seen = []
    transport.set_on_message(lambda topic, payload: seen.append((topic, payload)))
    transport.connect("192.168.1.50", "bblp", "12345678")
    transport.subscribe(REPORT)
    transport.publish(REQUEST, '{"a": 1}')
    FakePaho.last.on_message(FakePaho.last, None, type("M", (), {"topic": REPORT, "payload": b"hi"})())
    transport.close()
    calls = FakePaho.last.calls
    assert ("subscribe", REPORT, 1) in calls
    assert ("publish", REQUEST, '{"a": 1}', 1) in calls
    assert seen == [(REPORT, b"hi")]
    assert ("disconnect",) in calls and ("loop_stop",) in calls


# ---- from a saved printer ----


def _row(**overrides):
    row = {"id": "p1", "print_host": "192.168.1.50", "device_id": SERIAL, "printhost_apikey": "12345678"}
    row.update(overrides)
    return row


def test_the_report_of_a_saved_printer_is_read_through_its_link(monkeypatch):
    import asyncio

    from app import bambu_link

    monkeypatch.setattr(
        bambu_link, "links", BambuLinks(transport_factory=lambda: FakeTransport(answers=[FULL]), reply_wait=0.05)
    )
    assert asyncio.run(bambu_link.read_report(_row()))["mc_percent"] == 42


def test_a_saved_printer_missing_what_it_needs_says_what(monkeypatch):
    import asyncio

    from app import bambu_link

    for missing in ("print_host", "device_id", "printhost_apikey"):
        with pytest.raises(BambuError, match="serial number"):
            asyncio.run(bambu_link.read_report(_row(**{missing: ""})))


def test_a_connection_check_says_how_the_printer_is_and_lets_go_of_it(monkeypatch):
    import asyncio

    from app import bambu_link

    made = []

    def factory():
        made.append(FakeTransport(answers=[{**FULL, "gcode_state": "IDLE"}]))
        return made[-1]

    monkeypatch.setattr(bambu_link, "_new_transport", factory)
    message = asyncio.run(bambu_link.check_connection("192.168.1.50", SERIAL, "12345678"))
    assert "Connected" in message and "standby" in message
    assert made[0].closed is True


# ---- an address can carry a port ----


def test_an_address_with_a_port_is_connected_to_on_that_port():
    transport = _paho()
    transport.connect("192.168.1.50:9999", "bblp", "12345678")
    assert ("connect", "192.168.1.50", 9999) in FakePaho.last.calls


def test_an_address_with_no_port_uses_8883():
    transport = _paho()
    transport.connect(" 192.168.1.50 ", "bblp", "12345678")
    assert ("connect", "192.168.1.50", 8883) in FakePaho.last.calls


# ---- the raw report, for finding out what a printer says (nothing that identifies it) ----


def test_a_raw_report_has_the_serial_number_the_address_and_the_code_taken_out():
    from app.bambu_link import redacted

    report = {
        "gcode_state": "RUNNING",
        "sn": SERIAL,
        "ip": "192.168.1.50",
        "ap_ssid": "MyWifi",
        "subtask_name": f"made on {SERIAL}",
        "nested": {"wifi": "192.168.1.50 is me", "layers": [1, 2, {"code": "12345678"}]},
        "mc_percent": 42,
    }
    clean = redacted(report, [SERIAL, "192.168.1.50", "12345678"])
    text = json.dumps(clean)
    for secret in (SERIAL, "192.168.1.50", "12345678", "MyWifi"):
        assert secret not in text
    assert clean["gcode_state"] == "RUNNING" and clean["mc_percent"] == 42


# ---- starting a print ----


def test_a_print_can_be_started_with_the_start_command_and_nothing_else_of_that_kind():
    from app.bambu_send import project_file_command

    transport = FakeTransport(answers=[FULL])
    link = _link(transport)
    link.start_print(
        project_file_command(plate="Metadata/plate_1.gcode", remote_name="a.gcode.3mf", md5="x", use_ams=False)
    )
    topic, message = transport.published[-1]
    assert topic == REQUEST and message["print"]["command"] == "project_file"


def test_no_other_command_can_be_sent_as_a_start():
    transport = FakeTransport()
    link = _link(transport)
    for bad in ({"print": {"command": "gcode_line", "param": "M104 S300"}}, {"system": {"command": "ledctrl"}}, {}):
        with pytest.raises(BambuError, match="start"):
            link.start_print(bad)
    assert transport.published == []
