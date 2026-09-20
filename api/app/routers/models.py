from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .. import threemf
from ..auth import require_user
from ..config import settings
from ..schemas import ColorNode, ModelUploadResponse, PlateInfo, ThreeMfInspection
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


def finalize_new_model(
    model_id: str, suffix: str, dest: Path, original_name: str, owner_user_id: str
) -> ModelUploadResponse:
    """Writes the sidecar meta (+ .3mf plate/material inspection, best
    effort) for a model file that's already been written to `dest` --
    shared by the upload route below and the sample-model loader
    (routers/sample_models.py), which copies a bundled file to the same
    place instead of streaming an upload."""
    meta_dir = settings.models_dir / _META_DIRNAME
    meta_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "filename": original_name,
        "owner_user_id": owner_user_id,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    if suffix == ".3mf":
        try:
            inspection = threemf.inspect_3mf(dest)
            meta["plates"] = [p.model_dump() for p in inspection.plates]
            meta["extruder_indices"] = inspection.extruder_indices
            meta["embedded_filament_colors"] = inspection.embedded_filament_colors
            meta["embedded_filament_names"] = inspection.embedded_filament_names
            meta["color_tree"] = [c.model_dump() for c in inspection.color_tree]
        except Exception:  # noqa: BLE001 - a parse bug must never fail this itself
            pass
    _meta_path(model_id).write_text(json.dumps(meta))

    return ModelUploadResponse(model_id=model_id, filename=original_name)


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
    return finalize_new_model(model_id, suffix, dest, original_name, current.id)


@router.get("/{model_id}/file")
def get_model_file(model_id: str, current: User = Depends(require_user)) -> FileResponse:
    """The original model bytes, for the frontend to re-fetch into a
    browser-side File/Blob it never had itself -- notably a sample model
    loaded server-side (routers/sample_models.py) via POST /sample-models/
    {id}/load, which returns a model_id but no bytes the browser already
    holds the way a local upload does."""
    owner = resolve_model_owner(model_id)
    if owner is not None and owner != current.id:
        raise HTTPException(status_code=404, detail="model_id not found")
    path = resolve_model_path(model_id)
    original_name = resolve_model_original_name(model_id) or path.name
    return FileResponse(path, media_type="application/octet-stream", filename=original_name)


@router.get("/{model_id}/plates", response_model=ThreeMfInspection)
def get_model_plates(model_id: str, current: User = Depends(require_user)) -> ThreeMfInspection:
    resolve_model_path(model_id)  # 404s on unknown/invalid model_id
    owner = resolve_model_owner(model_id)
    if owner is not None and owner != current.id:
        raise HTTPException(status_code=404, detail="model_id not found")
    return resolve_model_plates(model_id)


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


def reassign_all_models_to_user(user_id: str) -> None:
    """Used by switch-to-single: merges every uploaded model, regardless of
    current owner, onto one account."""
    meta_dir = settings.models_dir / _META_DIRNAME
    if not meta_dir.is_dir():
        return
    for meta_file in meta_dir.glob("*.json"):
        try:
            data = json.loads(meta_file.read_text())
        except (OSError, ValueError):
            continue
        data["owner_user_id"] = user_id
        meta_file.write_text(json.dumps(data))


def delete_model(model_id: str) -> None:
    """Removes the uploaded model file(s) and its metadata sidecar.

    Used both by the explicit DELETE /jobs/{id} route (when it was the last
    job referencing this model) and the cleanup sweep (cleanup.py).
    """
    for f in settings.models_dir.glob(f"{model_id}.*"):
        f.unlink(missing_ok=True)
    _meta_path(model_id).unlink(missing_ok=True)


def resolve_model_plates(model_id: str) -> ThreeMfInspection:
    """The model's parsed plate/material-slot info -- always returns a
    shape, so callers never need a separate "is this even a 3mf" branch.

    Fast path: the sidecar already has it (set at upload time). Otherwise,
    for a .3mf uploaded before this feature shipped, parse it on the fly and
    best-effort re-persist for next time. Anything else (non-3mf, or a .3mf
    whose parse genuinely failed) gets a synthetic single implicit plate.
    """
    meta = _read_meta(model_id) or {}
    if "plates" in meta:
        return ThreeMfInspection(
            plates=[PlateInfo(**p) for p in meta["plates"]],
            extruder_indices=meta.get("extruder_indices", []),
            embedded_filament_colors=meta.get("embedded_filament_colors", []),
            embedded_filament_names=meta.get("embedded_filament_names", []),
            color_tree=[ColorNode(**c) for c in meta.get("color_tree", [])],
        )

    model_path = resolve_model_path(model_id)
    if model_path.suffix.lower() == ".3mf":
        inspection = threemf.inspect_3mf(model_path)
        try:
            meta["plates"] = [p.model_dump() for p in inspection.plates]
            meta["extruder_indices"] = inspection.extruder_indices
            meta["embedded_filament_colors"] = inspection.embedded_filament_colors
            meta["embedded_filament_names"] = inspection.embedded_filament_names
            meta["color_tree"] = [c.model_dump() for c in inspection.color_tree]
            _meta_path(model_id).write_text(json.dumps(meta))
        except OSError:
            pass  # cache write is best-effort, not a source of truth
        return inspection

    return ThreeMfInspection(plates=[PlateInfo(index=1)])


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
