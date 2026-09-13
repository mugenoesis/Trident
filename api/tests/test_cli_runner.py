from pathlib import Path

from app import cli_runner
from app.config import settings

_FAKE_BIN = Path(__file__).parent / "fixtures" / "fake_orca_slicer.py"


def test_run_slice_happy_path(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "orcaslicer_bin", str(_FAKE_BIN))

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


def test_run_slice_missing_binary_raises(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "orcaslicer_bin", "/no/such/orca-slicer-binary")

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
