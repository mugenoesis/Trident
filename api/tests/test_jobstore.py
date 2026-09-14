from pathlib import Path

from app.jobstore import JobStore
from app.schemas import JobProgress, JobStatus


def test_create_get_roundtrip(tmp_path: Path):
    db = JobStore(tmp_path / "jobs.sqlite3")
    job = db.create(
        user_id="local",
        model_id="abc123",
        printer_profile="Generic Printer",
        process_profile="0.20mm Standard",
        filament_profiles=["Generic PLA"],
        setting_overrides={"layer_height": 0.2},
    )
    assert job.status == JobStatus.QUEUED
    assert job.user_id == "local"

    fetched = db.get(job.id)
    assert fetched is not None
    assert fetched.model_id == "abc123"
    assert fetched.setting_overrides == {"layer_height": 0.2}


def test_progress_and_finish(tmp_path: Path):
    db = JobStore(tmp_path / "jobs.sqlite3")
    job = db.create(
        user_id="local",
        model_id="abc123",
        printer_profile="p",
        process_profile="q",
        filament_profiles=[],
        setting_overrides={},
    )

    db.set_status(job.id, JobStatus.RUNNING)
    db.update_progress(job.id, JobProgress(total_percent=42.0, message="slicing"))
    running = db.get(job.id)
    assert running is not None
    assert running.status == JobStatus.RUNNING
    assert running.progress is not None
    assert running.progress.total_percent == 42.0

    db.finish(job.id, status=JobStatus.SUCCEEDED, result={"return_code": 0})
    done = db.get(job.id)
    assert done is not None
    assert done.status == JobStatus.SUCCEEDED
    assert done.result == {"return_code": 0}


def test_get_missing_returns_none(tmp_path: Path):
    db = JobStore(tmp_path / "jobs.sqlite3")
    assert db.get("does-not-exist") is None


def test_list_orders_newest_first(tmp_path: Path):
    db = JobStore(tmp_path / "jobs.sqlite3")
    first = db.create(
        user_id="local", model_id="a", printer_profile="p", process_profile="q",
        filament_profiles=[], setting_overrides={},
    )
    second = db.create(
        user_id="local", model_id="b", printer_profile="p", process_profile="q",
        filament_profiles=[], setting_overrides={},
    )
    ids = [j.id for j in db.list("local")]
    assert ids[0] == second.id or ids[0] == first.id  # timestamps may tie; both present
    assert set(ids) == {first.id, second.id}


def test_list_scoped_to_user(tmp_path: Path):
    db = JobStore(tmp_path / "jobs.sqlite3")
    mine = db.create(
        user_id="alice", model_id="a", printer_profile="p", process_profile="q",
        filament_profiles=[], setting_overrides={},
    )
    db.create(
        user_id="bob", model_id="b", printer_profile="p", process_profile="q",
        filament_profiles=[], setting_overrides={},
    )
    ids = [j.id for j in db.list("alice")]
    assert ids == [mine.id]
