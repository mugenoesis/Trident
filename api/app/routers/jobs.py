from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse

from .. import cli_runner
from ..blocked_settings import blocked_keys
from ..config import settings
from ..jobstore import store
from ..schemas import JobCreateRequest, JobRecord, JobStatus
from .models import resolve_model_path

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
def create_job(request: JobCreateRequest, background_tasks: BackgroundTasks) -> JobRecord:
    rejected = blocked_keys(request.setting_overrides)
    if rejected:
        raise HTTPException(
            status_code=400,
            detail=f"Settings not overridable via CLI (nocli): {sorted(rejected)}",
        )

    model_path = resolve_model_path(request.model_id)

    job = store.create(
        model_id=request.model_id,
        printer_profile=request.printer_profile,
        process_profile=request.process_profile,
        filament_profiles=request.filament_profiles,
        setting_overrides=request.setting_overrides,
    )
    background_tasks.add_task(_run_job, job.id, model_path, request)
    return job


@router.get("", response_model=list[JobRecord])
def list_jobs() -> list[JobRecord]:
    return store.list()


@router.get("/{job_id}", response_model=JobRecord)
def get_job(job_id: str) -> JobRecord:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/{job_id}/gcode")
def get_job_gcode(job_id: str) -> FileResponse:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    matches = list(_job_output_dir(job_id).glob("*.gcode"))
    if not matches:
        raise HTTPException(status_code=404, detail="No gcode produced (yet) for this job")
    return FileResponse(matches[0], media_type="text/plain", filename=matches[0].name)


@router.get("/{job_id}/thumbnail")
def get_job_thumbnail(job_id: str) -> FileResponse:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    matches = list(_job_output_dir(job_id).glob("*.png"))
    if not matches:
        raise HTTPException(status_code=404, detail="No thumbnail produced (yet) for this job")
    return FileResponse(matches[0], media_type="image/png", filename=matches[0].name)
