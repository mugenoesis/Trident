"""The live link to a Bambu printer over MQTT, in LAN / Developer mode.

A printer speaks MQTT over TLS on port 8883: user `bblp`, the printer's LAN access code as the password, `device/<serial>/report` for what it says and
`device/<serial>/request` for what it is told. A link stays up while someone is looking at the printer and is let go a minute after the last look, so
the status page can ask often without a new connection each time. An X1 reports everything every time; a P1 or an A1 reports only what changed after
the first full report, so a link keeps the merged report.

The part that speaks MQTT (`PahoTransport`) is behind a small interface, so everything else is tested with a fake one. Bambu's protocol is documented
by its users, not by Bambu: this takes only the fields it knows and ignores the rest.
"""

from __future__ import annotations

import asyncio
import json
import ssl
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from .bambu_status import merge_report, status_from_bambu

MQTT_PORT = 8883
_USERNAME = "bblp"
# What a link is asked to do to the print: the names the page uses, and the printer's own commands for them.
_CONTROLS = {"pause": "pause", "resume": "resume", "cancel": "stop"}
_IDLE_SECONDS = 60.0
# Keys of a report that say which printer it is, left out of a raw report that is shared.
_IDENTIFYING_KEYS = frozenset({"sn", "ip", "ap_ssid", "ssid", "bssid", "mac"})


def split_host(address: str) -> tuple[str, int]:
    """A printer's address as saved: an IP address or name, with a port after a colon if it is not the usual 8883."""
    text = address.strip()
    name, colon, port = text.rpartition(":")
    if colon and port.isdigit() and ":" not in name:
        return name, int(port)
    return text, MQTT_PORT


class BambuError(Exception):
    """Something went wrong talking to the printer; the message says what and is fit to show the user."""


class Transport(Protocol):
    """What speaks MQTT for a link."""

    def set_on_message(self, handler: Callable[[str, bytes], None]) -> None: ...
    def connect(self, host: str, username: str, password: str) -> None: ...
    def subscribe(self, topic: str) -> None: ...
    def publish(self, topic: str, payload: str) -> None: ...
    def close(self) -> None: ...


class PahoTransport:
    """MQTT through paho: TLS on 8883 without checking the printer's own (self-made) certificate."""

    def __init__(self, client_factory: Callable[[], Any] | None = None, connect_wait: float = 8.0):
        self._factory = client_factory or self._paho_client
        self._connect_wait = connect_wait
        self._client: Any = None
        self._handler: Callable[[str, bytes], None] = lambda topic, payload: None

    @staticmethod
    def _paho_client() -> Any:
        import paho.mqtt.client as mqtt  # imported here: only a link to a real printer needs it

        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)

    def set_on_message(self, handler: Callable[[str, bytes], None]) -> None:
        self._handler = handler

    def connect(self, host: str, username: str, password: str) -> None:
        client = self._factory()
        outcome: dict[str, Any] = {}
        connected = threading.Event()

        def on_connect(_client: Any, _userdata: Any, _flags: Any, reason: Any, _properties: Any = None) -> None:
            outcome["reason"] = reason
            connected.set()

        client.on_connect = on_connect
        client.on_message = lambda _client, _userdata, message: self._handler(message.topic, bytes(message.payload))
        client.username_pw_set(username, password)
        client.tls_set(cert_reqs=ssl.CERT_NONE)
        client.tls_insecure_set(True)  # a printer's certificate is its own, so there is nothing to check it against
        name, port = split_host(host)
        try:
            client.connect(name, port, 30)
        except OSError as exc:
            raise BambuError(f"Couldn't reach the printer: {exc}") from exc
        client.loop_start()
        if not connected.wait(self._connect_wait):
            self._stop(client)
            raise BambuError("Couldn't reach the printer: it did not answer")
        if outcome["reason"].is_failure:
            self._stop(client)
            raise BambuError(
                "The printer refused the access code (check it, and the serial number, on the printer's screen)"
            )
        self._client = client

    @staticmethod
    def _stop(client: Any) -> None:
        client.disconnect()
        client.loop_stop()

    def subscribe(self, topic: str) -> None:
        self._client.subscribe(topic, qos=1)

    def publish(self, topic: str, payload: str) -> None:
        self._client.publish(topic, payload, qos=1)

    def close(self) -> None:
        if self._client is not None:
            self._stop(self._client)
            self._client = None


class BambuLink:
    """One printer: what it has reported so far, and what can be told it."""

    def __init__(
        self,
        host: str,
        serial: str,
        code: str,
        transport_factory: Callable[[], Transport],
        *,
        reply_wait: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.host, self.serial, self.code = host, serial, code
        self._factory = transport_factory
        self._reply_wait = reply_wait
        self._clock = clock
        self._transport: Transport | None = None
        self._lock = threading.Lock()
        self._report: dict[str, Any] = {}
        self._got = threading.Event()
        self.last_used = clock()

    @property
    def _request_topic(self) -> str:
        return f"device/{self.serial}/request"

    def _on_message(self, _topic: str, payload: bytes) -> None:
        """Only status reports are kept: answers to commands and anything that is not JSON are left alone."""
        try:
            message = json.loads(payload)
        except ValueError:
            return
        update = message.get("print") if isinstance(message, dict) else None
        if not isinstance(update, dict) or update.get("command") != "push_status":
            return
        with self._lock:
            self._report = merge_report(self._report, update)
        self._got.set()

    def _ask_for_everything(self) -> None:
        assert self._transport is not None
        self._transport.publish(
            self._request_topic, json.dumps({"pushing": {"sequence_id": "1", "command": "pushall"}})
        )

    def _ensure_started(self) -> None:
        self.last_used = self._clock()
        with self._lock:
            if self._transport is not None:
                return
            transport = self._factory()
            transport.set_on_message(self._on_message)
            try:
                transport.connect(self.host, _USERNAME, self.code)
            except BambuError:
                transport.close()
                raise
            self._transport = transport
        transport.subscribe(f"device/{self.serial}/report")
        self._ask_for_everything()

    def report(self) -> dict[str, Any]:
        """Everything the printer has reported (asking it to, if it has said nothing yet)."""
        self._ensure_started()
        if not self._got.wait(self._reply_wait):
            self._ask_for_everything()
            if not self._got.wait(self._reply_wait):
                raise BambuError(
                    "The printer did not answer. Check that it is on, that Developer Mode (which needs LAN Only mode) is on, "
                    "and that the serial number and the access code are right."
                )
        with self._lock:
            return dict(self._report)

    def control(self, action: str) -> None:
        """Pause, resume or cancel the print. Nothing else can be sent through here."""
        if action not in _CONTROLS:
            raise BambuError("Only pause, resume or cancel can be asked of the printer")
        self._ensure_started()
        assert self._transport is not None
        self._transport.publish(
            self._request_topic, json.dumps({"print": {"sequence_id": "0", "command": _CONTROLS[action], "param": ""}})
        )

    def start_print(self, message: dict[str, Any]) -> None:
        """Starts an uploaded print: only the start command can be sent through here."""
        command = message.get("print", {}).get("command") if isinstance(message.get("print"), dict) else None
        if command != "project_file":
            raise BambuError("Only the command that starts an uploaded print can be sent that way")
        self._ensure_started()
        assert self._transport is not None
        self._transport.publish(self._request_topic, json.dumps(message))

    def close(self) -> None:
        with self._lock:
            transport, self._transport = self._transport, None
            self._report = {}
            self._got.clear()
        if transport is not None:
            transport.close()


class BambuLinks:
    """The links that are up, one for each printer, let go once nobody has asked after them for a minute."""

    def __init__(
        self,
        transport_factory: Callable[[], Transport] = PahoTransport,
        *,
        reply_wait: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._factory = transport_factory
        self._reply_wait = reply_wait
        self._clock = clock
        self._links: dict[str, BambuLink] = {}
        self._lock = threading.Lock()
        self._reaper: threading.Thread | None = None

    def get(self, printer_id: str, host: str, serial: str, code: str) -> BambuLink:
        """The link to a printer: the one that is up, unless its address, serial number or access code has changed since."""
        with self._lock:
            link = self._links.get(printer_id)
            if link is not None and (link.host, link.serial, link.code) != (host, serial, code):
                link.close()
                link = None
            if link is None:
                link = BambuLink(host, serial, code, self._factory, reply_wait=self._reply_wait, clock=self._clock)
                self._links[printer_id] = link
            return link

    def reap(self) -> None:
        """Lets go of the links nobody has asked after lately."""
        with self._lock:
            idle = [key for key, link in self._links.items() if self._clock() - link.last_used > _IDLE_SECONDS]
            for key in idle:
                self._links.pop(key).close()

    def start_reaper(self) -> None:
        """Lets go of idle links every so often, for as long as the server runs."""
        if self._reaper is not None:
            return

        def loop() -> None:
            while True:
                time.sleep(15)
                self.reap()

        self._reaper = threading.Thread(target=loop, name="bambu-link-reaper", daemon=True)
        self._reaper.start()


def redacted(value: Any, secrets: list[str]) -> Any:
    """A report (or a part of one) with what identifies the printer taken out: keys such as its serial number and address, and any text that has
    one of the given secrets (its serial number, address and access code) in it. Fit to paste when asking what a printer reports.
    """
    if isinstance(value, dict):
        return {k: redacted(v, secrets) for k, v in value.items() if k not in _IDENTIFYING_KEYS}
    if isinstance(value, list):
        return [redacted(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in (s for s in secrets if s):
            value = value.replace(secret, "***")
    return value


def _new_transport() -> Transport:
    return PahoTransport()


links = BambuLinks(transport_factory=lambda: _new_transport())


# ---- what the routes use: a saved printer's row (secrets included) in, a report or an action out ----

_NEEDS = "A Bambu printer needs its IP address, serial number and access code (all three are on its screen, under the LAN settings)"


def _complete(host: object, serial: object, code: object) -> tuple[str, str, str]:
    if not (
        isinstance(host, str)
        and host.strip()
        and isinstance(serial, str)
        and serial.strip()
        and isinstance(code, str)
        and code.strip()
    ):
        raise BambuError(_NEEDS)
    return host.strip(), serial.strip(), code.strip()


def connection_of(row: Any) -> tuple[str, str, str]:
    """A saved Bambu printer's address, serial number and access code (or an error that says which is missing)."""
    return _complete(row["print_host"], row["device_id"], row["printhost_apikey"])


def _link_for(row: Any) -> BambuLink:
    host, serial, code = _complete(row["print_host"], row["device_id"], row["printhost_apikey"])
    links.start_reaper()
    return links.get(row["id"], host, serial, code)


async def read_report(row: Any) -> dict[str, Any]:
    """Everything a saved Bambu printer has reported (the link to it is made if need be, and kept while it is looked at)."""
    link = _link_for(row)
    return await asyncio.to_thread(link.report)


async def control(row: Any, action: str) -> None:
    """Pause, resume or cancel the print on a saved Bambu printer."""
    link = _link_for(row)
    await asyncio.to_thread(link.control, action)


async def send_print(
    row: Any, three_mf: Path, *, name: str, start: bool, use_ams: bool, plate_index: int | None
) -> None:
    """Uploads a sliced 3MF to a saved Bambu printer, and starts it if asked (otherwise it waits on the printer's own screen)."""
    from . import bambu_send  # imported here: bambu_send uses this module's errors

    host, _serial, code = _complete(row["print_host"], row["device_id"], row["printhost_apikey"])
    plate = bambu_send.plate_path(three_mf, plate_index)
    remote = bambu_send.remote_name(name)
    await asyncio.to_thread(bambu_send.upload, host, code, three_mf, remote)
    if start:
        message = bambu_send.project_file_command(
            plate=plate, remote_name=remote, md5=bambu_send.md5_of(three_mf), use_ams=use_ams
        )
        await asyncio.to_thread(_link_for(row).start_print, message)


async def check_connection(host: str | None, serial: str | None, code: str | None) -> str:
    """Connects to a printer that may not be saved yet, to see that the address, serial number and access code are right; lets go of it again."""
    host, serial, code = _complete(host, serial, code)
    link = BambuLink(host, serial, code, lambda: _new_transport())
    try:
        report = await asyncio.to_thread(link.report)
    finally:
        await asyncio.to_thread(link.close)
    return f"Connected (printer state: {status_from_bambu(report, serial)['state']})"
