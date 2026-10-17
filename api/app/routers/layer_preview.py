from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response

from .. import layer_preview
from ..auth import require_user
from ..schemas import JobStatus, LayerPreviewStatus
from ..userstore import User
from .jobs import _get_owned_job, _job_output_dir
from .models import resolve_model_path

router = APIRouter(prefix="/jobs", tags=["resin"])


@router.post("/{job_id}/layer-preview", response_model=LayerPreviewStatus)
def start_layer_preview(
    job_id: str, background_tasks: BackgroundTasks, current: User = Depends(require_user)
) -> LayerPreviewStatus:
    """Make the layer images of a finished resin job again if they are not there (a job makes them itself; this is for a failed one).

    Asking while one is running or ready does nothing.
    """
    job = _get_owned_job(job_id, current)
    if job.status != JobStatus.SUCCEEDED or (job.result or {}).get("printer_technology") != "SLA":
        raise HTTPException(status_code=409, detail="Only a finished resin job has a layer preview")
    out = _job_output_dir(job_id)
    if layer_preview.begin(out):
        background_tasks.add_task(
            layer_preview.generate,
            out=out,
            model_path=resolve_model_path(job.model_id),
            printer_name=job.printer_profile,
            resin_name=job.filament_profiles[0] if job.filament_profiles else None,
            overrides=job.setting_overrides,
            user_id=job.user_id,
        )
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
