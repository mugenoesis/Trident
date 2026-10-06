from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile

from .. import profiles as profiles_module
from .. import userprofiles
from ..auth import require_user
from ..schemas import (
    ExportRequest,
    FilamentForm,
    ImportedProfile,
    ImportResult,
    PrinterForm,
    ProfileDetail,
    ProfileSummary,
    SettingsSchema,
)
from ..settings_schema import build_settings_schema
from ..userstore import User

router = APIRouter(tags=["profiles"])


@router.get("/profiles", response_model=list[ProfileSummary])
def list_profiles(current: User = Depends(require_user)) -> list[ProfileSummary]:
    # Built-in profiles plus whatever this user imported (vendor "My profiles").
    return profiles_module.catalog.list(current.id)


@router.get("/profiles/imported", response_model=list[ImportedProfile])
def list_imported(current: User = Depends(require_user)) -> list[ImportedProfile]:
    user_raw = userprofiles.store.load_all(current.id)
    return [
        ImportedProfile(kind=kind, name=name, inherits=data.get("inherits") or None)
        for (kind, name), data in sorted(user_raw.items())
    ]


@router.post("/profiles/import", response_model=ImportResult)
async def import_profiles(
    files: list[UploadFile] = File(...),
    overwrite: bool = Form(False),
    current: User = Depends(require_user),
) -> ImportResult:
    """Same files OrcaSlicer's File > Import > Import Configs takes: .json
    presets and .zip/.orca_printer/.orca_filament/.orca_bundle bundles."""
    presets: list[userprofiles.ParsedPreset] = []
    issues: list[userprofiles.ImportIssue] = []
    for upload in files:
        raw = await upload.read(userprofiles._MAX_ZIP_UNCOMPRESSED + 1)
        found, problems = userprofiles.parse_upload(upload.filename or "profile.json", raw)
        presets += found
        issues += problems
    return profiles_module.catalog.import_for_user(current.id, presets, issues, overwrite)


def _filament_values(body: FilamentForm) -> dict:
    values = body.model_dump(exclude={"name", "base_name", "plate_temps"})
    for key, number in body.plate_temps.items():
        if key not in userprofiles.PLATE_TEMP_KEYS:
            raise HTTPException(status_code=422, detail=f"'{key}' is not a bed temperature setting")
        values[key] = number
    return values


def _save_filament(user_id: str, body: FilamentForm, edit: bool) -> ImportedProfile:
    try:
        return profiles_module.catalog.save_filament(
            user_id, body.name.strip(), _filament_values(body), base_name=body.base_name, edit=edit
        )
    except userprofiles.MaterialConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except userprofiles.MaterialNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except userprofiles.MaterialError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/profiles/filaments", response_model=ImportedProfile)
def create_filament(body: FilamentForm, current: User = Depends(require_user)) -> ImportedProfile:
    """A new material of the user's own: a copy of `base_name` with the form's settings."""
    return _save_filament(current.id, body, edit=False)


@router.put("/profiles/filaments/{name}", response_model=ImportedProfile)
def update_filament(name: str, body: FilamentForm, current: User = Depends(require_user)) -> ImportedProfile:
    if body.name.strip() != name:
        raise HTTPException(status_code=422, detail="A material cannot be renamed; save it under a new name instead")
    return _save_filament(current.id, body, edit=True)


@router.delete("/profiles/imported/{kind}/{name}")
def delete_imported(kind: str, name: str, current: User = Depends(require_user)) -> dict[str, bool]:
    if not profiles_module.catalog.delete_imported(current.id, kind, name):
        raise HTTPException(status_code=404, detail="Imported profile not found")
    return {"deleted": True}


@router.get("/profiles/{vendor}/{kind}/{name}", response_model=ProfileDetail)
def get_profile(vendor: str, kind: str, name: str, current: User = Depends(require_user)) -> ProfileDetail:
    detail = profiles_module.catalog.get(vendor, kind, name, current.id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return detail


@router.get("/settings/schema", response_model=SettingsSchema)
def get_settings_schema() -> SettingsSchema:
    return build_settings_schema()


def _printer_values(body: PrinterForm) -> dict:
    return body.model_dump(exclude={"name", "base_name"})


def _save_printer(user_id: str, body: PrinterForm, edit: bool) -> ImportedProfile:
    try:
        return profiles_module.catalog.save_printer(
            user_id, body.name.strip(), _printer_values(body), base_name=body.base_name, edit=edit
        )
    except userprofiles.PrinterConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except userprofiles.PrinterNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except userprofiles.PrinterError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/profiles/printers", response_model=ImportedProfile)
def create_printer(body: PrinterForm, current: User = Depends(require_user)) -> ImportedProfile:
    """A new printer of the user's own: a copy of `base_name` (or a generic printer) with the form's settings."""
    return _save_printer(current.id, body, edit=False)


@router.put("/profiles/printers/{name}", response_model=ImportedProfile)
def update_printer(name: str, body: PrinterForm, current: User = Depends(require_user)) -> ImportedProfile:
    if body.name.strip() != name:
        raise HTTPException(status_code=422, detail="A printer cannot be renamed; save it under a new name instead")
    return _save_printer(current.id, body, edit=True)


@router.get("/stored-profiles/machine/{name}")
def get_stored_printer(name: str, current: User = Depends(require_user)) -> dict:
    """What the user set on one of their printers (not the inherited values), so the editor can list the
    advanced settings it holds."""
    stored = profiles_module.catalog.stored_preset(current.id, "machine", name)
    if stored is None:
        raise HTTPException(status_code=404, detail="Printer not found")
    return stored


@router.get("/profiles/printer-keys", response_model=list[str])
def printer_keys(current: User = Depends(require_user)) -> list[str]:
    """The settings a printer preset holds, so the Advanced tab can offer those and no others."""
    from ..printer_keys import PRINTER_KEYS

    return sorted(PRINTER_KEYS - userprofiles.PRINTER_MANAGED_KEYS - userprofiles._PRINTER_META_KEYS)


@router.post("/profiles/export")
def export_profiles(body: ExportRequest, current: User = Depends(require_user)) -> Response:
    """The chosen presets of the user as a file desktop OrcaSlicer imports (.orca_printer / .orca_filament /
    .orca_bundle)."""
    try:
        data, filename = userprofiles.build_export(current.id, [(i.kind, i.name) for i in body.items])
    except userprofiles.PrinterNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except userprofiles.PrinterError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
