import math
from pathlib import Path

from app import belt_align, cli_runner
from app.cli_runner import SliceResult
from app.routers import jobs as jobs_router
from app.schemas import JobCreateRequest, ProfileDetail

# IdeaFormer IR3 V2's frame: 45 degree tilt about X, gcode_remap rev_x / pos_z / pos_y.
_MACHINE = {
    "belt_printer": "1",
    "belt_slice_rotation": "x",
    "belt_slice_rotation_angle": "45",
    "gcode_remap_x": "rev_x",
    "gcode_remap_y": "pos_z",
    "gcode_remap_z": "pos_y",
    "printable_area": ["0x0", "250x0", "250x2000", "0x2000"],
    "printable_height": "250",
}
_BOUNDS = (250.0, 2000.0, 250.0)
_COS = math.cos(math.radians(45))


def _gcode_at(belt_y: float, height: float = 0.1) -> tuple[float, float]:
    """gcode (gy, gz) of the point at upright Y=belt_y, upright Z=height."""
    gy = height / math.sin(math.radians(45))
    return gy, belt_y + gy * _COS


def _write(path: Path, purge_y: float, material: list[tuple[str, float]]) -> Path:
    lines = ["M83", "G92 E0", ";TYPE:Custom"]
    for gy, gz in [_gcode_at(purge_y - 0.2), _gcode_at(purge_y + 0.2)]:
        lines += [f"G1 X10 Y{gy:.4f} Z{gz:.4f}", f"G1 X240 Y{gy:.4f} Z{gz:.4f} E1.0"]
    for kind, belt_y in material:
        gy, gz = _gcode_at(belt_y, 0.2)
        lines += [f";TYPE:{kind}", f"G1 X100 Y{gy:.4f} Z{gz:.4f}", f"G1 X120 Y{gy:.4f} Z{gz:.4f} E0.5"]
    path.write_text("\n".join(lines))
    return path


def test_back_transform_inverts_the_machine_frame():
    t = belt_align.parse_belt_transform(_MACHINE, _BOUNDS)
    gy, gz = _gcode_at(37.5, 12.0)
    x, y, z = belt_align.back_transform(t, 190.0, gy, gz)
    assert (round(x, 6), round(y, 6), round(z, 6)) == (60.0, 37.5, 12.0)


def test_non_belt_printer_has_no_transform():
    assert belt_align.parse_belt_transform({"belt_printer": "0"}, _BOUNDS) is None
    assert belt_align.parse_belt_transform({**_MACHINE, "belt_slice_rotation": "z"}, _BOUNDS) is None


def test_start_is_the_lowest_printed_material_not_just_the_model(tmp_path):
    t = belt_align.parse_belt_transform(_MACHINE, _BOUNDS)
    gcode = _write(tmp_path / "a.gcode", 20.0, [("Outer wall", 60.0), ("Support", 45.0), ("Brim", 52.0)])
    m = belt_align.measure_start(gcode, t)
    assert round(m.purge_y, 2) == 20.0 and round(m.start_y, 2) == 45.0
    assert round(m.shift_needed, 2) == -25.0  # move the print toward the origin


def test_prime_tower_and_purge_do_not_count_as_the_print(tmp_path):
    t = belt_align.parse_belt_transform(_MACHINE, _BOUNDS)
    gcode = _write(tmp_path / "a.gcode", 20.0, [("Prime tower", 5.0), ("Outer wall", 30.0)])
    assert round(belt_align.measure_start(gcode, t).start_y, 2) == 30.0


def test_a_print_that_overlaps_the_purge_line_is_moved_away(tmp_path):
    t = belt_align.parse_belt_transform(_MACHINE, _BOUNDS)
    gcode = _write(tmp_path / "a.gcode", 20.0, [("Support", 8.0)])
    assert round(belt_align.measure_start(gcode, t).shift_needed, 2) == 12.0


def test_no_purge_or_no_material_gives_none(tmp_path):
    t = belt_align.parse_belt_transform(_MACHINE, _BOUNDS)
    only_material = tmp_path / "b.gcode"
    only_material.write_text(";TYPE:Outer wall\nM83\nG1 X1 Y1 Z1\nG1 X2 Y1 Z1 E1")
    assert belt_align.measure_start(only_material, t) is None


def _request():
    return JobCreateRequest(model_id="m", printer_profile="Belt", process_profile="P", filament_profiles=["F"])


def _patch(monkeypatch, tmp_path, measure):
    detail = ProfileDetail(vendor="V", kind="machine", name="Belt", path="x", data=_MACHINE)
    monkeypatch.setattr(cli_runner, "_resolve_profile_detail", lambda kind, name, user_id=None: detail)
    monkeypatch.setattr(belt_align, "measure_start", lambda gcode, t: measure)
    monkeypatch.setattr(jobs_router, "_job_output_dir", lambda job_id: tmp_path / job_id)
    out = tmp_path / "job"
    out.mkdir()
    (out / "plate_1.gcode").write_text("first")
    calls = []

    def fake_slice(**kw):
        calls.append(kw)
        kw["output_dir"].mkdir(parents=True, exist_ok=True)
        (kw["output_dir"] / "plate_1.gcode").write_text("second")
        return SliceResult(return_code=0, result_json={"return_code": 0}, stdout="", stderr="", used_result_json=True)

    monkeypatch.setattr(cli_runner, "run_slice", fake_slice)
    first = SliceResult(return_code=0, result_json={"return_code": 0}, stdout="", stderr="", used_result_json=True)
    return out, calls, first


def test_a_misaligned_start_is_sliced_again_shifted(tmp_path, monkeypatch):
    out, calls, first = _patch(monkeypatch, tmp_path, belt_align.StartMeasure(purge_y=20.0, start_y=35.0))
    result = jobs_router._align_to_purge_line("job", _request(), None, {"output_dir": out, "model_path": Path("m")}, first)
    assert calls[0]["belt_shift_y"] == -15.0 and calls[0]["on_progress"] is None
    assert (out / "plate_1.gcode").read_text() == "second" and not (out / "realigned").exists()
    assert result is not first


def test_a_start_within_tolerance_is_left_alone(tmp_path, monkeypatch):
    out, calls, first = _patch(monkeypatch, tmp_path, belt_align.StartMeasure(purge_y=20.0, start_y=20.2))
    assert jobs_router._align_to_purge_line("job", _request(), None, {"output_dir": out}, first) is first
    assert calls == [] and (out / "plate_1.gcode").read_text() == "first"


def test_a_failed_second_pass_keeps_the_first_result(tmp_path, monkeypatch):
    out, calls, first = _patch(monkeypatch, tmp_path, belt_align.StartMeasure(purge_y=20.0, start_y=60.0))
    monkeypatch.setattr(
        cli_runner,
        "run_slice",
        lambda **kw: SliceResult(return_code=1, result_json=None, stdout="", stderr="", used_result_json=False),
    )
    assert jobs_router._align_to_purge_line("job", _request(), None, {"output_dir": out}, first) is first
    assert (out / "plate_1.gcode").read_text() == "first"


def test_a_refused_shift_is_backed_off(tmp_path, monkeypatch):
    out, calls, first = _patch(monkeypatch, tmp_path, belt_align.StartMeasure(purge_y=20.0, start_y=86.5))  # wants -66.5
    accepted = SliceResult(return_code=0, result_json={"return_code": 0}, stdout="", stderr="", used_result_json=True)
    refused = SliceResult(return_code=206, result_json=None, stdout="", stderr="", used_result_json=False)
    outcomes = iter([refused, refused, accepted])
    seen = []

    def fake(**kw):
        seen.append(kw["belt_shift_y"])
        res = next(outcomes)
        if res.succeeded:
            kw["output_dir"].mkdir(parents=True, exist_ok=True)
            (kw["output_dir"] / "plate_1.gcode").write_text("backed off")
        return res

    monkeypatch.setattr(cli_runner, "run_slice", fake)
    monkeypatch.setattr(belt_align, "measure_start", lambda gcode, t: belt_align.StartMeasure(20.0, 86.5) if len(seen) == 0 else belt_align.StartMeasure(20.0, 20.3))
    jobs_router._align_to_purge_line("job", _request(), None, {"output_dir": out}, first)
    assert seen == [-66.5, -65.0, -63.5]
    assert (out / "plate_1.gcode").read_text() == "backed off"


def test_a_remaining_error_gets_refined(tmp_path, monkeypatch):
    out, calls, first = _patch(monkeypatch, tmp_path, None)
    readings = iter([belt_align.StartMeasure(20.0, 35.0), belt_align.StartMeasure(20.0, 21.2), belt_align.StartMeasure(20.0, 20.1)])
    monkeypatch.setattr(belt_align, "measure_start", lambda gcode, t: next(readings))
    jobs_router._align_to_purge_line("job", _request(), None, {"output_dir": out}, first)
    # shifts are cumulative from the default placement; the second one is
    # corrected for how far the start actually moved per mm of the first
    assert [round(c["belt_shift_y"], 2) for c in calls] == [-15.0, -16.3]
    assert len(calls) == 2


def test_a_support_that_moves_twice_as_fast_is_learned(tmp_path, monkeypatch):
    # The start moves 2 mm per mm of shift here (the support changes too).
    out, calls, first = _patch(monkeypatch, tmp_path, None)
    seen = []

    def fake(**kw):
        seen.append(kw["belt_shift_y"])
        kw["output_dir"].mkdir(parents=True, exist_ok=True)
        (kw["output_dir"] / "plate_1.gcode").write_text("x")
        return SliceResult(return_code=0, result_json={"return_code": 0}, stdout="", stderr="", used_result_json=True)

    monkeypatch.setattr(cli_runner, "run_slice", fake)
    monkeypatch.setattr(belt_align, "measure_start", lambda gcode, t: belt_align.StartMeasure(20.0, 8.43 + 2.0 * (seen[-1] if seen else 0.0)))
    jobs_router._align_to_purge_line("job", _request(), None, {"output_dir": out}, first)
    assert len(seen) == 2 and abs(seen[-1] - 5.785) < 0.01  # converged in two corrections, not overshooting
