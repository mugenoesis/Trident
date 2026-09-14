from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse

from .. import cli_runner
from ..auth import require_user
from ..blocked_settings import blocked_keys
from ..config import settings
from ..jobstore import store
from ..schemas import JobCreateRequest, JobRecord, JobStatus
from ..userstore import User
from .models import delete_model, resolve_model_original_name, resolve_model_owner, resolve_model_path

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _job_output_dir(job_id: str) -> Path:
    return settings.output_dir / job_id


def _run_job(job_id: str, model_path: Path, request: JobCreateRequest) -> None:
    store.set_status(job_id, JobStatus.RUNNING)
    try:
        result = cli_runner.run_slice(
            model_path=model_path,
            output_dir=_job_output_dir(job_id),
            printer_profile=request.printer_profile,
            process_profile=request.process_profile,
            filament_profiles=request.filament_profiles,
            setting_overrides=request.setting_overrides,
            on_progress=lambda p: store.update_progress(job_id, p),
        )
    except Exception as exc:  # noqa: BLE001 - report to job record, don't crash the worker
        store.finish(job_id, status=JobStatus.FAILED, error=str(exc))
        return

    if result.succeeded:
        store.finish(job_id, status=JobStatus.SUCCEEDED, result=result.result_json)
    else:
        error = result.result_json.get("error_string") if result.result_json else result.stderr
        store.finish(
            job_id,
            status=JobStatus.FAILED,
            result=result.result_json,
            error=error or f"exit code {result.return_code}",
        )


@router.post("", response_model=JobRecord)
def create_job(
    request: JobCreateRequest, background_tasks: BackgroundTasks, current: User = Depends(require_user)
) -> JobRecord:
    rejected = blocked_keys(request.setting_overrides)
    if rejected:
        raise HTTPException(
            status_code=400,
            detail=f"Settings not overridable via CLI (nocli): {sorted(rejected)}",
        )

    model_path = resolve_model_path(request.model_id)
    # A model with no recorded owner predates per-user ownership and stays
    # accessible (nothing to enforce); one with a *different* owner is a 404,
    # not a 403, so this doesn't confirm the model_id exists to a non-owner.
    owner = resolve_model_owner(request.model_id)
    if owner is not None and owner != current.id:
        raise HTTPException(status_code=404, detail="model_id not found")

    job = store.create(
        user_id=current.id,
        model_id=request.model_id,
        printer_profile=request.printer_profile,
        process_profile=request.process_profile,
        filament_profiles=request.filament_profiles,
        setting_overrides=request.setting_overrides,
    )
    background_tasks.add_task(_run_job, job.id, model_path, request)
    return job


@router.get("", response_model=list[JobRecord])
def list_jobs(current: User = Depends(require_user)) -> list[JobRecord]:
    return store.list(current.id)


def _get_owned_job(job_id: str, current: User) -> JobRecord:
    job = store.get(job_id)
    if job is None or job.user_id != current.id:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/{job_id}", response_model=JobRecord)
def get_job(job_id: str, current: User = Depends(require_user)) -> JobRecord:
    return _get_owned_job(job_id, current)


@router.get("/{job_id}/gcode")
def get_job_gcode(job_id: str, current: User = Depends(require_user)) -> FileResponse:
    job = _get_owned_job(job_id, current)
    matches = list(_job_output_dir(job_id).glob("*.gcode"))
    if not matches:
        raise HTTPException(status_code=404, detail="No gcode produced (yet) for this job")

    # Name the download after the upload (e.g. "my_model.gcode") rather than
    # OrcaSlicer's generic on-disk "plate_1.gcode", which means nothing once
    # there's more than one job in flight. Falls back to the actual output
    # filename for models uploaded before this metadata existed.
    original_name = resolve_model_original_name(job.model_id)
    download_name = f"{Path(original_name).stem}.gcode" if original_name else matches[0].name

    # Not text/plain: .gcode isn't a MIME-registered extension, and browsers
    # (confirmed: Chrome on Android) "correct" the download filename to match
    # the Content-Type they were given, appending .txt over the intended
    # .gcode. application/octet-stream is the standard fix -- it doesn't map
    # to any particular extension, so the filename's own .gcode is left alone.
    return FileResponse(
        matches[0], media_type="application/octet-stream", filename=download_name
    )


@router.delete("/{job_id}")
def delete_job(job_id: str, current: User = Depends(require_user)) -> dict[str, bool]:
    """"I'm finished with this" -- deletes the job's output (gcode/thumbnail)
    immediately, and the uploaded model too if no other job still points at
    it. Complements the automatic retention sweep (cleanup.py) for anyone
    who wants files gone right away instead of waiting out the retention
    window."""
    job = _get_owned_job(job_id, current)
    shutil.rmtree(_job_output_dir(job_id), ignore_errors=True)
    store.delete(job_id)
    still_referenced = any(j.model_id == job.model_id for j in store.list_all())
    if not still_referenced:
        delete_model(job.model_id)
    return {"ok": True}


@router.get("/{job_id}/thumbnail")
def get_job_thumbnail(job_id: str, current: User = Depends(require_user)) -> FileResponse:
    _get_owned_job(job_id, current)
    matches = list(_job_output_dir(job_id).glob("*.png"))
    if not matches:
        raise HTTPException(status_code=404, detail="No thumbnail produced (yet) for this job")
    return FileResponse(matches[0], media_type="image/png", filename=matches[0].name)
