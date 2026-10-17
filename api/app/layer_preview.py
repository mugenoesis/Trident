"""Layer previews of a resin job.

The job's own file is in the printer's format, which the app cannot read back. A preview is the same slice written once more as an
SL1 archive (zip of PNG layers, which the engine writes for any printer), kept in <job output>/preview/ with a state.json that says
whether it is running, ready or failed. Layers are read straight out of the zip, one at a time.
"""

from __future__ import annotations

import json
import threading
import zipfile
from pathlib import Path
from typing import Any

PREVIEW_DIR = "preview"
ARCHIVE_FORMAT = "SL1"
ARCHIVE_NAME = "plate_1.sl1"

_lock = threading.Lock()
_running: set[str] = set()


def _state_path(out: Path) -> Path:
    return out / PREVIEW_DIR / "state.json"


def _write(out: Path, **state: Any) -> None:
    path = _state_path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state))


def status(out: Path) -> dict[str, Any]:
    """{"status": none | running | ready | failed, "layer_count", "error"}."""
    try:
        state = json.loads(_state_path(out).read_text())
    except (OSError, ValueError):
        return {"status": "none", "layer_count": None, "error": None}
    if state.get("status") == "running" and str(out) not in _running:
        # the process that was making it is gone (the app was restarted)
        return {"status": "failed", "layer_count": None, "error": "The preview was interrupted; ask for it again"}
    return {"status": state["status"], "layer_count": state.get("layer_count"), "error": state.get("error")}


def begin(out: Path) -> bool:
    """Mark a preview as running; False when one is already running or ready (nothing to start)."""
    with _lock:
        if status(out)["status"] in ("running", "ready"):
            return False
        _running.add(str(out))
        _write(out, status="running")
        return True


def finish_ready(out: Path, layer_count: int) -> None:
    _write(out, status="ready", layer_count=layer_count)
    _running.discard(str(out))


def finish_failed(out: Path, error: str) -> None:
    _write(out, status="failed", error=error)
    _running.discard(str(out))


def count_layers(archive: Path) -> int:
    with zipfile.ZipFile(archive) as z:
        return sum(1 for name in z.namelist() if name.lower().endswith(".png"))


def layer_png(out: Path, index: int) -> bytes | None:
    """The PNG of layer `index` (from 0), or None when there is no such layer or no preview."""
    if status(out)["status"] != "ready" or index < 0:
        return None
    try:
        with zipfile.ZipFile(out / PREVIEW_DIR / ARCHIVE_NAME) as z:
            names = sorted(n for n in z.namelist() if n.lower().endswith(".png"))
            return z.read(names[index]) if index < len(names) else None
    except (OSError, zipfile.BadZipFile):
        return None
