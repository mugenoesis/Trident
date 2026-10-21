"""Finding where a Bambu printer is on the local network from the serial number in its certificate (app/bambu_discovery.py).

A printer's MQTT port answers a TLS handshake with a certificate whose subject is its serial number, so a printer can be found without
sending it, or anything else on the network, a password. The fixture is a throwaway certificate (subject 01P00A000000000, issued by a
differently named CA, so that reading the issuer by mistake would fail)."""

from __future__ import annotations

import asyncio
import base64

import pytest

from app import bambu_discovery as discovery

LEAF = base64.b64decode(
    "MIIDJzCCAg+gAwIBAgIUKIHdf9ws+EWUvveuVg1Ze0Wa42YwDQYJKoZIhvcNAQELBQAwOzELMAkGA1UEBhMCQ04xGjAYBgNVBAoMEVRlc3QgUHJpbnRlcnMgQ28uMRAwDgYDVQQDDAdUZXN0IENBMCAXDTI2MTAyMDIxNTIwNVoYDzIxMjYwOTI2MjE1MjA1WjAaMRgwFgYDVQQDDA8wMVAwMEEwMDAwMDAwMDAwggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAwggEKAoIBAQCU5oHeoeMOmBAHqM7OTh81tCRD+v2CXJk59i1gt3+C4Cm5FE7w1H8BUPhMazqTG7RIrFL3AH1jkPzeGUr2eeNo93JpEewE/gHvF8d/C5EAqHdIlwLvJSbZx6hwJNER84gUhbnyxY2h4mNEZX/F7n5B/6tLk7yIGWWyK+qRKPKrQUfd5YptsvArkd1nKke7XGnSaTtpYoP2m+yKO79YHPHbF76QU5nQPGY+8/yS1uYRHFRPU2+fJqHpaNQOu2qPlvbtW+av45qrpX1EtylpGJMSeCTVQK3hX7YPPSBy0VnRCIGazbrty949WojTfF39a6US+8XiiZEdI4bamB8m2hBjAgMBAAGjQjBAMB0GA1UdDgQWBBSy5VU50OKsOHI2jBzV7qZliT9xmTAfBgNVHSMEGDAWgBT+uHfcuET9nkB350BWtgw1qRSyxDANBgkqhkiG9w0BAQsFAAOCAQEANiXaHXuinj/9qPptWpTCPmiFg6RyFdqvTt+m4MbQ8jcFUwrtq17isZCbJZ6Cy1VOV0qyudMg4dI+K/8RTkSVPyIDdD7y4cREBfm/ovWrNMc3YkT8WZGLx/LoYTo399WzG+98FsRMsY/iAeKNZpdOmNx6eg4z7uMfk6ExA6k4SGA8t5m6HTU+0lwSFGWtt7iKpY8To4yFtaYg+7vheladeIn+Rqcrn/xm21b0RnaXLV/njVf6FE95MtiqUUqKUKYgV4zaLzezl3he+V5H2dXy58kaP2+GHZo/la+v5vc2+AEC/Ep+p7XQHBj5nsQXtRR9vtECXrdRR05B8eP0yGJ9EA=="
)
SERIAL = "01P00A000000000"
X1C = "00M00A000000000"
A1_MINI = "03000A000000000"


def test_the_serial_is_the_subjects_common_name_not_the_issuers():
    assert discovery.serial_from_certificate(LEAF) == SERIAL


@pytest.mark.parametrize("junk", [b"", b"\x00", b"\x30\x03\x01\x01\x00", LEAF[:40], b"not a certificate at all"])
def test_something_that_is_not_a_certificate_has_no_serial(junk):
    assert discovery.serial_from_certificate(junk) is None


@pytest.mark.parametrize(
    ("host", "network"),
    [
        ("192.168.1.3", "192.168.1.0/24"),
        ("10.4.5.6", "10.4.5.0/24"),
        ("172.20.9.1", "172.20.9.0/24"),
    ],
)
def test_the_network_to_search_is_the_one_the_page_was_opened_from(host, network):
    assert discovery.network_of(host) == network


@pytest.mark.parametrize("host", ["", "localhost", "trident.example.com", "8.8.8.8", "::1", "999.1.1.1", "127.0.0.1"])
def test_a_page_not_opened_from_a_private_address_gives_no_network_to_search(host):
    assert discovery.network_of(host) is None


def test_a_small_private_network_is_all_its_hosts():
    hosts = discovery.hosts_of("192.168.1.0/24")
    assert len(hosts) == 254 and hosts[0] == "192.168.1.1" and hosts[-1] == "192.168.1.254"
    assert len(discovery.hosts_of("192.168.0.0/22")) == 1022


@pytest.mark.parametrize(
    "network", ["8.8.8.0/24", "10.0.0.0/8", "192.168.0.0/16", "nonsense", "", "192.168.1.0/24 extra", "127.0.0.0/24"]
)
def test_only_small_private_networks_are_searched(network):
    with pytest.raises(ValueError):
        discovery.hosts_of(network)


def test_printers_are_found_by_the_serial_in_their_certificate():
    seen = {"192.168.1.45": SERIAL, "192.168.1.58": X1C, "192.168.1.134": "mqtt-client-6f1a"}

    async def probe(ip: str) -> str | None:
        return seen.get(ip)

    found = asyncio.run(discovery.find_printers("192.168.1.0/24", {SERIAL, X1C, A1_MINI}, probe=probe))
    assert found == {SERIAL: "192.168.1.45", X1C: "192.168.1.58"}


def test_a_host_that_is_not_one_of_the_accounts_printers_is_never_reported():
    async def probe(ip: str) -> str | None:
        return "SOMEONE-ELSES-PRINTER" if ip == "192.168.1.9" else None

    assert asyncio.run(discovery.find_printers("192.168.1.0/24", {SERIAL}, probe=probe)) == {}


def test_a_host_that_fails_to_answer_is_skipped():
    async def probe(ip: str) -> str | None:
        if ip.endswith(".5"):
            raise OSError("connection reset")
        return SERIAL if ip.endswith(".6") else None

    assert asyncio.run(discovery.find_printers("192.168.1.0/24", {SERIAL}, probe=probe)) == {SERIAL: "192.168.1.6"}


def test_nothing_is_probed_when_there_is_no_serial_to_look_for():
    probed: list[str] = []

    async def probe(ip: str) -> str | None:
        probed.append(ip)
        return None

    assert asyncio.run(discovery.find_printers("192.168.1.0/24", set(), probe=probe)) == {}
    assert probed == []


def test_a_network_that_is_not_allowed_is_refused_before_any_probe():
    async def probe(ip: str) -> str | None:
        raise AssertionError("must not be called")

    with pytest.raises(ValueError):
        asyncio.run(discovery.find_printers("8.8.8.0/24", {SERIAL}, probe=probe))


def test_a_closed_port_is_quickly_nothing():
    async def scenario():
        server = await asyncio.start_server(lambda reader, writer: None, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        server.close()
        await server.wait_closed()
        return await discovery.probe_host("127.0.0.1", port)

    assert asyncio.run(scenario()) is None


def test_a_host_that_accepts_but_never_speaks_tls_is_nothing(monkeypatch):
    monkeypatch.setattr(discovery, "HANDSHAKE_TIMEOUT_S", 0.3)

    async def scenario():
        async def idle(reader, writer):
            await asyncio.sleep(5)

        server = await asyncio.start_server(idle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            return await discovery.probe_host("127.0.0.1", port)
        finally:
            server.close()

    assert asyncio.run(scenario()) is None


def test_a_printer_gets_longer_to_answer_than_a_host_that_is_not_there():
    # Printers take about a second to finish a TLS handshake; a host that does not answer at all must not be waited for that long.
    assert discovery.HANDSHAKE_TIMEOUT_S >= 3 * discovery.TCP_TIMEOUT_S


def test_the_searching_stops_asking_once_every_serial_is_found():
    asked: list[str] = []

    async def probe(ip: str) -> str | None:
        asked.append(ip)
        return SERIAL if ip == "192.168.1.1" else None

    asyncio.run(discovery.find_printers("192.168.1.0/24", {SERIAL}, probe=probe))
    assert len(asked) < 254
