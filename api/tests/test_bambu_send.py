"""Sending a sliced print to a Bambu printer in LAN mode: the sliced 3MF is uploaded by FTPS and started by an MQTT command.

The command's fields follow the community's documentation of the protocol, and the way a file is named for it (`ftp:///name`, from the root of the
printer's storage) is the one reported to work best; none of it is Bambu's own documentation, so it is a thing to try on a real printer.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from app.bambu_link import BambuError
from app.bambu_send import md5_of, plate_path, project_file_command, upload


def _three_mf(tmp_path: Path, *names: str) -> Path:
    path = tmp_path / "sliced.gcode.3mf"
    with zipfile.ZipFile(path, "w") as z:
        for name in names:
            z.writestr(name, "; gcode\n" if name.endswith(".gcode") else "x")
    return path


# ---- which plate is in the 3MF ----


def test_the_plate_is_the_one_whose_gcode_is_in_the_3mf(tmp_path):
    path = _three_mf(tmp_path, "3D/3dmodel.model", "Metadata/plate_1.gcode", "Metadata/plate_1.gcode.md5")
    assert plate_path(path, None) == "Metadata/plate_1.gcode"


def test_with_several_plates_the_one_asked_for_is_used(tmp_path):
    path = _three_mf(tmp_path, "Metadata/plate_1.gcode", "Metadata/plate_2.gcode")
    assert plate_path(path, 2) == "Metadata/plate_2.gcode"
    assert plate_path(path, None) == "Metadata/plate_1.gcode"


def test_a_3mf_with_no_gcode_in_it_is_refused(tmp_path):
    path = _three_mf(tmp_path, "3D/3dmodel.model")
    with pytest.raises(BambuError, match="G-code"):
        plate_path(path, None)


def test_a_plate_that_is_not_in_it_is_refused(tmp_path):
    path = _three_mf(tmp_path, "Metadata/plate_1.gcode")
    with pytest.raises(BambuError, match="plate 3"):
        plate_path(path, 3)


# ---- the command that starts it ----


def test_the_start_command_names_the_file_the_plate_and_its_checksum():
    message = project_file_command(
        plate="Metadata/plate_1.gcode", remote_name="benchy.gcode.3mf", md5="abc123", use_ams=False
    )
    command = message["print"]
    assert command["command"] == "project_file"
    assert command["param"] == "Metadata/plate_1.gcode"
    assert command["file"] == "benchy.gcode.3mf"
    assert command["url"] == "ftp:///benchy.gcode.3mf"
    assert command["md5"] == "abc123"
    assert command["subtask_name"] == "benchy"
    assert command["use_ams"] is False
    assert command["bed_type"] == "auto"
    assert command["task_id"] == "0" and command["project_id"] == "0"  # always, for a print from a local file


def test_the_ams_is_used_from_its_first_slot_when_asked():
    command = project_file_command(plate="Metadata/plate_1.gcode", remote_name="a.gcode.3mf", md5="x", use_ams=True)[
        "print"
    ]
    assert command["use_ams"] is True
    assert command["ams_mapping"] == [0]


def test_a_files_checksum_is_its_md5(tmp_path):
    path = tmp_path / "x.3mf"
    path.write_bytes(b"hello")
    assert md5_of(path) == hashlib.md5(b"hello", usedforsecurity=False).hexdigest()


# ---- the upload ----


class FakeFtp:
    """What an FTPS client is asked, in order."""

    def __init__(self, fail: Exception | None = None):
        self.calls: list[tuple] = []
        self.fail = fail
        self.stored: bytes | None = None

    def connect(self, host, port, timeout=None):
        self.calls.append(("connect", host, port))
        if self.fail:
            raise self.fail
        return "220"

    def login(self, user, passwd):
        self.calls.append(("login", user, passwd))

    def prot_p(self):
        self.calls.append(("prot_p",))

    def storbinary(self, command, fp):
        self.calls.append(("storbinary", command))
        self.stored = fp.read()

    def quit(self):
        self.calls.append(("quit",))

    def close(self):
        self.calls.append(("close",))


def test_the_3mf_is_stored_in_the_root_over_ftps_as_bblp(tmp_path):
    path = tmp_path / "sliced.gcode.3mf"
    path.write_bytes(b"3mf bytes")
    ftp = FakeFtp()
    upload("192.168.1.50", "12345678", path, "benchy.gcode.3mf", ftp_factory=lambda: ftp)
    assert ftp.calls[0] == ("connect", "192.168.1.50", 990)
    assert ("login", "bblp", "12345678") in ftp.calls
    assert ("prot_p",) in ftp.calls
    assert ("storbinary", "STOR benchy.gcode.3mf") in ftp.calls
    assert ftp.stored == b"3mf bytes"
    assert ftp.calls[-1] in (("quit",), ("close",))


def test_an_address_with_a_port_for_mqtt_still_uploads_to_the_printer_itself(tmp_path):
    path = tmp_path / "s.3mf"
    path.write_bytes(b"x")
    ftp = FakeFtp()
    upload("192.168.1.50:8883", "12345678", path, "a.gcode.3mf", ftp_factory=lambda: ftp)
    assert ftp.calls[0][:2] == ("connect", "192.168.1.50")


def test_a_printer_that_cannot_be_reached_for_the_upload_says_so(tmp_path):
    path = tmp_path / "s.3mf"
    path.write_bytes(b"x")
    with pytest.raises(BambuError, match="reach"):
        upload("192.168.1.50", "12345678", path, "a.gcode.3mf", ftp_factory=lambda: FakeFtp(fail=OSError("timed out")))


def test_a_refused_login_is_said_to_be_the_access_code(tmp_path):
    import ftplib

    class Refusing(FakeFtp):
        def login(self, user, passwd):
            raise ftplib.error_perm("530 Login incorrect")  # noqa: S321 - the error of an FTPS client

    path = tmp_path / "s.3mf"
    path.write_bytes(b"x")
    with pytest.raises(BambuError, match="access code"):
        upload("192.168.1.50", "wrong", path, "a.gcode.3mf", ftp_factory=Refusing)


def test_a_name_that_could_climb_out_of_the_root_is_refused(tmp_path):
    path = tmp_path / "s.3mf"
    path.write_bytes(b"x")
    for bad in ("../x.3mf", "a/b.3mf", "a b;DELE.3mf\r\n", ""):
        with pytest.raises(BambuError, match="name"):
            upload("192.168.1.50", "12345678", path, bad, ftp_factory=FakeFtp)


class SilentAfterUpload(FakeFtp):
    """A P1 or an A1: it takes the whole file and then never sends the 'transfer complete' reply."""

    def storbinary(self, command, fp):
        super().storbinary(command, fp)
        raise TimeoutError("The read operation timed out")


class SizeCheck(FakeFtp):
    """A second connection that is only asked how big the file on the printer is."""

    def __init__(self, size: int | None = None, fail: Exception | None = None):
        super().__init__(fail=fail)
        self._size = size

    def voidcmd(self, cmd):
        self.calls.append(("voidcmd", cmd))

    def size(self, name):
        self.calls.append(("size", name))
        return self._size


def _factory(*connections):
    queue = iter(connections)
    return lambda: next(queue)


def test_a_printer_that_never_sends_the_final_reply_but_has_the_whole_file_is_a_success(tmp_path):
    path = tmp_path / "s.3mf"
    path.write_bytes(b"3mf bytes")
    check = SizeCheck(size=9)
    upload("192.168.1.45", "12345678", path, "a.gcode.3mf", ftp_factory=_factory(SilentAfterUpload(), check))
    assert ("login", "bblp", "12345678") in check.calls and ("size", "a.gcode.3mf") in check.calls
    assert ("voidcmd", "TYPE I") in check.calls


def test_a_file_that_is_not_all_there_after_the_silence_is_a_failure(tmp_path):
    path = tmp_path / "s.3mf"
    path.write_bytes(b"3mf bytes")
    for size in (3, 0, None):
        with pytest.raises(BambuError, match="did not confirm"):
            upload(
                "192.168.1.45",
                "12345678",
                path,
                "a.gcode.3mf",
                ftp_factory=_factory(SilentAfterUpload(), SizeCheck(size=size)),
            )


def test_a_check_that_cannot_be_made_after_the_silence_is_a_failure(tmp_path):
    path = tmp_path / "s.3mf"
    path.write_bytes(b"3mf bytes")
    with pytest.raises(BambuError, match="did not confirm"):
        upload(
            "192.168.1.45",
            "12345678",
            path,
            "a.gcode.3mf",
            ftp_factory=_factory(SilentAfterUpload(), SizeCheck(fail=OSError("no route"))),
        )


def test_a_timeout_before_anything_was_sent_is_still_a_printer_that_cannot_be_reached(tmp_path):
    path = tmp_path / "s.3mf"
    path.write_bytes(b"x")
    with pytest.raises(BambuError, match="reach"):
        upload(
            "192.168.1.45", "12345678", path, "a.gcode.3mf", ftp_factory=lambda: FakeFtp(fail=TimeoutError("timed out"))
        )


def _unused(_: io.BytesIO) -> None:  # keeps the io import honest for the zip helper above
    return None
