from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile

from ..config import settings
from ..schemas import ModelUploadResponse

router = APIRouter(prefix="/models", tags=["models"])

_ALLOWED_SUFFIXES = {".stl", ".3mf", ".obj", ".step", ".stp"}
_MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500MB


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

    return ModelUploadResponse(model_id=model_id, filename=file.filename or dest.name)


def resolve_model_path(model_id: str) -> Path:
    if "/" in model_id or "\\" in model_id or ".." in model_id:
        raise HTTPException(status_code=400, detail="Invalid model_id")
    matches = list(settings.models_dir.glob(f"{model_id}.*"))
    if not matches:
        raise HTTPException(status_code=404, detail="model_id not found")
    return matches[0]
