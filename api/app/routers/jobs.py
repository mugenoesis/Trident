from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse

from .. import cli_runner, gcode_stats, gcode_thumbnail
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
            plate_index=request.plate_index,
            on_progress=lambda p: store.update_progress(job_id, p),
        )
    except Exception as exc:  # noqa: BLE001 - report to job record, don't crash the worker
        store.finish(job_id, status=JobStatus.FAILED, error=str(exc))
        return

    if result.succeeded:
        if request.preview_image_base64:
            gcode_thumbnail.embed_preview(_job_output_dir(job_id), request.preview_image_base64)
        # OrcaSlicer's own result.json never carries this (see
        # gcode_stats.py) -- folded into the same free-form result blob
        # rather than a new JobRecord/DB column, same as everything else
        # here that's "whatever the slice produced."
        result_json = dict(result.result_json) if result.result_json else {}
        filament_grams = gcode_stats.total_filament_grams_for_job(_job_output_dir(job_id))
        if filament_grams is not None:
            result_json["filament_used_g"] = round(filament_grams, 2)
        store.finish(job_id, status=JobStatus.SUCCEEDED, result=result_json)
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
        plate_index=request.plate_index,
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


def resolve_job_gcode_path(job_id: str) -> Path:
    """The on-disk sliced gcode file for a job -- shared by the download
    route below and the send-to-printer route (routers/printers.py), which
    needs the same file to actually upload it.

    When the job requested a specific plate, OrcaSlicer names its output
    plate_{plate_index}.gcode (confirmed: --slice N and the resulting
    plate_N.gcode share the same 1-based N) -- prefer that exact file so a
    job never returns some other plate's output by glob-order luck. Falls
    through to the glob for every job that didn't request a specific plate
    (including all jobs predating plate_index), or if the specific file
    isn't there yet (still slicing) -- same "not ready yet" 404 as today.
    """
    job = store.get(job_id)
    if job is not None and job.plate_index is not None:
        specific = _job_output_dir(job_id) / f"plate_{job.plate_index}.gcode"
        if specific.is_file():
            return specific
    matches = list(_job_output_dir(job_id).glob("*.gcode"))
    if not matches:
        raise HTTPException(status_code=404, detail="No gcode produced (yet) for this job")
    return matches[0]


@router.get("/{job_id}/gcode")
def get_job_gcode(job_id: str, current: User = Depends(require_user)) -> FileResponse:
    job = _get_owned_job(job_id, current)
    gcode_path = resolve_job_gcode_path(job_id)

    # Name the download after the upload (e.g. "my_model.gcode") rather than
    # OrcaSlicer's generic on-disk "plate_1.gcode", which means nothing once
    # there's more than one job in flight. Falls back to the actual output
    # filename for models uploaded before this metadata existed.
    original_name = resolve_model_original_name(job.model_id)
    download_name = f"{Path(original_name).stem}.gcode" if original_name else gcode_path.name

    # Not text/plain: .gcode isn't a MIME-registered extension, and browsers
    # (confirmed: Chrome on Android) "correct" the download filename to match
    # the Content-Type they were given, appending .txt over the intended
    # .gcode. application/octet-stream is the standard fix -- it doesn't map
    # to any particular extension, so the filename's own .gcode is left alone.
    return FileResponse(
        gcode_path, media_type="application/octet-stream", filename=download_name
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
