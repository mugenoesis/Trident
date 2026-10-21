"""Finding where a Bambu printer is on the local network, from the serial number in its certificate.

A Bambu printer's MQTT port (8883) answers a TLS handshake with a certificate whose subject is the printer's serial number. So a printer
can be found without sending it, or anything else on the network, a password: connect, read the certificate, and keep the host only if the
serial is one the Bambu account lists. Nothing is ever sent after the handshake, and only small private networks are searched.
"""

from __future__ import annotations

import asyncio
import ipaddress
import ssl
from collections.abc import Awaitable, Callable
from contextlib import suppress

MQTT_PORT = 8883
MAX_HOSTS = 1024  # a /22
CONCURRENCY = 64
TCP_TIMEOUT_S = 0.8  # a host that does not even answer on the port is skipped quickly
HANDSHAKE_TIMEOUT_S = 5.0  # a printer needs about a second to finish a TLS handshake (seen on an X1C)
_COMMON_NAME = b"\x55\x04\x03"  # the OID of "commonName" in a certificate's subject


def _tlv(data: bytes, pos: int) -> tuple[int, int, int]:
    """One DER element: (tag, where its value starts, where it ends)."""
    if pos + 2 > len(data):
        raise ValueError("truncated")
    tag, first = data[pos], data[pos + 1]
    pos += 2
    if first < 0x80:
        length = first
    else:
        count = first & 0x7F
        if count == 0 or count > 4 or pos + count > len(data):
            raise ValueError("bad length")
        length = int.from_bytes(data[pos : pos + count], "big")
        pos += count
    if pos + length > len(data):
        raise ValueError("truncated")
    return tag, pos, pos + length


def _children(data: bytes, start: int, end: int) -> list[tuple[int, int, int]]:
    found = []
    while start < end:
        tag, value_start, value_end = _tlv(data, start)
        found.append((tag, value_start, value_end))
        start = value_end
    return found


def _common_name(data: bytes, start: int, end: int) -> str | None:
    """The commonName in a certificate's subject (a sequence of sets of {OID, value} pairs)."""
    for _, set_start, set_end in _children(data, start, end):
        for _, pair_start, pair_end in _children(data, set_start, set_end):
            oid, value = _children(data, pair_start, pair_end)[:2]
            if data[oid[1] : oid[2]] == _COMMON_NAME:
                return data[value[1] : value[2]].decode("utf-8")
    return None


def serial_from_certificate(der: bytes) -> str | None:
    """The subject's common name of a DER certificate (a Bambu printer's serial number), or None if it is not one."""
    try:
        tag, start, end = _tlv(der, 0)
        if tag != 0x30:
            return None
        tbs_tag, tbs_start, tbs_end = _tlv(der, start)
        if tbs_tag != 0x30 or tbs_end > end:
            return None
        fields = _children(der, tbs_start, tbs_end)
        first = 1 if fields[0][0] == 0xA0 else 0  # skip the optional version
        # serial number, signature algorithm, issuer, validity, then the subject
        _, subject_start, subject_end = fields[first + 4]
        return _common_name(der, subject_start, subject_end)
    except (ValueError, IndexError):
        return None


def network_of(host: str) -> str | None:
    """The /24 around a private IPv4 address (the one a page was opened from), or None for anything else."""
    try:
        address = ipaddress.IPv4Address(host)
    except ValueError:
        return None
    if not address.is_private or address.is_loopback or address.is_link_local:
        return None
    return str(ipaddress.IPv4Network(f"{host}/24", strict=False))


def hosts_of(network: str) -> list[str]:
    """Every host of a private network of at most /22; anything else (public, loopback, bigger, not a network) is a ValueError."""
    net = ipaddress.IPv4Network(network.strip(), strict=False)
    if not net.is_private or net.is_loopback or net.is_link_local:
        raise ValueError("Only a private network can be searched")
    if net.num_addresses > MAX_HOSTS:
        raise ValueError("That network is too big to search (at most a /22)")
    return [str(host) for host in net.hosts()]


async def _port_open(ip: str, port: int) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), TCP_TIMEOUT_S)
    except (OSError, TimeoutError):
        return False
    writer.close()
    with suppress(OSError):
        await writer.wait_closed()
    return True


async def probe_host(ip: str, port: int = MQTT_PORT) -> str | None:
    """The serial number in the certificate a host presents on the MQTT port, or None. Only the TLS handshake happens."""
    if not await _port_open(ip, port):
        return None  # most addresses of a network have nothing there: do not wait for a handshake that will never come
    # Reading the certificate is the whole point, so it is deliberately not verified; nothing is sent over the connection.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    writer = None
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port, ssl=context, ssl_handshake_timeout=HANDSHAKE_TIMEOUT_S),
            HANDSHAKE_TIMEOUT_S + TCP_TIMEOUT_S,
        )
        ssl_object = writer.get_extra_info("ssl_object")
        der = ssl_object.getpeercert(binary_form=True) if ssl_object else None
        return serial_from_certificate(der) if der else None
    except (OSError, TimeoutError, ssl.SSLError):
        return None
    finally:
        if writer is not None:
            writer.close()
            with suppress(OSError, ssl.SSLError):
                await writer.wait_closed()


async def _answer(probe: Callable[[str], Awaitable[str | None]], ip: str) -> str | None:
    try:
        return await probe(ip)
    except (OSError, TimeoutError, ssl.SSLError, ValueError):
        return None  # one host failing never stops the search


async def find_printers(
    network: str, serials: set[str], *, probe: Callable[[str], Awaitable[str | None]] = probe_host
) -> dict[str, str]:
    """{serial: IP address} for the serials found on `network`. Hosts are asked in batches, and the search ends once every serial is found."""
    hosts = hosts_of(network)
    wanted = set(serials)
    found: dict[str, str] = {}
    if not wanted:
        return found
    for begin in range(0, len(hosts), CONCURRENCY):
        batch = hosts[begin : begin + CONCURRENCY]
        for ip, serial in zip(batch, await asyncio.gather(*(_answer(probe, ip) for ip in batch)), strict=True):
            if serial in wanted and serial not in found:
                found[serial] = ip
        if len(found) == len(wanted):
            break
    return found
