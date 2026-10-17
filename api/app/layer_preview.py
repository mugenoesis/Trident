"""Layer previews of a resin job, and the peel warning that comes from them.

The job's own file is in the printer's format, which the app cannot read back. A preview is the same slice written once more as an SL1
archive (a zip of PNG layers, which the engine writes for any printer), made by itself after a resin job succeeds and kept in
<job output>/preview/ with a state.json that says whether it is running, ready or failed. Layers are read straight out of the zip, one at
a time. The PNGs are also measured: the largest layer's area, in square centimetres, decides the peel warning.
"""

from __future__ import annotations

import io
import json
import threading
import zipfile
from pathlib import Path
from typing import Any

from PIL import Image

from . import resin as resin_module
from . import resin_runner

PREVIEW_DIR = "preview"
ARCHIVE_FORMAT = "SL1"
ARCHIVE_NAME = "plate_1.sl1"

# A layer of cured resin peels off the film in one go, and the force grows with its area, so a large solid layer is where a print
# fails or a film tears. The limit is a rule of thumb of this app, not a figure from any resin or printer maker.
PEEL_WARNING_CM2 = 20.0

_lock = threading.Lock()
_running: set[str] = set()


def _state_path(out: Path) -> Path:
    return out / PREVIEW_DIR / "state.json"


def _write(out: Path, **state: Any) -> None:
    path = _state_path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state))


def status(out: Path) -> dict[str, Any]:
    """The state of the preview: status none | running | ready | failed, and for a ready one its layers and peel figures."""
    try:
        state = json.loads(_state_path(out).read_text())
    except (OSError, ValueError):
        return {"status": "none"}
    if state.get("status") == "running" and str(out) not in _running:
        # the process that was making it is gone (the app was restarted)
        return {"status": "failed", "error": "The preview was interrupted; ask for it again"}
    return state


def begin(out: Path) -> bool:
    """Mark a preview as running; False when one is already running or ready (nothing to start)."""
    with _lock:
        if status(out)["status"] in ("running", "ready"):
            return False
        _running.add(str(out))
        _write(out, status="running")
        return True


def _finish_failed(out: Path, error: str) -> None:
    _write(out, status="failed", error=error)
    _running.discard(str(out))


def _png_names(archive: zipfile.ZipFile) -> list[str]:
    return sorted(n for n in archive.namelist() if n.lower().endswith(".png"))


def measure(archive_path: Path, display_mm: tuple[float, float]) -> tuple[int, int, float]:
    """(layer count, index of the largest layer, its area in cm2) of an SL1 archive on a screen of this size in mm."""
    peak_layer, peak_mm2 = 0, 0.0
    with zipfile.ZipFile(archive_path) as archive:
        names = _png_names(archive)
        for index, name in enumerate(names):
            with Image.open(io.BytesIO(archive.read(name))) as image:
                gray = image.convert("L")
                width, height = gray.size
                cured = sum(gray.histogram()[128:])
            area = cured * (display_mm[0] / width) * (display_mm[1] / height)
            if area > peak_mm2:
                peak_layer, peak_mm2 = index, area
    return len(names), peak_layer, peak_mm2 / 100


def generate(
    *,
    out: Path,
    model_path: Path,
    printer_name: str,
    resin_name: str | None,
    overrides: dict[str, Any],
    user_id: str | None,
) -> None:
    """Make the preview of a job whose state was just marked running by begin(); never raises."""
    try:
        result = resin_runner.run_resin_slice(
            model_path=model_path,
            output_dir=out / PREVIEW_DIR,
            printer_name=printer_name,
            resin_name=resin_name,
            setting_overrides=overrides,
            timeout_s=1800.0,
            user_id=user_id,
            archive_format=ARCHIVE_FORMAT,
        )
        if not result.succeeded:
            error = (result.result_json or {}).get("error_string") or result.stderr
            _finish_failed(out, error or f"exit code {result.return_code}")
            return
        count, peak_layer, peak_cm2 = measure(
            out / PREVIEW_DIR / ARCHIVE_NAME, resin_module.catalog.screen_mm(printer_name)
        )
        _write(
            out,
            status="ready",
            layer_count=count,
            peak_layer=peak_layer,
            peak_area_cm2=round(peak_cm2, 2),
            peel_warning=peak_cm2 > PEEL_WARNING_CM2,
            peel_warning_cm2=PEEL_WARNING_CM2,
        )
        _running.discard(str(out))
    except Exception as exc:
        _finish_failed(out, str(exc))


def layer_png(out: Path, index: int) -> bytes | None:
    """The PNG of layer `index` (from 0), or None when there is no such layer or no preview."""
    if status(out)["status"] != "ready" or index < 0:
        return None
    try:
        with zipfile.ZipFile(out / PREVIEW_DIR / ARCHIVE_NAME) as z:
            names = _png_names(z)
            return z.read(names[index]) if index < len(names) else None
    except (OSError, zipfile.BadZipFile):
        return None
