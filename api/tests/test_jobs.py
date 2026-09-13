import io

from app import cli_runner
from app.cli_runner import SliceResult


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
