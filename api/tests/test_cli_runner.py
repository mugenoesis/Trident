import json
from pathlib import Path

from app import cli_runner
from app import profiles as profiles_module
from app.config import settings

_FAKE_BIN = Path(__file__).parent / "fixtures" / "fake_orca_slicer.py"


def _write_profile(vendor_dir: Path, subdir: str, name: str, kind: str) -> None:
    d = vendor_dir / subdir
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps({"name": name, "type": kind}))


def _seed_catalog(profiles_dir: Path, vendor: str, machine: str, process: str, filament: str) -> None:
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / f"{vendor}.json").write_text(json.dumps({"name": vendor}))
    vendor_dir = profiles_dir / vendor
    _write_profile(vendor_dir, "machine", machine, "machine")
    _write_profile(vendor_dir, "process", process, "process")
    _write_profile(vendor_dir, "filament", filament, "filament")
    profiles_module.catalog.load()


def test_run_slice_happy_path(tmp_path: Path, monkeypatch, data_dirs):
    monkeypatch.setattr(settings, "orcaslicer_bin", str(_FAKE_BIN))
    _seed_catalog(data_dirs["profiles"], "Generic", "Generic Printer", "0.20mm Standard", "Generic PLA")

    model_path = tmp_path / "cube.stl"
    model_path.write_text("fake")
    output_dir = tmp_path / "out"

    progress_events = []
    result = cli_runner.run_slice(
        model_path=model_path,
        output_dir=output_dir,
        printer_profile="Generic Printer",
        process_profile="0.20mm Standard",
        filament_profiles=["Generic PLA"],
        setting_overrides={"layer_height": 0.2},
        on_progress=progress_events.append,
        timeout_s=10,
    )

    assert result.succeeded
    assert result.used_result_json
    assert result.result_json == {"return_code": 0, "error_string": ""}
    assert (output_dir / "out.gcode").exists()
    assert len(progress_events) == 2
    assert progress_events[-1].total_percent == 100.0
    # FIFO is cleaned up after the run.
    assert not (output_dir / "progress.pipe").exists()


def test_run_slice_unknown_profile_raises(tmp_path: Path, data_dirs):
    model_path = tmp_path / "cube.stl"
    model_path.write_text("fake")
    profiles_module.catalog.load()  # empty catalog

    try:
        cli_runner.run_slice(
            model_path=model_path,
            output_dir=tmp_path / "out",
            printer_profile="No Such Printer",
            process_profile="q",
            filament_profiles=[],
            setting_overrides={},
            timeout_s=10,
        )
        raised = False
    except ValueError:
        raised = True
    assert raised
    # Failing before the subprocess is spawned shouldn't leave a FIFO behind.
    assert not (tmp_path / "out" / "progress.pipe").exists()


def test_run_slice_missing_binary_raises(tmp_path: Path, monkeypatch, data_dirs):
    monkeypatch.setattr(settings, "orcaslicer_bin", "/no/such/orca-slicer-binary")
    _seed_catalog(data_dirs["profiles"], "Generic", "p", "q", "r")

    model_path = tmp_path / "cube.stl"
    model_path.write_text("fake")

    try:
        cli_runner.run_slice(
            model_path=model_path,
            output_dir=tmp_path / "out",
            printer_profile="p",
            process_profile="q",
            filament_profiles=[],
            setting_overrides={},
            timeout_s=10,
        )
        raised = False
    except OSError:
        raised = True
    assert raised
