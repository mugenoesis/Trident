import json
import zipfile
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


def test_run_slice_plate_index_maps_to_slice_flag(tmp_path: Path, monkeypatch, data_dirs):
    monkeypatch.setattr(settings, "orcaslicer_bin", str(_FAKE_BIN))
    _seed_catalog(data_dirs["profiles"], "Generic", "Generic Printer", "0.20mm Standard", "Generic PLA")

    model_path = tmp_path / "cube.stl"
    model_path.write_text("fake")
    output_dir = tmp_path / "out"

    result = cli_runner.run_slice(
        model_path=model_path,
        output_dir=output_dir,
        printer_profile="Generic Printer",
        process_profile="0.20mm Standard",
        filament_profiles=["Generic PLA"],
        setting_overrides={},
        plate_index=5,
        timeout_s=10,
    )
    assert result.succeeded
    assert (output_dir / "slice_arg.txt").read_text() == "5"


def test_run_slice_no_plate_index_slices_all_plates(tmp_path: Path, monkeypatch, data_dirs):
    monkeypatch.setattr(settings, "orcaslicer_bin", str(_FAKE_BIN))
    _seed_catalog(data_dirs["profiles"], "Generic", "Generic Printer", "0.20mm Standard", "Generic PLA")

    model_path = tmp_path / "cube.stl"
    model_path.write_text("fake")
    output_dir = tmp_path / "out"

    result = cli_runner.run_slice(
        model_path=model_path,
        output_dir=output_dir,
        printer_profile="Generic Printer",
        process_profile="0.20mm Standard",
        filament_profiles=["Generic PLA"],
        setting_overrides={},
        timeout_s=10,
    )
    assert result.succeeded
    assert (output_dir / "slice_arg.txt").read_text() == "0"


def test_run_slice_3mf_forces_arrange(tmp_path: Path, monkeypatch, data_dirs):
    # A .3mf project bakes in the bed position(s) it was arranged at on
    # whatever printer authored it. Re-slicing on a different printer
    # profile (routine here, since one project can target many machines)
    # gives no guarantee that position is valid for the new printer's bed --
    # confirmed against a real project authored for a "Bambu Lab A1 mini"
    # whose embedded object position sat outside an IdeaFormer IR3 V2's much
    # smaller belt-shaped usable area, failing with "One of the plate is
    # empty or has no object fully inside it" even though the object itself
    # was perfectly printable once actually positioned within bounds.
    monkeypatch.setattr(settings, "orcaslicer_bin", str(_FAKE_BIN))
    _seed_catalog(data_dirs["profiles"], "Generic", "Generic Printer", "0.20mm Standard", "Generic PLA")

    model_path = tmp_path / "project.3mf"
    model_path.write_text("fake")
    output_dir = tmp_path / "out"

    result = cli_runner.run_slice(
        model_path=model_path,
        output_dir=output_dir,
        printer_profile="Generic Printer",
        process_profile="0.20mm Standard",
        filament_profiles=["Generic PLA"],
        setting_overrides={},
        timeout_s=10,
    )
    assert result.succeeded
    assert (output_dir / "arrange_arg.txt").read_text() == "1"


def _write_project_3mf(path: Path, project_settings: dict) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("3D/3dmodel.model", "<model/>")
        zf.writestr("Metadata/project_settings.config", json.dumps(project_settings))


def test_run_slice_3mf_corrects_out_of_range_embedded_setting(tmp_path: Path, monkeypatch, data_dirs):
    # Real-world shape (a downloaded "bee+multicolor.3mf"): the file's own
    # baked-in raft_first_layer_expansion was "-1", outside the engine's
    # declared [0, inf) range for that key, even though raft_layers was "0"
    # (raft off, so the value could never have actually mattered) --
    # confirmed against a real build: m_print_config.validate(true)
    # (OrcaSlicer.cpp) still hard-fails the whole job on it regardless,
    # with "Invalid parameter value(s) included in the 3mf file". See
    # cli_runner._out_of_range_overrides.
    monkeypatch.setattr(settings, "orcaslicer_bin", str(_FAKE_BIN))
    monkeypatch.setattr(cli_runner, "_option_bounds_cache", None)
    _seed_catalog(data_dirs["profiles"], "Generic", "Generic Printer", "0.20mm Standard", "Generic PLA")

    model_path = tmp_path / "bee_multicolor.3mf"
    _write_project_3mf(model_path, {"raft_first_layer_expansion": "-1", "raft_layers": "0"})
    output_dir = tmp_path / "out"

    result = cli_runner.run_slice(
        model_path=model_path,
        output_dir=output_dir,
        printer_profile="Generic Printer",
        process_profile="0.20mm Standard",
        filament_profiles=["Generic PLA"],
        setting_overrides={},
        timeout_s=10,
    )
    assert result.succeeded
    assert (output_dir / "raft_first_layer_expansion_arg.txt").read_text() == "2"


def test_run_slice_3mf_leaves_in_range_embedded_setting_alone(tmp_path: Path, monkeypatch, data_dirs):
    monkeypatch.setattr(settings, "orcaslicer_bin", str(_FAKE_BIN))
    monkeypatch.setattr(cli_runner, "_option_bounds_cache", None)
    _seed_catalog(data_dirs["profiles"], "Generic", "Generic Printer", "0.20mm Standard", "Generic PLA")

    model_path = tmp_path / "fine.3mf"
    _write_project_3mf(model_path, {"raft_first_layer_expansion": "3", "raft_layers": "0"})
    output_dir = tmp_path / "out"

    result = cli_runner.run_slice(
        model_path=model_path,
        output_dir=output_dir,
        printer_profile="Generic Printer",
        process_profile="0.20mm Standard",
        filament_profiles=["Generic PLA"],
        setting_overrides={},
        timeout_s=10,
    )
    assert result.succeeded
    assert (output_dir / "raft_first_layer_expansion_arg.txt").read_text() == ""


def test_run_slice_3mf_does_not_override_callers_own_setting(tmp_path: Path, monkeypatch, data_dirs):
    # A caller-supplied setting_overrides entry is a deliberate choice --
    # even if the 3mf's own baked value for that same key is out of range,
    # don't second-guess what the caller explicitly asked for.
    monkeypatch.setattr(settings, "orcaslicer_bin", str(_FAKE_BIN))
    monkeypatch.setattr(cli_runner, "_option_bounds_cache", None)
    _seed_catalog(data_dirs["profiles"], "Generic", "Generic Printer", "0.20mm Standard", "Generic PLA")

    model_path = tmp_path / "explicit.3mf"
    _write_project_3mf(model_path, {"raft_first_layer_expansion": "-1", "raft_layers": "0"})
    output_dir = tmp_path / "out"

    result = cli_runner.run_slice(
        model_path=model_path,
        output_dir=output_dir,
        printer_profile="Generic Printer",
        process_profile="0.20mm Standard",
        filament_profiles=["Generic PLA"],
        setting_overrides={"raft_first_layer_expansion": 5},
        timeout_s=10,
    )
    assert result.succeeded
    assert (output_dir / "raft_first_layer_expansion_arg.txt").read_text() == "5"


def test_run_slice_stl_does_not_force_arrange(tmp_path: Path, monkeypatch, data_dirs):
    # A bare .stl/.obj carries no baked-in bed position to distrust, so
    # there's nothing here for --arrange to correct -- leave the slicer's
    # own default placement behavior alone.
    monkeypatch.setattr(settings, "orcaslicer_bin", str(_FAKE_BIN))
    _seed_catalog(data_dirs["profiles"], "Generic", "Generic Printer", "0.20mm Standard", "Generic PLA")

    model_path = tmp_path / "cube.stl"
    model_path.write_text("fake")
    output_dir = tmp_path / "out"

    result = cli_runner.run_slice(
        model_path=model_path,
        output_dir=output_dir,
        printer_profile="Generic Printer",
        process_profile="0.20mm Standard",
        filament_profiles=["Generic PLA"],
        setting_overrides={},
        timeout_s=10,
    )
    assert result.succeeded
    assert (output_dir / "arrange_arg.txt").read_text() == ""


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


def test_run_slice_keep_positions_does_not_disturb_the_3mf_corrections(tmp_path: Path, monkeypatch, data_dirs):
    # keep_positions adds its own flag; it must neither be required for, nor
    # get in the way of, the out-of-range embedded-setting correction.
    monkeypatch.setattr(settings, "orcaslicer_bin", str(_FAKE_BIN))
    monkeypatch.setattr(cli_runner, "_option_bounds_cache", None)
    _seed_catalog(data_dirs["profiles"], "Generic", "Generic Printer", "0.20mm Standard", "Generic PLA")
    for keep in (False, True):
        model_path = tmp_path / f"m{keep}.3mf"
        _write_project_3mf(model_path, {"raft_first_layer_expansion": "-1", "raft_layers": "0"})
        output_dir = tmp_path / f"out{keep}"
        result = cli_runner.run_slice(
            model_path=model_path,
            output_dir=output_dir,
            printer_profile="Generic Printer",
            process_profile="0.20mm Standard",
            filament_profiles=["Generic PLA"],
            setting_overrides={},
            keep_positions=keep,
            arrange=not keep,
            timeout_s=10,
        )
        assert result.succeeded
        assert (output_dir / "raft_first_layer_expansion_arg.txt").read_text() == "2"
        assert (output_dir / "keep_positions_arg.txt").read_text() == ("1" if keep else "")
        assert (output_dir / "arrange_arg.txt").read_text() == ("" if keep else "1")


def test_run_slice_lets_a_3mf_from_a_newer_bambu_studio_through(tmp_path: Path, monkeypatch, data_dirs):
    # A real project from Bambu Studio 02.08 failed with "Unsupported 3MF
    # version" because the slicer build is older; --allow-newer-file clears it.
    monkeypatch.setattr(settings, "orcaslicer_bin", str(_FAKE_BIN))
    monkeypatch.setattr(cli_runner, "_option_bounds_cache", None)
    _seed_catalog(data_dirs["profiles"], "Generic", "Generic Printer", "0.20mm Standard", "Generic PLA")
    for name, expected in (("p.3mf", "1"), ("p.stl", "")):
        model = tmp_path / name
        if name.endswith(".3mf"):
            _write_project_3mf(model, {})
        else:
            model.write_bytes(b"solid x\nendsolid x\n")
        out = tmp_path / ("out_" + name)
        result = cli_runner.run_slice(
            model_path=model,
            output_dir=out,
            printer_profile="Generic Printer",
            process_profile="0.20mm Standard",
            filament_profiles=["Generic PLA"],
            setting_overrides={},
            timeout_s=10,
        )
        assert result.succeeded
        assert (out / "allow_newer_arg.txt").read_text() == expected


def test_filament_map_is_set_for_three_or_more_filaments():
    four_heads = {"nozzle_diameter": ["0.4"] * 4}
    assert cli_runner._filament_map_overrides(four_heads, 4, {}) == {"filament_map": "1,2,3,4", "filament_map_mode": "Manual"}
    assert cli_runner._filament_map_overrides(four_heads, 3, {})["filament_map"] == "1,2,3"
    # more filaments than extruders: the extras share the last one
    assert cli_runner._filament_map_overrides({"nozzle_diameter": ["0.4", "0.4"]}, 4, {})["filament_map"] == "1,2,2,2"
    assert cli_runner._filament_map_overrides({"nozzle_diameter": ["0.4"]}, 3, {})["filament_map"] == "1,1,1"
    # the job's own nozzle list counts, and so does a caller-supplied map
    assert cli_runner._filament_map_overrides({}, 3, {"nozzle_diameter": "0.4,0.4,0.4"})["filament_map"] == "1,2,3"
    assert cli_runner._filament_map_overrides(four_heads, 4, {"filament_map": "1,1,2,2"}) == {}
    # one or two filaments are left to the slicer
    assert cli_runner._filament_map_overrides(four_heads, 2, {}) == {}
    assert cli_runner._filament_map_overrides(four_heads, 1, {}) == {}
