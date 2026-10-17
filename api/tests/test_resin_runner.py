import json
from pathlib import Path

import pytest
from resin_support import FAKE_BIN, build_resin_dir

from app import resin as resin_module
from app import resin_runner
from app.config import settings
from app.resin import ResinCatalog
from app.resin_runner import ResinJobError


@pytest.fixture()
def resin_dir(tmp_path: Path, monkeypatch) -> Path:
    root = build_resin_dir(tmp_path / "resin")
    catalog = ResinCatalog(root)
    catalog.load()
    monkeypatch.setattr(resin_module, "catalog", catalog)
    monkeypatch.setattr(settings, "orcaslicer_bin", str(FAKE_BIN))
    return root


def _slice(tmp_path: Path, **overrides):
    model = tmp_path / "cube.stl"
    model.write_text("fake")
    kwargs = {
        "model_path": model,
        "output_dir": tmp_path / "out",
        "printer_name": "Elegoo Mars 3",
        "resin_name": None,
        "setting_overrides": {},
        "timeout_s": 30,
    }
    kwargs.update(overrides)
    return resin_runner.run_resin_slice(**kwargs)


def _args(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "out" / "args.json").read_text())


def test_a_resin_slice_writes_the_printer_file_and_reports_it(tmp_path, resin_dir):
    events = []
    result = _slice(tmp_path, on_progress=events.append)
    assert result.succeeded
    assert result.result_json["printer_technology"] == "SLA"
    assert float(result.result_json["resin_used_ml"]) == 8.0  # the slicer writes numbers as text
    assert (tmp_path / "out" / "plate_1.ctb").is_file()
    assert [e.total_percent for e in events] == [10.0, 80.0]
    assert events[0].message == "Slicing"


def test_the_printer_preset_and_the_overrides_reach_the_slicer(tmp_path, resin_dir):
    _slice(
        tmp_path,
        setting_overrides={"layer_height": 0.1, "supports_enable": True, "hollowing_enable": False, "exposure_time": 3},
    )
    args = _args(tmp_path)
    assert args["printer"]["display_pixels_x"] == "4098"
    assert args["printer"]["sla_archive_format"] == "CTBENCRYPTED"
    # a process profile in the slicer's own file format: strings, booleans as 1/0
    assert args["process"] == {
        "type": "process",
        "from": "user",
        "name": "resin",
        "layer_height": "0.1",
        "supports_enable": "1",
        "hollowing_enable": "0",
        "exposure_time": "3",
    }
    assert args["material"] is None


def test_a_resin_is_handed_over_as_its_own_file(tmp_path, resin_dir):
    _slice(tmp_path, resin_name="Test resin")
    assert _args(tmp_path)["material"]["name"] == "Test resin"


def test_a_3mf_is_allowed_to_be_newer(tmp_path, resin_dir):
    model = tmp_path / "part.3mf"
    model.write_text("fake")
    _slice(tmp_path, model_path=model)
    assert _args(tmp_path)["allow_newer"] == "1"


def test_a_failed_slice_reports_the_slicers_error(tmp_path, resin_dir):
    result = _slice(tmp_path, setting_overrides={"hollowing_min_thickness": 99})
    assert not result.succeeded
    assert result.result_json["error_string"] == "does not fit"
    assert "does not fit" in result.stderr


def test_nothing_is_started_for_a_printer_resin_or_setting_that_cannot_be_used(tmp_path, resin_dir):
    with pytest.raises(ResinJobError, match="Unknown resin printer"):
        _slice(tmp_path, printer_name="Nope")
    with pytest.raises(ResinJobError, match="cannot write yet"):
        _slice(tmp_path, printer_name="Elegoo Old")
    with pytest.raises(ResinJobError, match="Unknown resin"):
        _slice(tmp_path, resin_name="Nope")
    with pytest.raises(ResinJobError, match="not available"):
        _slice(tmp_path, setting_overrides={"print_host": "http://x"})
    assert not (tmp_path / "out" / "args.json").exists()


def test_the_scratch_files_are_removed(tmp_path, resin_dir):
    import tempfile

    pattern = "headless-orca-resin-*"
    before = set(Path(tempfile.gettempdir()).glob(pattern))
    _slice(tmp_path)
    assert set(Path(tempfile.gettempdir()).glob(pattern)) == before
