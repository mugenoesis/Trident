from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from ..auth import require_user
from ..config import settings
from ..schemas import ModelUploadResponse
from ..userstore import User

router = APIRouter(prefix="/models", tags=["models"])

_ALLOWED_SUFFIXES = {".stl", ".3mf", ".obj", ".step", ".stp"}
_MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500MB

# Sidecar metadata: original filename (so downloaded G-code can be named
# after the upload instead of OrcaSlicer's generic "plate_N.gcode" -- see
# routers/jobs.py), owner, and upload time (used by the cleanup sweep). A
# subdirectory, not f"{model_id}.name" next to the model itself:
# resolve_model_path() globs f"{model_id}.*" and returning the sidecar
# instead of the actual model would be a matter of glob ordering luck.
_META_DIRNAME = ".meta"


def _meta_path(model_id: str) -> Path:
    return settings.models_dir / _META_DIRNAME / f"{model_id}.json"


def _read_meta(model_id: str) -> dict | None:
    meta_file = _meta_path(model_id)
    if not meta_file.is_file():
        return None
    try:
        return json.loads(meta_file.read_text())
    except (OSError, ValueError):
        return None


@router.post("", response_model=ModelUploadResponse)
async def upload_model(file: UploadFile, current: User = Depends(require_user)) -> ModelUploadResponse:
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
    meta = {
        "filename": original_name,
        "owner_user_id": current.id,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    _meta_path(model_id).write_text(json.dumps(meta))

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
    meta = _read_meta(model_id)
    return (meta or {}).get("filename") or None


def resolve_model_owner(model_id: str) -> str | None:
    """The uploading user's id, or None if unknown (predates ownership
    tracking, or the sidecar is missing) -- callers should treat unknown
    ownership as accessible rather than reject it."""
    meta = _read_meta(model_id)
    return (meta or {}).get("owner_user_id") or None


def resolve_model_uploaded_at(model_id: str) -> datetime | None:
    """When the model was uploaded, if known -- used by the cleanup sweep
    to age out old, unreferenced uploads."""
    meta = _read_meta(model_id)
    raw = (meta or {}).get("uploaded_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None
