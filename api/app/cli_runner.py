"""Subprocess orchestration around the patched OrcaSlicer CLI.

Protocol (docs/ARCHITECTURE.md):
- `--outputdir <dir>` gets a `result.json` written on every exit path
  (`record_exit_reson()` in OrcaSlicer.cpp) — this is the authoritative
  result, not the process exit code.
- `--pipe <fifo>` streams newline-delimited JSON progress objects.

Race condition: `cli_callback_mgr_t::start()` opens the FIFO
`O_WRONLY|O_NONBLOCK` in a retry loop and gives up after ~1s if nothing
has opened it for reading yet. So we must: create the FIFO, start a
reader thread blocked on open-for-read, *then* spawn the subprocess.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import profiles as profiles_module
from .config import settings
from .schemas import JobProgress, ProfileDetail

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[JobProgress], None]


def _resolve_profile_detail(kind: str, name: str) -> ProfileDetail:
    detail = profiles_module.catalog.get_by_name(kind, name)
    if detail is None:
        raise ValueError(f"Unknown {kind} profile: {name!r}")
    return detail


def _write_resolved_profile(detail: ProfileDetail, tmp_dir: Path, stem: str) -> str:
    """--load-settings/--load-filaments take literal file paths, not the bare
    catalog names GET /profiles and JobCreateRequest use (confirmed against a
    real build: OrcaSlicer.cpp's load_config_file() does a plain
    boost::filesystem::exists() on the string it's given, no name lookup).

    Writing out `detail.data` (ProfileCatalog's fully `inherits`-resolved
    effective config, see profiles.py) rather than pointing at the profile's
    own file on disk matters: OrcaSlicer.cpp's `--load-settings` handler reads
    only the literal keys present in the given file and does NOT itself walk
    `inherits` (that only happens in the GUI/PresetBundle preset-selection
    flow) -- confirmed against a real build, a belt machine's leaf JSON alone
    slices with `belt_printer = 0` and identity `gcode_remap_*` in the
    resulting gcode's config dump, silently dropping every belt-mode setting
    that's only declared on its "fdm_belt_common" parent. Feeding the
    already-merged dict here sidesteps that gap without needing an
    OrcaSlicer.cpp change.
    """
    path = tmp_dir / f"{stem}.json"
    path.write_text(json.dumps(detail.data))
    return str(path)


class SliceResult:
    def __init__(
        self,
        *,
        return_code: int,
        result_json: dict[str, Any] | None,
        stdout: str,
        stderr: str,
        used_result_json: bool,
    ):
        self.return_code = return_code
        self.result_json = result_json
        self.stdout = stdout
        self.stderr = stderr
        self.used_result_json = used_result_json

    @property
    def succeeded(self) -> bool:
        if self.result_json is not None:
            return self.result_json.get("return_code") == 0
        return self.return_code == 0


def _pipe_reader(fifo_path: Path, on_progress: ProgressCallback | None) -> None:
    """Block opening the FIFO for reading, then forward parsed JSON lines."""
    try:
        with open(fifo_path, "r") as fifo:
            for line in fifo:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Non-JSON line on --pipe: %r", line)
                    continue
                if on_progress is not None:
                    on_progress(
                        JobProgress(
                            plate_index=data.get("plate_index"),
                            plate_count=data.get("plate_count"),
                            plate_percent=data.get("plate_percent"),
                            total_percent=data.get("total_percent"),
                            message=data.get("message"),
                            warning=data.get("warning"),
                        )
                    )
    except OSError as exc:
        logger.warning("--pipe reader for %s exited: %s", fifo_path, exc)


def run_slice(
    *,
    model_path: Path,
    output_dir: Path,
    printer_profile: str,
    process_profile: str,
    filament_profiles: list[str],
    setting_overrides: dict[str, Any],
    plate_index: int | None = None,
    on_progress: ProgressCallback | None = None,
    timeout_s: float | None = None,
) -> SliceResult:
    # Resolved before the FIFO/reader thread exist so an unknown profile name
    # fails fast without leaking a thread blocked forever on open()-for-read.
    printer_detail = _resolve_profile_detail("machine", printer_profile)
    process_detail = _resolve_profile_detail("process", process_profile)
    filament_details = [_resolve_profile_detail("filament", f) for f in filament_profiles]

    output_dir.mkdir(parents=True, exist_ok=True)
    fifo_path = output_dir / "progress.pipe"
    if fifo_path.exists():
        fifo_path.unlink()
    os.mkfifo(fifo_path)

    reader_thread = threading.Thread(
        target=_pipe_reader, args=(fifo_path, on_progress), daemon=True
    )
    reader_thread.start()

    # Written fresh per slice (not cached alongside the catalog) since
    # setting_overrides below apply as separate CLI flags on top, not into
    # these files -- these just need to carry each profile's own resolved
    # `inherits` chain, see _write_resolved_profile.
    resolved_profiles_dir = tempfile.mkdtemp(prefix="headless-orca-resolved-")
    printer_path = _write_resolved_profile(printer_detail, Path(resolved_profiles_dir), "printer")
    process_path = _write_resolved_profile(process_detail, Path(resolved_profiles_dir), "process")
    filament_paths = [
        _write_resolved_profile(detail, Path(resolved_profiles_dir), f"filament_{i}")
        for i, detail in enumerate(filament_details)
    ]

    cmd = [
        settings.orcaslicer_bin,
        "--slice",
        # 0 = slice all plates; N = slice only plate N (--help-fff). Driven
        # by the pre-slice plate picker for multi-plate .3mf uploads -- None
        # means "not applicable", same as today's always-slice-everything.
        str(plate_index) if plate_index is not None else "0",
        "--datadir",
        str(settings.orcaslicer_datadir),
        "--outputdir",
        str(output_dir),
        "--pipe",
        str(fifo_path),
        "--load-settings",
        f"{printer_path};{process_path}",
    ]
    if filament_paths:
        cmd += ["--load-filaments", ";".join(filament_paths)]
    for key, value in setting_overrides.items():
        # ConfigOptionDef::cli_args() (libslic3r/Config.cpp) derives the CLI flag
        # from the config key by replacing underscores with dashes, unless the
        # option defines a custom `cli` alias -- that's a rarer case this doesn't
        # handle, but covers the vast majority of settings (confirmed against a
        # real build: --layer_height is rejected as "Invalid option", --layer-height
        # works).
        #
        # Single `--key=value` token, not `["--key", "value"]`: ConfigBase::
        # read_cli_args() only auto-consumes the *next* argv token as a value
        # for non-bool options (coBool/coBools are allowed an empty value,
        # meaning "true", so it never looks ahead for them). A separate
        # "--enable-support" "1" pair left "1" unconsumed, which then got
        # parsed as a positional arg -- i.e. an extra (nonexistent) input
        # model file, surfacing as a confusing "input files not found" error.
        # The `--key=value` form is parsed generically up front regardless of
        # type, so it's correct (and safe with spaces, e.g. enum values like
        # "Textured PEI Plate") for every option, not just bools.
        cmd.append(f"--{key.replace('_', '-')}={value}")
    cmd.append(str(model_path))

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        return_code = proc.returncode
        stdout, stderr = proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        return_code = -1
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + "\n[cli_runner] timed out and was killed"
    finally:
        reader_thread.join(timeout=2.0)
        fifo_path.unlink(missing_ok=True)
        shutil.rmtree(resolved_profiles_dir, ignore_errors=True)

    result_json_path = output_dir / "result.json"
    result_json: dict[str, Any] | None = None
    if result_json_path.exists():
        try:
            result_json = json.loads(result_json_path.read_text())
        except json.JSONDecodeError:
            logger.error("result.json at %s is not valid JSON", result_json_path)

    return SliceResult(
        return_code=return_code,
        result_json=result_json,
        stdout=stdout,
        stderr=stderr,
        used_result_json=result_json is not None,
    )


def fetch_help_json() -> list[dict[str, Any]] | None:
    """Shell out to `--help-json` (docs/ARCHITECTURE.md patch #5).

    Returns None if the binary doesn't support --help-json yet (patch not
    landed, or a vanilla/unpatched build during M1) so callers can fall
    back to parsing --help-fff/--help-sla text.
    """
    try:
        proc = subprocess.run(
            [settings.orcaslicer_bin, "--help-json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.info("--help-json unavailable: %s", exc)
        return None
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        logger.warning("--help-json produced non-JSON output")
        return None
