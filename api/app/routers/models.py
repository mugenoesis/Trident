from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile

from ..config import settings
from ..schemas import ModelUploadResponse

router = APIRouter(prefix="/models", tags=["models"])

_ALLOWED_SUFFIXES = {".stl", ".3mf", ".obj", ".step", ".stp"}
_MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500MB

# Sidecar metadata (currently just the original filename, so downloaded
# G-code can be named after the upload instead of OrcaSlicer's generic
# "plate_N.gcode" -- see routers/jobs.py). A subdirectory, not
# f"{model_id}.name" next to the model itself: resolve_model_path() globs
# f"{model_id}.*" and returning the sidecar instead of the actual model
# would be a matter of glob ordering luck.
_META_DIRNAME = ".meta"


@router.post("", response_model=ModelUploadResponse)
async def upload_model(file: UploadFile) -> ModelUploadResponse:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type {suffix!r}; allowed: {sorted(_ALLOWED_SUFFIXES)}",
        )

    model_id = uuid.uuid4().hex
    settings.models_dir.mkdir(parents=True, exist_ok=True)
    dest = settings.models_dir / f"{model_id}{suffix}"

    size = 0
    with dest.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > _MAX_UPLOAD_BYTES:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="File too large")
            out.write(chunk)

    original_name = file.filename or dest.name
    meta_dir = settings.models_dir / _META_DIRNAME
    meta_dir.mkdir(parents=True, exist_ok=True)
    (meta_dir / f"{model_id}.name").write_text(original_name)

    return ModelUploadResponse(model_id=model_id, filename=original_name)


def resolve_model_path(model_id: str) -> Path:
    if "/" in model_id or "\\" in model_id or ".." in model_id:
        raise HTTPException(status_code=400, detail="Invalid model_id")
    matches = list(settings.models_dir.glob(f"{model_id}.*"))
    if not matches:
        raise HTTPException(status_code=404, detail="model_id not found")
    return matches[0]


def resolve_model_original_name(model_id: str) -> str | None:
    """The filename the model was originally uploaded as, if known.

    Used to name downloaded G-code after the upload instead of OrcaSlicer's
    generic "plate_N.gcode" (routers/jobs.py). None for models uploaded
    before this metadata existed, or if the sidecar was somehow lost --
    callers should fall back to the actual output filename.
    """
    meta_file = settings.models_dir / _META_DIRNAME / f"{model_id}.name"
    if not meta_file.is_file():
        return None
    return meta_file.read_text().strip() or None
