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

    monkeypatch.setattr(jobs_router, "_machine_bed", lambda name: (False, 125.0))
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

    monkeypatch.setattr(jobs_router, "_machine_bed", lambda name: (True, 125.0))
    resp = client.post(
        "/jobs",
        json=_job(model_id, excluded_objects=[1], belt_layout={"order": [3, 0, 2], "gap_mm": 12}),
    )
    assert resp.status_code == 200
    assert captured["plate_index"] == 1
    assert captured["arrange"] is False
    objs = list_objects(captured["model_path"])
    assert [o.name for o in objs] == ["Block A", "Wide C", "Cube D"]
    assert {o.plate for o in objs} == {1}


def test_belt_layout_ignored_on_non_belt_printer(client, tmp_path, monkeypatch):
    model_id = _upload_project(client, tmp_path)
    captured = _capture_slice(monkeypatch)
    from app.routers import jobs as jobs_router

    monkeypatch.setattr(jobs_router, "_machine_bed", lambda name: (False, 125.0))
    resp = client.post("/jobs", json=_job(model_id, belt_layout={"order": [0, 1, 2, 3]}, plate_index=2))
    assert resp.status_code == 200
    assert captured["plate_index"] == 2
    assert captured["arrange"] is True
