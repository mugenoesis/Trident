"""A Bambu printer's camera in LAN mode: one picture at a time.

An A1 or a P1 serves JPEG pictures over a TLS socket on port 6000, after a small login packet; an X1 (and the H2 printers) serve an RTSPS video
stream on port 322, of which one frame is taken. The printer must have LAN mode liveview switched on. Both are documented by Bambu's users, not by
Bambu, so the byte layouts below are what is reported and are to be tried on a real printer.
"""

from __future__ import annotations

import asyncio
import io
import socket
import ssl
import struct
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from .bambu_link import BambuError, connection_of, split_host

JPEG_PORT = 6000
RTSP_PORT = 322
# What a serial number starts with, by the camera the printer has (X1 Carbon, X1E, H2D, H2S, H2C | P1S, P1P, A1 mini, A1).
_RTSP_SERIALS = ("00M", "03W", "094", "093", "31B")
_JPEG_SERIALS = ("01P", "01S", "030", "039")
_MAX_PICTURE = 5 * 1024 * 1024
_TIMEOUT = 8.0
# A picture taken less than this long ago is given again (several cards or tabs may ask at once).
_REUSE_SECONDS = 1.0
_LIVEVIEW = "is LAN mode liveview switched on in the printer's settings?"
_clock: Callable[[], float] = time.monotonic
_CACHE: dict[str, tuple[float, bytes]] = {}


def camera_family(serial: str) -> str | None:
    """ "rtsp" for an X1 or H2, "jpeg" for a P1 or A1, and None for a serial number not known (which is tried both ways)."""
    if serial.startswith(_RTSP_SERIALS):
        return "rtsp"
    if serial.startswith(_JPEG_SERIALS):
        return "jpeg"
    return None


def auth_packet(code: str) -> bytes:
    """The login for the JPEG camera: 80 bytes, four 32-bit numbers (0x40, 0x3000, 0, 0), then the user and the access code, each padded to 32."""
    return struct.pack("<IIII", 0x40, 0x3000, 0, 0) + b"bblp".ljust(32, b"\x00") + code.encode()[:32].ljust(32, b"\x00")


def _tls_connect(host: str, port: int) -> Any:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # a printer's certificate is its own
    return context.wrap_socket(socket.create_connection((host, port), timeout=_TIMEOUT))


def _read_exact(sock: Any, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise BambuError("The camera stopped answering")
        data += chunk
    return bytes(data)


def jpeg_snapshot(address: str, code: str, *, connect: Callable[[str, int], Any] | None = None) -> bytes:
    """One picture from an A1 or a P1: log in, then the first frame (a 16-byte header that starts with its size, and the JPEG)."""
    try:
        sock = (connect or _tls_connect)(split_host(address)[0], JPEG_PORT)
    except OSError as exc:
        raise BambuError(f"Couldn't reach the camera ({exc}): {_LIVEVIEW}") from exc
    try:
        try:
            sock.sendall(auth_packet(code))
            size = int.from_bytes(_read_exact(sock, 16)[:4], "little")
            if not 0 < size <= _MAX_PICTURE:
                raise BambuError("The camera did not send a picture")
            picture = _read_exact(sock, size)
        except (OSError, ssl.SSLError) as exc:
            raise BambuError(f"The camera stopped answering ({exc})") from exc
    finally:
        sock.close()
    if not (picture.startswith(b"\xff\xd8") and picture.endswith(b"\xff\xd9")):
        raise BambuError("The camera did not send a picture")
    return picture


def snapshot_url(address: str, code: str) -> str:
    return f"rtsps://bblp:{quote(code, safe='')}@{split_host(address)[0]}:{RTSP_PORT}/streaming/live/1"


def _open_stream(url: str, **options: Any) -> Any:
    try:
        import av  # imported here: only an X1 or H2 camera needs it
    except ImportError as exc:
        raise BambuError("This build cannot read this printer's camera (its video library is missing)") from exc
    return av.open(url, **options)


def rtsp_snapshot(address: str, code: str, *, open_stream: Callable[..., Any] | None = None) -> bytes:
    """One picture from an X1 or an H2: the first frame of its RTSPS stream, as a JPEG."""
    url = snapshot_url(address, code)
    container = None
    try:
        container = (open_stream or _open_stream)(url, options={"rtsp_transport": "tcp"}, timeout=_TIMEOUT + 2)
        for frame in container.decode(video=0):
            buffer = io.BytesIO()
            frame.to_image().save(buffer, format="JPEG", quality=80)
            return buffer.getvalue()
    except BambuError:
        raise
    except Exception as exc:
        # the library puts the address it was given, with the access code in it, in its messages: it is not repeated
        raise BambuError(f"The camera is not answering ({str(exc).replace(code, '***')}): {_LIVEVIEW}") from exc
    finally:
        if container is not None:
            container.close()
    raise BambuError("The camera sent no picture")


def take_snapshot(address: str, serial: str, code: str) -> bytes:
    """One picture, from the camera the printer has (a serial number not known is tried as a JPEG camera, then as a video one)."""
    family = camera_family(serial)
    if family == "jpeg":
        return jpeg_snapshot(address, code)
    if family == "rtsp":
        return rtsp_snapshot(address, code)
    try:
        return jpeg_snapshot(address, code)
    except BambuError:
        return rtsp_snapshot(address, code)


async def snapshot(row: Any) -> tuple[bytes, str]:
    """One picture from a saved Bambu printer's camera: the picture and its type."""
    host, serial, code = connection_of(row)
    cached = _CACHE.get(host)
    if cached and _clock() - cached[0] < _REUSE_SECONDS:
        return cached[1], "image/jpeg"
    picture = await asyncio.to_thread(take_snapshot, host, serial, code)
    _CACHE[host] = (_clock(), picture)
    return picture, "image/jpeg"
