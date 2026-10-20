"""A Bambu printer's camera in LAN mode: one picture at a time.

An A1 or a P1 serves JPEG pictures over a TLS socket on port 6000 (after a small login packet); an X1 serves an RTSPS video stream on port 322, of
which one frame is taken. Both are documented by Bambu's users, not by Bambu, so the byte layouts here are what is reported, to be tried on a real
printer. The tests use stand-ins for the socket and for the video library.
"""

from __future__ import annotations

import io
import struct

import pytest
from PIL import Image

from app.bambu_camera import (
    JPEG_PORT,
    RTSP_PORT,
    auth_packet,
    camera_family,
    jpeg_snapshot,
    rtsp_snapshot,
    snapshot_url,
)
from app.bambu_link import BambuError

CODE = "12345678"


def _jpeg(color=(200, 30, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, format="JPEG")
    return buffer.getvalue()


# ---- which kind of camera a printer has ----


@pytest.mark.parametrize("serial", ["00M00A123456789", "03W00X123456789", "09400A123456789"])
def test_x1_and_h2_printers_have_the_rtsp_camera(serial):
    assert camera_family(serial) == "rtsp"


@pytest.mark.parametrize("serial", ["01P00A123456789", "01S00C123456789", "03000A123456789", "03900A123456789"])
def test_p1_and_a1_printers_have_the_jpeg_camera(serial):
    assert camera_family(serial) == "jpeg"


def test_a_serial_number_not_known_is_tried_both_ways():
    assert camera_family("99X00A123456789") is None
    assert camera_family("") is None


# ---- the JPEG camera of an A1 or a P1 ----


class FakeSocket:
    """A TLS socket that has been sent what it was sent, and gives back the bytes it was loaded with."""

    def __init__(self, incoming: bytes):
        self.incoming = bytearray(incoming)
        self.sent = bytearray()
        self.closed = False

    def sendall(self, data):
        self.sent += data

    def recv(self, n):
        chunk = bytes(self.incoming[:n])
        del self.incoming[:n]
        return chunk

    def close(self):
        self.closed = True


def _frame(jpeg: bytes) -> bytes:
    return struct.pack("<I", len(jpeg)) + b"\x00" * 12 + jpeg  # a 16-byte header: the size, then what we do not use


def test_the_login_packet_is_80_bytes_with_the_user_and_the_access_code_padded_to_32():
    packet = auth_packet(CODE)
    assert len(packet) == 80
    assert packet[:16] == struct.pack("<IIII", 0x40, 0x3000, 0, 0)
    assert packet[16:48] == b"bblp".ljust(32, b"\x00")
    assert packet[48:80] == CODE.encode().ljust(32, b"\x00")


def test_a_picture_is_what_follows_the_login_and_a_16_byte_header():
    picture = _jpeg()
    sock = FakeSocket(_frame(picture))
    assert jpeg_snapshot("192.168.1.50", CODE, connect=lambda host, port: sock) == picture
    assert bytes(sock.sent) == auth_packet(CODE)
    assert sock.closed is True


def test_it_connects_to_port_6000_of_the_printer():
    seen = []

    def connect(host, port):
        seen.append((host, port))
        return FakeSocket(_frame(_jpeg()))

    jpeg_snapshot("192.168.1.50:8883", CODE, connect=connect)  # the MQTT port in the saved address is not the camera's
    assert seen == [("192.168.1.50", JPEG_PORT)]


def test_something_that_is_not_a_picture_is_refused():
    with pytest.raises(BambuError, match="picture"):
        jpeg_snapshot("h", CODE, connect=lambda host, port: FakeSocket(_frame(b"not a jpeg at all")))


def test_a_size_that_cannot_be_right_is_refused():
    huge = struct.pack("<I", 200 * 1024 * 1024) + b"\x00" * 12
    with pytest.raises(BambuError, match="picture"):
        jpeg_snapshot("h", CODE, connect=lambda host, port: FakeSocket(huge))


def test_a_printer_that_stops_answering_is_said_to_be():
    with pytest.raises(BambuError, match="camera"):
        jpeg_snapshot("h", CODE, connect=lambda host, port: FakeSocket(b"\x10\x00"))


def test_a_printer_whose_camera_is_off_is_said_to_be():
    def refuse(host, port):
        raise ConnectionRefusedError("refused")

    with pytest.raises(BambuError, match="LAN mode liveview"):
        jpeg_snapshot("h", CODE, connect=refuse)


# ---- the RTSPS camera of an X1 ----


class FakeFrame:
    def to_image(self):
        return Image.new("RGB", (16, 9), (10, 200, 10))


class FakeContainer:
    def __init__(self, frames=1, fail: Exception | None = None):
        self.frames = frames
        self.fail = fail
        self.closed = False

    def decode(self, video=0):
        if self.fail:
            raise self.fail
        for _ in range(self.frames):
            yield FakeFrame()

    def close(self):
        self.closed = True


def test_the_stream_address_is_rtsps_on_322_with_the_user_and_the_code():
    assert snapshot_url("192.168.1.50", CODE) == f"rtsps://bblp:{CODE}@192.168.1.50:{RTSP_PORT}/streaming/live/1"
    assert snapshot_url("192.168.1.50:8883", CODE).startswith(f"rtsps://bblp:{CODE}@192.168.1.50:322/")


def test_a_frame_of_the_stream_is_made_a_jpeg():
    seen = {}

    def open_stream(url, **options):
        seen.update(url=url, options=options)
        return FakeContainer()

    data = rtsp_snapshot("192.168.1.50", CODE, open_stream=open_stream)
    assert Image.open(io.BytesIO(data)).format == "JPEG"
    assert seen["url"] == snapshot_url("192.168.1.50", CODE)
    assert seen["options"]["options"]["rtsp_transport"] == "tcp"


def test_the_stream_is_closed_again():
    container = FakeContainer()
    rtsp_snapshot("192.168.1.50", CODE, open_stream=lambda url, **o: container)
    assert container.closed is True


def test_a_stream_with_no_frame_is_said_to_have_none():
    with pytest.raises(BambuError, match="no picture"):
        rtsp_snapshot("h", CODE, open_stream=lambda url, **o: FakeContainer(frames=0))


def test_a_stream_that_cannot_be_opened_does_not_give_away_the_access_code():
    def failing(url, **o):
        raise OSError(f"could not open {url}")

    with pytest.raises(BambuError) as caught:
        rtsp_snapshot("192.168.1.50", CODE, open_stream=failing)
    assert CODE not in str(caught.value)
    assert "LAN mode liveview" in str(caught.value)


# ---- which camera is used ----


def test_a_p1_or_a1_is_asked_for_a_jpeg_and_an_x1_for_a_video_frame(monkeypatch):
    from app import bambu_camera

    monkeypatch.setattr(bambu_camera, "jpeg_snapshot", lambda host, code, **k: b"jpeg")
    monkeypatch.setattr(bambu_camera, "rtsp_snapshot", lambda host, code, **k: b"rtsp")
    assert bambu_camera.take_snapshot("h", "01P00A123456789", CODE) == b"jpeg"
    assert bambu_camera.take_snapshot("h", "00M00A123456789", CODE) == b"rtsp"


def test_a_serial_number_not_known_is_tried_as_a_jpeg_camera_and_then_as_a_video_one(monkeypatch):
    from app import bambu_camera

    def no_jpeg(host, code, **k):
        raise BambuError("The camera is not answering")

    monkeypatch.setattr(bambu_camera, "jpeg_snapshot", no_jpeg)
    monkeypatch.setattr(bambu_camera, "rtsp_snapshot", lambda host, code, **k: b"rtsp")
    assert bambu_camera.take_snapshot("h", "99X00A123456789", CODE) == b"rtsp"


def test_a_picture_taken_a_moment_ago_is_given_again_instead_of_asking_the_printer_again(monkeypatch):
    import asyncio

    from app import bambu_camera

    now = [100.0]
    calls = []
    monkeypatch.setattr(bambu_camera, "_clock", lambda: now[0])
    monkeypatch.setattr(bambu_camera, "take_snapshot", lambda host, serial, code: calls.append(1) or b"picture")
    bambu_camera._CACHE.clear()
    row = {"print_host": "192.168.1.50", "device_id": "01P00A123456789", "printhost_apikey": CODE}
    assert asyncio.run(bambu_camera.snapshot(row)) == (b"picture", "image/jpeg")
    assert asyncio.run(bambu_camera.snapshot(row)) == (b"picture", "image/jpeg")
    assert len(calls) == 1
    now[0] += 5
    asyncio.run(bambu_camera.snapshot(row))
    assert len(calls) == 2
