from __future__ import annotations

import shutil
import uuid

from fastapi import APIRouter, Depends, HTTPException

from .. import sample_models as sample_catalog
from ..auth import require_user
from ..config import settings
from ..schemas import ModelUploadResponse, SampleModelSummary
from ..userstore import User
from .models import finalize_new_model

router = APIRouter(prefix="/sample-models", tags=["sample-models"])


@router.get("", response_model=list[SampleModelSummary])
def list_sample_models() -> list[SampleModelSummary]:
    return [
        SampleModelSummary(id=s.id, name=s.name, description=s.description)
        for s in sample_catalog.list_samples()
    ]


@router.post("/{sample_id}/load", response_model=ModelUploadResponse)
def load_sample_model(sample_id: str, current: User = Depends(require_user)) -> ModelUploadResponse:
    """Copies a bundled sample into a fresh model_id -- same shape as a
    regular upload (routers/models.py's upload_model), so the frontend can
    treat the two identically from this point on."""
    sample = sample_catalog.get_sample(sample_id)
    if sample is None:
        raise HTTPException(status_code=404, detail="Unknown sample model")
    source_path = sample_catalog.resolve_sample_path(sample)
    if not source_path.is_file():
        raise HTTPException(status_code=500, detail="Sample model file missing from this build")

    model_id = uuid.uuid4().hex
    suffix = source_path.suffix.lower()
    settings.models_dir.mkdir(parents=True, exist_ok=True)
    dest = settings.models_dir / f"{model_id}{suffix}"
    shutil.copyfile(source_path, dest)

    # Extension included (unlike the bare display name) -- the frontend
    # needs it to pick the right 3D-viewer loader when it re-fetches this
    # file's bytes (GET /models/{id}/file), the same way it already relies
    # on a normal upload's own filename for that.
    return finalize_new_model(model_id, suffix, dest, f"{sample.name}{suffix}", current.id)
