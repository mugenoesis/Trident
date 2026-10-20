"""Sending a sliced print to a Bambu printer in LAN / Developer mode: the sliced 3MF (`.gcode.3mf`, which the slicer exports for Bambu machines) is
uploaded by FTPS to the printer's storage, and an MQTT command starts it.

FTPS is implicit TLS on port 990 (user `bblp`, the access code as the password), and the file goes in the root of the storage, named in the start
command as `ftp:///<name>`: the way that is reported to work best across the models (uploads under `cache/` and `file:///sdcard/…` names are reported
not to start on an A1). Bambu's protocol is documented by its users, not by Bambu, so the fields below are the documented ones and this is a thing to
try on a real printer.
"""

from __future__ import annotations

import ftplib
import hashlib
import re
import socket
import ssl
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .bambu_link import BambuError, split_host

FTPS_PORT = 990
_PLATE = re.compile(r"^Metadata/plate_(\d+)\.gcode$")
# What a file name on the printer may be made of: no path, nothing that could end the FTP command and start another.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_()\-][A-Za-z0-9_.()\- ]{0,120}$")


def remote_name(print_name: str) -> str:
    """The name a print is stored under on the printer: its own name made safe, with `.gcode.3mf` on it."""
    stem = re.sub(r"[^A-Za-z0-9_()\- ]+", "_", print_name).strip(" _.")[:80]
    return f"{stem or 'print'}.gcode.3mf"


def plate_path(three_mf: Path, plate_index: int | None) -> str:
    """The path of the plate's G-code inside the 3MF (what the start command's `param` is): the plate asked for, else the first one."""
    with zipfile.ZipFile(three_mf) as z:
        plates = sorted((int(m.group(1)), m.group(0)) for name in z.namelist() if (m := _PLATE.match(name)))
    if not plates:
        raise BambuError("There is no G-code in the sliced 3MF, so there is nothing to print")
    if plate_index is None:
        return plates[0][1]
    for number, path in plates:
        if number == plate_index:
            return path
    raise BambuError(f"The sliced 3MF has no plate {plate_index}")


def md5_of(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)  # the printer checks the file by its md5
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def project_file_command(*, plate: str, remote_name: str, md5: str, use_ams: bool) -> dict[str, Any]:
    """The MQTT message that starts the uploaded print. The ids are always "0" for a print from a local file; the first AMS slot is used when asked."""
    return {
        "print": {
            "sequence_id": "0",
            "command": "project_file",
            "param": plate,
            "project_id": "0",
            "profile_id": "0",
            "task_id": "0",
            "subtask_id": "0",
            "subtask_name": remote_name.removesuffix(".gcode.3mf"),
            "file": remote_name,
            "url": f"ftp:///{remote_name}",
            "md5": md5,
            "timelapse": False,
            "bed_type": "auto",
            "bed_levelling": True,
            "flow_cali": True,
            "vibration_cali": True,
            "layer_inspect": True,
            "ams_mapping": [0] if use_ams else "",
            "use_ams": use_ams,
        }
    }


class ImplicitFtps(ftplib.FTP_TLS):
    """FTP over TLS from the first byte (port 990), as a printer speaks it: the control connection is wrapped in TLS as soon as it is made, before the
    server's greeting is read. Its data connections reuse the control connection's TLS session, which the printer insists on.
    """

    _wrapped: Any = None

    @property
    def sock(self) -> Any:  # pyright: ignore[reportIncompatibleVariableOverride]
        return self._wrapped

    @sock.setter
    def sock(self, value: Any) -> None:  # pyright: ignore[reportIncompatibleVariableOverride]
        if value is not None and not isinstance(value, ssl.SSLSocket):
            value = self.context.wrap_socket(value)
        self._wrapped = value

    def ntransfercmd(self, cmd: str, rest: Any = None) -> tuple[socket.socket, int | None]:
        # an FTPS client: the data connection is wrapped in TLS just below
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)  # noqa: S321
        if getattr(self, "_prot_p", False):
            conn = self.context.wrap_socket(conn, server_hostname=self.host, session=self.sock.session)
        return conn, size


def _new_ftps() -> ftplib.FTP_TLS:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # a printer's certificate is its own, so there is nothing to check it against
    return ImplicitFtps(context=context)


def upload(host: str, code: str, path: Path, name: str, *, ftp_factory: Callable[[], Any] | None = None) -> None:
    """Stores a file in the root of the printer's storage over FTPS. `host` may carry the MQTT port: the upload goes to the printer itself."""
    if not _SAFE_NAME.match(name):
        raise BambuError("That file name cannot be sent to the printer")
    ftp = (ftp_factory or _new_ftps)()
    try:
        try:
            ftp.connect(split_host(host)[0], FTPS_PORT, timeout=15)
            ftp.login("bblp", code)
            ftp.prot_p()
            with path.open("rb") as f:
                ftp.storbinary(f"STOR {name}", f)
        except ftplib.error_perm as exc:
            if str(exc).startswith("530"):
                raise BambuError("The printer refused the access code (check it on the printer's screen)") from exc
            raise BambuError(f"The printer refused the upload: {exc}") from exc
        except (OSError, ftplib.Error) as exc:
            raise BambuError(f"Couldn't reach the printer to upload to it: {exc}") from exc
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()
