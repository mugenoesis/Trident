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


def run_resin_slice(
    *,
    model_path: Path,
    output_dir: Path,
    printer_name: str,
    resin_name: str | None,
    setting_overrides: dict[str, Any],
    on_progress: ProgressCallback | None = None,
    timeout_s: float | None = None,
) -> SliceResult:
    printer = resin_module.catalog.get_printer(printer_name)
    preset = resin_module.catalog.printer_preset(printer_name)
    if printer is None or preset is None:
        raise ResinJobError(f"Unknown resin printer: {printer_name!r}")
    if not printer["supported"]:
        raise ResinJobError(f"{printer_name} reads {printer['format']} files, which the slicer cannot write yet")
    check_overrides(setting_overrides)
    material_file = None
    if resin_name:
        material_file = resin_module.catalog.resin_path(resin_name)
        if material_file is None:
            raise ResinJobError(f"Unknown resin: {resin_name!r}")

    output_dir.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="headless-orca-resin-"))
    try:
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
