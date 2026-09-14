from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone

from app import cleanup
from app.config import settings
from app.jobstore import store
from app.schemas import JobStatus


def _upload_model(client) -> str:
    resp = client.post(
        "/models", files={"file": ("cube.stl", io.BytesIO(b"fake stl bytes"), "model/stl")}
    )
    assert resp.status_code == 200
    return resp.json()["model_id"]


def _age_model(model_id: str, hours: float) -> None:
    meta_file = settings.models_dir / ".meta" / f"{model_id}.json"
    data = json.loads(meta_file.read_text())
    data["uploaded_at"] = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    meta_file.write_text(json.dumps(data))


def _age_job(job_id: str, hours: float) -> None:
    with store._connect() as conn:  # noqa: SLF001 - test-only reach into the store
        conn.execute(
            "UPDATE jobs SET created_at = ? WHERE id = ?",
            ((datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(), job_id),
        )


def test_expired_terminal_job_and_orphaned_model_are_purged(client):
    model_id = _upload_model(client)
    job = store.create(
        user_id="local",
        model_id=model_id,
        printer_profile="p",
        process_profile="q",
        filament_profiles=[],
        setting_overrides={},
    )
    store.finish(job.id, status=JobStatus.SUCCEEDED, result={"ok": True})
    output_dir = settings.output_dir / job.id
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "plate_1.gcode").write_text("; fake\n")

    _age_job(job.id, hours=100)
    _age_model(model_id, hours=100)

    cleanup.run_cleanup_once()

    assert store.get(job.id) is None
    assert not output_dir.exists()
    assert not list(settings.models_dir.glob(f"{model_id}.*"))
    assert not (settings.models_dir / ".meta" / f"{model_id}.json").exists()


def test_active_job_survives_regardless_of_age(client):
    model_id = _upload_model(client)
    job = store.create(
        user_id="local",
        model_id=model_id,
        printer_profile="p",
        process_profile="q",
        filament_profiles=[],
        setting_overrides={},
    )
    # Left QUEUED -- never touched, no matter how old.
    _age_job(job.id, hours=1000)
    _age_model(model_id, hours=1000)

    cleanup.run_cleanup_once()

    assert store.get(job.id) is not None
    assert list(settings.models_dir.glob(f"{model_id}.*"))


def test_model_with_a_surviving_job_is_not_deleted(client):
    model_id = _upload_model(client)
    old_job = store.create(
        user_id="local", model_id=model_id, printer_profile="p", process_profile="q",
        filament_profiles=[], setting_overrides={},
    )
    store.finish(old_job.id, status=JobStatus.SUCCEEDED, result={})
    _age_job(old_job.id, hours=100)

    recent_job = store.create(
        user_id="local", model_id=model_id, printer_profile="p", process_profile="q",
        filament_profiles=[], setting_overrides={},
    )
    store.finish(recent_job.id, status=JobStatus.SUCCEEDED, result={})
    # recent_job is fresh (not aged), so the model still has a live reference.
    _age_model(model_id, hours=100)

    cleanup.run_cleanup_once()

    assert store.get(old_job.id) is None
    assert store.get(recent_job.id) is not None
    assert list(settings.models_dir.glob(f"{model_id}.*"))


def test_fresh_terminal_job_is_not_purged(client):
    model_id = _upload_model(client)
    job = store.create(
        user_id="local", model_id=model_id, printer_profile="p", process_profile="q",
        filament_profiles=[], setting_overrides={},
    )
    store.finish(job.id, status=JobStatus.SUCCEEDED, result={})

    cleanup.run_cleanup_once()

    assert store.get(job.id) is not None


def test_delete_job_endpoint_removes_output_and_orphaned_model(client, monkeypatch):
    from app import cli_runner
    from app.cli_runner import SliceResult

    def fake_run_slice(**kwargs):
        output_dir = kwargs["output_dir"]
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "plate_1.gcode").write_text("; fake\n")
        return SliceResult(
            return_code=0, result_json={"return_code": 0}, stdout="", stderr="", used_result_json=True
        )

    monkeypatch.setattr(cli_runner, "run_slice", fake_run_slice)

    model_id = _upload_model(client)
    job_resp = client.post(
        "/jobs",
        json={"model_id": model_id, "printer_profile": "p", "process_profile": "q"},
    )
    job_id = job_resp.json()["id"]
    assert client.get(f"/jobs/{job_id}").json()["status"] == "succeeded"

    resp = client.delete(f"/jobs/{job_id}")
    assert resp.status_code == 200
    assert client.get(f"/jobs/{job_id}").status_code == 404
    assert not (settings.output_dir / job_id).exists()
    assert not list(settings.models_dir.glob(f"{model_id}.*"))


def test_delete_job_of_another_user_404s(client):
    client.post("/auth/setup", json={"mode": "multi", "username": "alice", "password": "pw12345"})
    model_id = _upload_model(client)
    job = store.create(
        user_id="local", model_id=model_id, printer_profile="p", process_profile="q",
        filament_profiles=[], setting_overrides={},
    )
    resp = client.delete(f"/jobs/{job.id}")
    assert resp.status_code == 404
    assert store.get(job.id) is not None
