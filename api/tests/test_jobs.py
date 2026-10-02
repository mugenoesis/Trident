import io

from app import cli_runner
from app.cli_runner import SliceResult
from app.config import settings


def _upload_model(client) -> str:
    resp = client.post(
        "/models", files={"file": ("cube.stl", io.BytesIO(b"fake stl bytes"), "model/stl")}
    )
    assert resp.status_code == 200
    return resp.json()["model_id"]


def test_create_job_rejects_blocked_override(client):
    model_id = _upload_model(client)
    resp = client.post(
        "/jobs",
        json={
            "model_id": model_id,
            "printer_profile": "Generic Printer",
            "process_profile": "0.20mm Standard",
            "setting_overrides": {"print_host": "http://example"},
        },
    )
    assert resp.status_code == 400


def test_create_job_unknown_model_404s(client):
    resp = client.post(
        "/jobs",
        json={
            "model_id": "does-not-exist",
            "printer_profile": "Generic Printer",
            "process_profile": "0.20mm Standard",
        },
    )
    assert resp.status_code == 404


def test_create_job_success_path(client, monkeypatch):
    model_id = _upload_model(client)

    def fake_run_slice(**kwargs):
        on_progress = kwargs.get("on_progress")
        if on_progress:
            from app.schemas import JobProgress

            on_progress(JobProgress(total_percent=100.0, message="done"))
        return SliceResult(
            return_code=0,
            result_json={"return_code": 0, "error_string": ""},
            stdout="",
            stderr="",
            used_result_json=True,
        )

    monkeypatch.setattr(cli_runner, "run_slice", fake_run_slice)

    resp = client.post(
        "/jobs",
        json={
            "model_id": model_id,
            "printer_profile": "Generic Printer",
            "process_profile": "0.20mm Standard",
            "setting_overrides": {"layer_height": 0.2},
        },
    )
    assert resp.status_code == 200
    job_id = resp.json()["id"]

    got = client.get(f"/jobs/{job_id}")
    assert got.status_code == 200
    body = got.json()
    assert body["status"] == "succeeded"
    assert body["result"] == {"return_code": 0, "error_string": ""}


def test_gcode_download_named_after_upload(client, monkeypatch):
    model_id = _upload_model(client)  # uploaded as "cube.stl"

    def fake_run_slice(**kwargs):
        output_dir = kwargs["output_dir"]
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "plate_1.gcode").write_text("; fake gcode\n")
        return SliceResult(
            return_code=0,
            result_json={"return_code": 0, "error_string": ""},
            stdout="",
            stderr="",
            used_result_json=True,
        )

    monkeypatch.setattr(cli_runner, "run_slice", fake_run_slice)

    resp = client.post(
        "/jobs",
        json={
            "model_id": model_id,
            "printer_profile": "Generic Printer",
            "process_profile": "0.20mm Standard",
        },
    )
    job_id = resp.json()["id"]
    assert client.get(f"/jobs/{job_id}").json()["status"] == "succeeded"

    got = client.get(f"/jobs/{job_id}/gcode")
    assert got.status_code == 200
    assert got.headers["content-type"] == "application/octet-stream"
    # "cube.stl" -> "cube.gcode", not OrcaSlicer's on-disk "plate_1.gcode".
    assert 'filename="cube.gcode"' in got.headers["content-disposition"]


def test_gcode_download_falls_back_without_upload_metadata(client, monkeypatch):
    model_id = _upload_model(client)
    # Simulate a model uploaded before the sidecar metadata existed.
    (settings.models_dir / ".meta" / f"{model_id}.json").unlink()

    def fake_run_slice(**kwargs):
        output_dir = kwargs["output_dir"]
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "plate_1.gcode").write_text("; fake gcode\n")
        return SliceResult(
            return_code=0,
            result_json={"return_code": 0, "error_string": ""},
            stdout="",
            stderr="",
            used_result_json=True,
        )

    monkeypatch.setattr(cli_runner, "run_slice", fake_run_slice)

    resp = client.post(
        "/jobs",
        json={
            "model_id": model_id,
            "printer_profile": "Generic Printer",
            "process_profile": "0.20mm Standard",
        },
    )
    job_id = resp.json()["id"]
    assert client.get(f"/jobs/{job_id}").json()["status"] == "succeeded"

    got = client.get(f"/jobs/{job_id}/gcode")
    assert got.status_code == 200
    assert 'filename="plate_1.gcode"' in got.headers["content-disposition"]


def test_gcode_download_targets_specific_plate(client, monkeypatch):
    model_id = _upload_model(client)

    def fake_run_slice(**kwargs):
        output_dir = kwargs["output_dir"]
        output_dir.mkdir(parents=True, exist_ok=True)
        # Simulate a multi-plate output dir: an unrelated plate_1.gcode
        # plus the plate that was actually requested. Without the
        # plate-specific lookup, a blind glob could return either one.
        (output_dir / "plate_1.gcode").write_text("; plate 1 (not requested)\n")
        (output_dir / "plate_2.gcode").write_text("; plate 2 (requested)\n")
        return SliceResult(
            return_code=0,
            result_json={"return_code": 0, "error_string": ""},
            stdout="",
            stderr="",
            used_result_json=True,
        )

    monkeypatch.setattr(cli_runner, "run_slice", fake_run_slice)

    resp = client.post(
        "/jobs",
        json={
            "model_id": model_id,
            "printer_profile": "Generic Printer",
            "process_profile": "0.20mm Standard",
            "plate_index": 2,
        },
    )
    job_id = resp.json()["id"]
    assert client.get(f"/jobs/{job_id}").json()["status"] == "succeeded"

    got = client.get(f"/jobs/{job_id}/gcode")
    assert got.status_code == 200
    assert got.content == b"; plate 2 (requested)\n"


def test_create_job_failure_path(client, monkeypatch):
    model_id = _upload_model(client)

    def fake_run_slice(**kwargs):
        return SliceResult(
            return_code=1,
            result_json={"return_code": 1, "error_string": "bad printer profile"},
            stdout="",
            stderr="",
            used_result_json=True,
        )

    monkeypatch.setattr(cli_runner, "run_slice", fake_run_slice)

    resp = client.post(
        "/jobs",
        json={
            "model_id": model_id,
            "printer_profile": "Generic Printer",
            "process_profile": "0.20mm Standard",
        },
    )
    job_id = resp.json()["id"]

    got = client.get(f"/jobs/{job_id}")
    body = got.json()
    assert body["status"] == "failed"
    assert body["error"] == "bad printer profile"


def test_get_missing_job_404s(client):
    resp = client.get("/jobs/does-not-exist")
    assert resp.status_code == 404


# --- object selection / belt layout (.3mf) ---------------------------------


def _upload_project(client, tmp_path) -> str:
    from test_threemf_objects import _write_project

    project = _write_project(tmp_path)
    resp = client.post("/models", files={"file": ("p.3mf", project.read_bytes(), "model/3mf")})
    assert resp.status_code == 200
    return resp.json()["model_id"]


def _capture_slice(monkeypatch) -> dict:
    captured: dict = {}

    def fake_run_slice(**kwargs):
        captured.update(kwargs)
        return SliceResult(
            return_code=0,
            result_json={"return_code": 0, "error_string": ""},
            stdout="",
            stderr="",
            used_result_json=True,
        )

    monkeypatch.setattr(cli_runner, "run_slice", fake_run_slice)
    return captured


def _job(model_id: str, **extra) -> dict:
    return {
        "model_id": model_id,
        "printer_profile": "Generic Printer",
        "process_profile": "0.20mm Standard",
        **extra,
    }


def test_upload_lists_objects_in_inspection(client, tmp_path):
    model_id = _upload_project(client, tmp_path)
    body = client.get(f"/models/{model_id}/plates").json()
    assert [o["name"] for o in body["objects"]] == ["Block A", "Tall B", "Wide C", "Cube D"]


def test_exclusion_rejected_for_non_3mf(client):
    model_id = _upload_model(client)
    resp = client.post("/jobs", json=_job(model_id, excluded_objects=[0]))
    assert resp.status_code == 400


def test_belt_layout_and_copies_are_accepted_for_non_3mf(client, monkeypatch, tmp_path):
    from app.routers import jobs as jobs_router
    from test_threemf_objects import _write_project

    model_id = _upload_model(client)
    captured = _capture_slice(monkeypatch)
    project = _write_project(tmp_path)

    def fake_convert(src, dest, **kw):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(project.read_bytes())
        return dest

    monkeypatch.setattr(cli_runner, "convert_model", fake_convert)
    monkeypatch.setattr(jobs_router, "_machine_bed", lambda name, user_id=None: (True, 125.0))
    monkeypatch.setattr(jobs_router, "_machine_bed_area", lambda name, user_id=None: (["0x0", "250x0", "250x2000", "0x2000"], 250.0))
    resp = client.post("/jobs", json=_job(model_id, belt_layout={"order": [], "gap_mm": 10}, copies=2))
    assert resp.status_code == 200 and captured["plate_index"] == 1


def test_all_objects_excluded_rejected(client, tmp_path):
    model_id = _upload_project(client, tmp_path)
    resp = client.post("/jobs", json=_job(model_id, excluded_objects=[0, 1, 2, 3]))
    assert resp.status_code == 400


def test_unknown_excluded_index_rejected(client, tmp_path):
    model_id = _upload_project(client, tmp_path)
    resp = client.post("/jobs", json=_job(model_id, excluded_objects=[17]))
    assert resp.status_code == 400


def test_chosen_plate_with_everything_excluded_rejected(client, tmp_path):
    model_id = _upload_project(client, tmp_path)
    # object 2 ("Wide C") is the only one on plate 2
    resp = client.post("/jobs", json=_job(model_id, excluded_objects=[2], plate_index=2))
    assert resp.status_code == 400


def test_exclusion_slices_a_derived_copy_and_keeps_arranging(client, tmp_path, monkeypatch):
    from app.threemf_objects import list_objects

    model_id = _upload_project(client, tmp_path)
    captured = _capture_slice(monkeypatch)
    from app.routers import jobs as jobs_router

    monkeypatch.setattr(jobs_router, "_machine_bed_area", lambda name, user_id=None: (["0x0", "250x0", "250x2000", "0x2000"], 250.0))
    monkeypatch.setattr(jobs_router, "_machine_bed", lambda name, user_id=None: (False, 125.0))
    resp = client.post("/jobs", json=_job(model_id, excluded_objects=[1], plate_index=1))
    assert resp.status_code == 200
    assert captured["model_path"].name == "input.3mf"
    assert captured["plate_index"] == 1
    assert captured["arrange"] is True
    assert [o.name for o in list_objects(captured["model_path"])] == ["Block A", "Wide C", "Cube D"]


def test_belt_layout_slices_one_plate_without_rearranging(client, tmp_path, monkeypatch):
    from app.threemf_objects import list_objects

    model_id = _upload_project(client, tmp_path)
    captured = _capture_slice(monkeypatch)
    from app.routers import jobs as jobs_router

    monkeypatch.setattr(jobs_router, "_machine_bed_area", lambda name, user_id=None: (["0x0", "250x0", "250x2000", "0x2000"], 250.0))
    monkeypatch.setattr(jobs_router, "_machine_bed", lambda name, user_id=None: (True, 125.0))
    resp = client.post(
        "/jobs",
        json=_job(model_id, excluded_objects=[1], belt_layout={"order": [3, 0, 2], "gap_mm": 12}),
    )
    assert resp.status_code == 200
    assert captured["plate_index"] == 1
    assert captured["arrange"] is False
    objs = list_objects(captured["model_path"])
    # the build follows the layout order (order [3, 0, 2], with Tall B excluded)
    assert [o.name for o in objs] == ["Cube D", "Block A", "Wide C"]
    assert {o.plate for o in objs} == {1}


def test_belt_layout_ignored_on_non_belt_printer(client, tmp_path, monkeypatch):
    model_id = _upload_project(client, tmp_path)
    captured = _capture_slice(monkeypatch)
    from app.routers import jobs as jobs_router

    monkeypatch.setattr(jobs_router, "_machine_bed_area", lambda name, user_id=None: (["0x0", "250x0", "250x2000", "0x2000"], 250.0))
    monkeypatch.setattr(jobs_router, "_machine_bed", lambda name, user_id=None: (False, 125.0))
    resp = client.post("/jobs", json=_job(model_id, belt_layout={"order": [0, 1, 2, 3]}, plate_index=2))
    assert resp.status_code == 200
    assert captured["plate_index"] == 2
    assert captured["arrange"] is True


def test_placement_converts_an_stl_and_keeps_positions(client, tmp_path, monkeypatch):
    from app.routers import jobs as jobs_router
    from app.threemf_objects import list_objects
    from test_threemf_objects import _write_project

    model_id = _upload_model(client)  # a plain "stl"
    captured = _capture_slice(monkeypatch)
    project = _write_project(tmp_path)

    def fake_convert(src, dest, **kw):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(project.read_bytes())
        return dest

    monkeypatch.setattr(cli_runner, "convert_model", fake_convert)
    monkeypatch.setattr(jobs_router, "_machine_bed", lambda name, user_id=None: (False, 125.0))
    monkeypatch.setattr(jobs_router, "_machine_bed_area", lambda name, user_id=None: (["0x0", "250x0", "250x250", "0x250"], 250.0))
    resp = client.post("/jobs", json=_job(model_id, placement={"x": 60, "y": 70}))
    assert resp.status_code == 200
    assert captured["arrange"] is False and captured["keep_positions"] is True and captured["plate_index"] == 1
    objs = list_objects(captured["model_path"])
    assert len(objs) == 4  # every object of the converted file is kept, moved as a group


def test_placement_and_belt_layout_cannot_be_combined(client, tmp_path):
    model_id = _upload_project(client, tmp_path)
    resp = client.post("/jobs", json=_job(model_id, placement={"x": 1, "y": 2}, belt_layout={"order": [0]}))
    assert resp.status_code == 400


def test_orient_and_arrange_store_a_new_3mf_model(client, tmp_path, monkeypatch):
    model_id = _upload_model(client)
    project = None
    from test_threemf_objects import _write_project

    project = _write_project(tmp_path)
    calls = []

    def fake_convert(src, dest, **kw):
        calls.append(kw)
        dest.write_bytes(project.read_bytes())
        return dest

    monkeypatch.setattr(cli_runner, "convert_model", fake_convert)
    oriented = client.post(f"/models/{model_id}/orient", json={})
    assert oriented.status_code == 200 and oriented.json()["filename"].endswith(".3mf")
    assert oriented.json()["model_id"] != model_id
    assert calls[-1]["orient"] is True and calls[-1]["arrange"] is False
    assert client.post(f"/models/{model_id}/arrange", json={}).status_code == 400  # needs the printer
    arranged = client.post(f"/models/{model_id}/arrange", json={"printer_profile": "P", "process_profile": "Q"})
    assert arranged.status_code == 200 and calls[-1]["arrange"] is True and calls[-1]["printer_profile"] == "P"


def test_copies_on_a_belt_printer_become_a_row(client, tmp_path, monkeypatch):
    from app.routers import jobs as jobs_router
    from app.threemf_objects import list_objects

    model_id = _upload_project(client, tmp_path)
    captured = _capture_slice(monkeypatch)
    monkeypatch.setattr(jobs_router, "_machine_bed", lambda name, user_id=None: (True, 125.0))
    monkeypatch.setattr(jobs_router, "_machine_bed_area", lambda name, user_id=None: (["0x0", "250x0", "250x2000", "0x2000"], 250.0))
    resp = client.post("/jobs", json=_job(model_id, excluded_objects=[1, 2, 3], copies=4))
    assert resp.status_code == 200
    assert captured["plate_index"] == 1 and captured["arrange"] is False
    assert len(list_objects(captured["model_path"])) == 4


def test_copies_on_a_normal_printer_are_arranged_by_the_slicer(client, tmp_path, monkeypatch):
    from app.routers import jobs as jobs_router
    from app.threemf_objects import list_objects

    model_id = _upload_project(client, tmp_path)
    captured = _capture_slice(monkeypatch)
    monkeypatch.setattr(jobs_router, "_machine_bed", lambda name, user_id=None: (False, 125.0))
    monkeypatch.setattr(jobs_router, "_machine_bed_area", lambda name, user_id=None: (["0x0", "250x0", "250x250", "0x250"], 250.0))
    resp = client.post("/jobs", json=_job(model_id, excluded_objects=[1, 2, 3], copies=3))
    assert resp.status_code == 200
    assert captured["arrange"] is True and captured["keep_positions"] is False
    assert len(list_objects(captured["model_path"])) == 3


def test_copies_limits(client, tmp_path):
    model_id = _upload_project(client, tmp_path)
    assert client.post("/jobs", json=_job(model_id, copies=0)).status_code == 422
    assert client.post("/jobs", json=_job(model_id, copies=51)).status_code == 422
