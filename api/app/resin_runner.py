"""Slicing for a resin (MSLA) printer through the engine's command line.

The engine slices a model for a printer preset with printer_technology = SLA to the printer's own file (plate_1.<ext>) and
writes result.json with printer_technology, archive_file, archive_format, layer_count, layer_height_mm,
estimated_print_time_s and resin_used_ml. See the engine's docs/resin-materials.md for how a resin file is used:
--load-filaments names it, and a value in the process profile (the overrides here) still wins over the resin.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

from . import resin as resin_module
from .cli_runner import ProgressCallback, SliceResult, _read_result_json
from .config import settings
from .schemas import JobProgress

logger = logging.getLogger(__name__)

# What the user may set for a resin slice: the printer-independent SLA process settings and the resin's own values.
RESIN_OVERRIDE_KEYS = frozenset(
    {
        *resin_module.ROW_KEYS,
        "layer_height",
        "initial_layer_height",
        "supports_enable",
        "support_head_front_diameter",
        "support_head_penetration",
        "support_head_width",
        "support_pillar_diameter",
        "support_small_pillar_diameter_percent",
        "support_base_diameter",
        "support_base_height",
        "support_critical_angle",
        "support_max_bridge_length",
        "support_max_pillar_link_distance",
        "support_points_density_relative",
        "support_points_minimal_distance",
        "support_tree_type",
        "pad_enable",
        "pad_wall_thickness",
        "pad_wall_height",
        "pad_brim_size",
        "pad_max_merge_distance",
        "pad_zero_elevation",
        "hollowing_enable",
        "hollowing_min_thickness",
        "hollowing_quality",
        "hollowing_closing_distance",
        "fill_closed_cavities",
        "gamma_correction",
        "slice_closing_radius",
        "elefant_foot_compensation",
        "absolute_correction",
    }
)

_SLA_PROGRESS = re.compile(r"^sla (\d+)% ?(.*)$")


class ResinJobError(ValueError):
    """A resin job that cannot be started (an unknown printer, a format with no writer, a setting that is not offered)."""


def check_overrides(overrides: dict[str, Any]) -> None:
    unknown = sorted(set(overrides) - RESIN_OVERRIDE_KEYS)
    if unknown:
        raise ResinJobError(f"Settings not available for resin printers: {unknown}")


def _process_preset(overrides: dict[str, Any]) -> dict[str, str]:
    process: dict[str, str] = {"type": "process", "from": "user", "name": "resin"}
    for key, value in overrides.items():
        process[key] = "1" if value is True else "0" if value is False else str(value)
    return process


def _material_file_for(
    material_file: Path, resin_name: str, printer_name: str, user_id: str | None, scratch: Path
) -> Path:
    """The resin's file, or for a printer of the user's copied from a catalogue one a copy of it whose rows are also for that printer."""
    catalog = resin_module.catalog
    like_names = catalog.settings_names(printer_name, user_id)
    material = catalog.get_resin(resin_name, user_id)
    if material is None or len(like_names) <= 2:
        return material_file
    path = scratch / "material.json"
    path.write_text(json.dumps(resin_module.rows_for_printer(material, printer_name, like_names)))
    return path


def _support_point_args(scratch: Path, support_points: dict[str, Any] | None, points_output: Path | None) -> list[str]:
    """The slicer's options for hand-placed support points (a file of them to use) and for writing the points it ends up with."""
    args: list[str] = []
    if support_points is not None:
        points_path = scratch / "support_points.json"
        points_path.write_text(json.dumps(support_points))
        args += ["--sla-support-points-input", str(points_path)]
    if points_output is not None:
        args += ["--sla-support-points-output", str(points_output)]
    return args


def _material_fits(resin_name: str, printer_name: str, user_id: str | None, overrides: dict[str, Any]) -> bool:
    """Whether the resin has a row of settings the slicer can use for the printer at the layer height of the job."""
    catalog = resin_module.catalog
    material = catalog.get_resin(resin_name, user_id)
    if material is None:
        return False
    try:
        height = float(overrides.get("layer_height", 0.05))
    except (TypeError, ValueError):
        height = 0.05
    return resin_module.choose_row(material, catalog.settings_names(printer_name, user_id), height) is not None


def run_resin_slice(
    *,
    model_path: Path,
    output_dir: Path,
    printer_name: str,
    resin_name: str | None,
    setting_overrides: dict[str, Any],
    on_progress: ProgressCallback | None = None,
    timeout_s: float | None = None,
    user_id: str | None = None,
    archive_format: str | None = None,
    support_points: dict[str, Any] | None = None,
    points_output: Path | None = None,
) -> SliceResult:
    printer = resin_module.catalog.get_printer(printer_name, user_id)
    preset = resin_module.catalog.printer_preset(printer_name, user_id)
    if printer is None or preset is None:
        raise ResinJobError(f"Unknown resin printer: {printer_name!r}")
    if not printer["supported"]:
        raise ResinJobError(f"{printer_name} reads {printer['format']} files, which the slicer cannot write yet")
    check_overrides(setting_overrides)
    material_file = None
    if resin_name:
        material_file = resin_module.catalog.resin_path(resin_name, user_id)
        if material_file is None:
            raise ResinJobError(f"Unknown resin: {resin_name!r}")

    if archive_format:
        # a different file than the printer's own (a layer preview is written as SL1)
        preset = {**preset, "sla_archive_format": archive_format}

    output_dir.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="headless-orca-resin-"))
    try:
        if (
            resin_name
            and material_file is not None
            and not _material_fits(resin_name, printer_name, user_id, setting_overrides)
        ):
            material_file = None  # no row for this printer: the values typed for it are in the overrides, and the slicer refuses such a material
        if resin_name and material_file is not None:
            material_file = _material_file_for(material_file, resin_name, printer_name, user_id, scratch)
        printer_path = scratch / "printer.json"
        printer_path.write_text(json.dumps(preset))
        process_path = scratch / "process.json"
        process_path.write_text(json.dumps(_process_preset(setting_overrides)))
        cmd = [
            settings.orcaslicer_bin,
            "--slice",
            "0",
            "--datadir",
            str(settings.orcaslicer_datadir),
            "--outputdir",
            str(output_dir),
            "--load-settings",
            f"{printer_path};{process_path}",
        ]
        if material_file is not None:
            cmd += ["--load-filaments", str(material_file)]
        cmd += _support_point_args(scratch, support_points, points_output)
        if model_path.suffix.lower() == ".3mf":
            cmd.append("--allow-newer-file=1")
        cmd.append(str(model_path))
        return _run(cmd, output_dir, on_progress, timeout_s)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _run(
    cmd: list[str], output_dir: Path, on_progress: ProgressCallback | None, timeout_s: float | None
) -> SliceResult:
    """Run the slicer, forwarding its "sla N% text" progress lines as they arrive."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    timed_out = threading.Event()

    def kill() -> None:
        timed_out.set()
        proc.kill()

    timer = threading.Timer(timeout_s, kill) if timeout_s else None
    if timer:
        timer.start()
    stdout, stderr_pipe = proc.stdout, proc.stderr
    if stdout is None or stderr_pipe is None:
        raise RuntimeError("the slicer was started without its output pipes")
    stderr_parts: list[str] = []
    stderr_thread = threading.Thread(target=lambda: stderr_parts.append(stderr_pipe.read()), daemon=True)
    stderr_thread.start()
    stdout_lines: list[str] = []
    try:
        for line in stdout:
            stdout_lines.append(line)
            m = _SLA_PROGRESS.match(line.strip())
            if m and on_progress is not None:
                percent = float(m.group(1))
                on_progress(JobProgress(total_percent=percent, plate_percent=percent, message=m.group(2) or None))
        proc.wait()
    finally:
        if timer:
            timer.cancel()
        stderr_thread.join(timeout=2.0)
    stderr = "".join(stderr_parts)
    return_code = proc.returncode
    if timed_out.is_set():
        return_code = -1
        stderr += "\n[resin_runner] timed out and was killed"
    result_json = _read_result_json(output_dir / "result.json")
    return SliceResult(
        return_code=return_code,
        result_json=result_json,
        stdout="".join(stdout_lines),
        stderr=stderr,
        used_result_json=result_json is not None,
    )


class HollowError(ValueError):
    """A model that cannot be hollowed, with the reason in words the user can act on."""


class HollowResult:
    def __init__(self, volume_before_mm3: float, volume_after_mm3: float, triangles: int):
        self.volume_before_mm3 = volume_before_mm3
        self.volume_after_mm3 = volume_after_mm3
        self.triangles = triangles


# Hollowing needs no particular printer, but the slicer reaches it through the resin path, which wants a resin printer profile.
_HOLLOW_PRINTER = {
    "type": "machine",
    "from": "user",
    "name": "hollowing",
    "printer_technology": "SLA",
    "display_width": "120",
    "display_height": "68",
    "display_pixels_x": "2560",
    "display_pixels_y": "1440",
    "printable_height": "150",
}


def run_hollow(
    *, model_path: Path, output_path: Path, wall_thickness: float, quality: float, timeout_s: float = 600.0
) -> HollowResult:
    """Hollow a model with the slicer: a copy with a cavity in it, written as a binary STL in the place the model is."""
    scratch = Path(tempfile.mkdtemp(prefix="headless-orca-hollow-"))
    try:
        printer = scratch / "printer.json"
        printer.write_text(json.dumps(_HOLLOW_PRINTER))
        process = scratch / "process.json"
        process.write_text(
            json.dumps(
                {
                    "type": "process",
                    "from": "user",
                    "name": "hollowing",
                    "hollowing_min_thickness": f"{wall_thickness:g}",
                    "hollowing_quality": f"{quality:g}",
                }
            )
        )
        cmd = [
            settings.orcaslicer_bin,
            "--slice",
            "0",
            "--datadir",
            str(settings.orcaslicer_datadir),
            "--outputdir",
            str(scratch / "out"),
            "--load-settings",
            f"{printer};{process}",
            "--sla-hollow-output",
            str(output_path),
        ]
        if model_path.suffix.lower() == ".3mf":
            cmd.append("--allow-newer-file=1")
        cmd.append(str(model_path))
        result = _run(cmd, scratch / "out", None, timeout_s)
        info = result.result_json or {}
        if not result.succeeded or not output_path.is_file():
            raise HollowError(
                str(info.get("error_string") or result.stderr.strip() or f"exit code {result.return_code}")
            )
        return HollowResult(
            float(info.get("volume_before_mm3", 0)),
            float(info.get("volume_after_mm3", 0)),
            int(float(info.get("triangle_count", 0))),
        )
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


class SupportPointsError(ValueError):
    """A model the slicer could not place support points on, with the reason in words the user can act on."""


def run_support_points(
    *,
    model_path: Path,
    printer_name: str,
    resin_name: str | None,
    setting_overrides: dict[str, Any],
    user_id: str | None = None,
    support_points: dict[str, Any] | None = None,
    timeout_s: float = 600.0,
) -> dict[str, Any]:
    """The support points the slicer would build supports for (generated, or `support_points` given back), without slicing.

    The points are in the coordinates the model file has: {"objects": [{"points": [{"x", "y", "z", "radius", "type"}]}]}.
    """
    scratch = Path(tempfile.mkdtemp(prefix="headless-orca-points-"))
    try:
        target = scratch / "points.json"
        result = run_resin_slice(
            model_path=model_path,
            output_dir=scratch / "out",
            printer_name=printer_name,
            resin_name=resin_name,
            setting_overrides=setting_overrides,
            timeout_s=timeout_s,
            user_id=user_id,
            support_points=support_points,
            points_output=target,
        )
        if not result.succeeded or not target.is_file():
            info = result.result_json or {}
            raise SupportPointsError(
                str(info.get("error_string") or result.stderr.strip() or f"exit code {result.return_code}")
            )
        return json.loads(target.read_text())
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
