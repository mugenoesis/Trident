from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response

from .. import layer_preview, resin_runner
from ..auth import require_user
from ..schemas import JobRecord, JobStatus, LayerPreviewStatus
from ..userstore import User
from .jobs import _get_owned_job, _job_output_dir
from .models import resolve_model_path

router = APIRouter(prefix="/jobs", tags=["resin"])


def _run_preview(job: JobRecord) -> None:
    """Slice the job's model again, to SL1, into the job's preview folder."""
    out = _job_output_dir(job.id)
    try:
        result = resin_runner.run_resin_slice(
            model_path=resolve_model_path(job.model_id),
            output_dir=out / layer_preview.PREVIEW_DIR,
            printer_name=job.printer_profile,
            resin_name=job.filament_profiles[0] if job.filament_profiles else None,
            setting_overrides=job.setting_overrides,
            timeout_s=1800.0,
            user_id=job.user_id,
            archive_format=layer_preview.ARCHIVE_FORMAT,
        )
        if not result.succeeded:
            error = (result.result_json or {}).get("error_string") or result.stderr
            layer_preview.finish_failed(out, error or f"exit code {result.return_code}")
            return
        layer_preview.finish_ready(
            out, layer_preview.count_layers(out / layer_preview.PREVIEW_DIR / layer_preview.ARCHIVE_NAME)
        )
    except Exception as exc:
        layer_preview.finish_failed(out, str(exc))


@router.post("/{job_id}/layer-preview", response_model=LayerPreviewStatus)
def start_layer_preview(
    job_id: str, background_tasks: BackgroundTasks, current: User = Depends(require_user)
) -> LayerPreviewStatus:
    """Make the layer images of a finished resin job (once; asking again while it runs or after it is ready does nothing)."""
    job = _get_owned_job(job_id, current)
    if job.status != JobStatus.SUCCEEDED or (job.result or {}).get("printer_technology") != "SLA":
        raise HTTPException(status_code=409, detail="Only a finished resin job has a layer preview")
    out = _job_output_dir(job_id)
    if layer_preview.begin(out):
        background_tasks.add_task(_run_preview, job)
    return LayerPreviewStatus(**layer_preview.status(out))


@router.get("/{job_id}/layer-preview", response_model=LayerPreviewStatus)
def get_layer_preview(job_id: str, current: User = Depends(require_user)) -> LayerPreviewStatus:
    _get_owned_job(job_id, current)
    return LayerPreviewStatus(**layer_preview.status(_job_output_dir(job_id)))


@router.get("/{job_id}/layers/{index}.png")
def get_layer(job_id: str, index: int, current: User = Depends(require_user)) -> Response:
    _get_owned_job(job_id, current)
    png = layer_preview.layer_png(_job_output_dir(job_id), index)
    if png is None:
        raise HTTPException(status_code=404, detail="No such layer")
    return Response(content=png, media_type="image/png")
