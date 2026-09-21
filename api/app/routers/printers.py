from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import printhost
from ..auth import require_user
from ..jobstore import store as job_store
from ..printerstore import store
from ..schemas import (
    MaterialProfileCreateRequest,
    MaterialProfileRecord,
    MaterialProfileUpdateRequest,
    PrinterCreateRequest,
    PrinterRecord,
    PrinterUpdateRequest,
    SendToPrinterRequest,
    SettingsProfileCreateRequest,
    SettingsProfileRecord,
    SettingsProfileUpdateRequest,
    TestConnectionRequest,
)
from ..userstore import User
from .jobs import resolve_job_gcode_path

router = APIRouter(prefix="/printers", tags=["printers"])


def _get_owned_printer(printer_id: str, current: User) -> PrinterRecord:
    printer = store.get_printer(printer_id)
    if printer is None or store.get_owner(printer_id) != current.id:
        raise HTTPException(status_code=404, detail="Printer not found")
    return printer


@router.get("", response_model=list[PrinterRecord])
def list_printers(current: User = Depends(require_user)) -> list[PrinterRecord]:
    return store.list_printers(current.id)


@router.post("", response_model=PrinterRecord)
def create_printer(body: PrinterCreateRequest, current: User = Depends(require_user)) -> PrinterRecord:
    return store.create_printer(user_id=current.id, **body.model_dump())


@router.post("/test-connection")
async def test_connection_ad_hoc(
    body: TestConnectionRequest, current: User = Depends(require_user)  # noqa: ARG001 - auth gate only
) -> dict[str, str]:
    """Validates connection fields before a printer is even saved (the
    create-printer form's Test connection button) -- for an already-saved
    printer, POST /printers/{id}/test-connection uses its stored
    credentials instead."""
    try:
        message = await printhost.test_connection(body.model_dump())
    except printhost.PrintHostError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"message": message}


@router.put("/{printer_id}", response_model=PrinterRecord)
def update_printer(
    printer_id: str, body: PrinterUpdateRequest, current: User = Depends(require_user)
) -> PrinterRecord:
    _get_owned_printer(printer_id, current)
    # exclude_unset, not exclude_none: an empty string ("clear this field")
    # is a real, intentional value here, distinct from the field being left
    # out of the request body entirely ("don't touch this field").
    updated = store.update_printer(printer_id, **body.model_dump(exclude_unset=True))
    assert updated is not None  # just confirmed the printer exists above
    return updated


@router.delete("/{printer_id}")
def delete_printer(printer_id: str, current: User = Depends(require_user)) -> dict[str, bool]:
    _get_owned_printer(printer_id, current)
    store.delete_printer(printer_id)
    return {"ok": True}


@router.get("/{printer_id}/materials", response_model=list[MaterialProfileRecord])
def list_materials(printer_id: str, current: User = Depends(require_user)) -> list[MaterialProfileRecord]:
    _get_owned_printer(printer_id, current)
    return store.list_materials(printer_id)


@router.post("/{printer_id}/materials", response_model=MaterialProfileRecord)
def create_material(
    printer_id: str, body: MaterialProfileCreateRequest, current: User = Depends(require_user)
) -> MaterialProfileRecord:
    _get_owned_printer(printer_id, current)
    return store.create_material(printer_id=printer_id, user_id=current.id, **body.model_dump())


def _get_owned_material(printer_id: str, material_id: str, current: User) -> MaterialProfileRecord:
    _get_owned_printer(printer_id, current)
    material = store.get_material(material_id)
    if material is None or material.printer_id != printer_id:
        raise HTTPException(status_code=404, detail="Material profile not found")
    return material


@router.put("/{printer_id}/materials/{material_id}", response_model=MaterialProfileRecord)
def update_material(
    printer_id: str,
    material_id: str,
    body: MaterialProfileUpdateRequest,
    current: User = Depends(require_user),
) -> MaterialProfileRecord:
    """Covers both a plain rename and "update mode" (overwrite the saved
    settings with whatever's currently dialed in) -- same request shape,
    the frontend just chooses which fields to include."""
    _get_owned_material(printer_id, material_id, current)
    updated = store.update_material(material_id, **body.model_dump(exclude_unset=True))
    assert updated is not None  # just confirmed the material exists above
    return updated


@router.post("/{printer_id}/materials/{material_id}/duplicate", response_model=MaterialProfileRecord)
def duplicate_material(
    printer_id: str, material_id: str, current: User = Depends(require_user)
) -> MaterialProfileRecord:
    _get_owned_material(printer_id, material_id, current)
    duplicated = store.duplicate_material(material_id, user_id=current.id)
    assert duplicated is not None  # just confirmed the material exists above
    return duplicated


@router.delete("/{printer_id}/materials/{material_id}")
def delete_material(
    printer_id: str, material_id: str, current: User = Depends(require_user)
) -> dict[str, bool]:
    _get_owned_material(printer_id, material_id, current)
    store.delete_material(material_id)
    return {"ok": True}


@router.get("/{printer_id}/settings-profiles", response_model=list[SettingsProfileRecord])
def list_settings_profiles(
    printer_id: str, current: User = Depends(require_user)
) -> list[SettingsProfileRecord]:
    _get_owned_printer(printer_id, current)
    return store.list_settings_profiles(printer_id)


@router.post("/{printer_id}/settings-profiles", response_model=SettingsProfileRecord)
def create_settings_profile(
    printer_id: str, body: SettingsProfileCreateRequest, current: User = Depends(require_user)
) -> SettingsProfileRecord:
    _get_owned_printer(printer_id, current)
    return store.create_settings_profile(printer_id=printer_id, user_id=current.id, **body.model_dump())


def _get_owned_settings_profile(printer_id: str, profile_id: str, current: User) -> SettingsProfileRecord:
    _get_owned_printer(printer_id, current)
    profile = store.get_settings_profile(profile_id)
    if profile is None or profile.printer_id != printer_id:
        raise HTTPException(status_code=404, detail="Settings profile not found")
    return profile


@router.put("/{printer_id}/settings-profiles/{profile_id}", response_model=SettingsProfileRecord)
def update_settings_profile(
    printer_id: str,
    profile_id: str,
    body: SettingsProfileUpdateRequest,
    current: User = Depends(require_user),
) -> SettingsProfileRecord:
    """Covers both a plain rename and "update mode" (overwrite the saved
    settings with whatever's currently dialed in) -- same request shape,
    the frontend just chooses which fields to include."""
    _get_owned_settings_profile(printer_id, profile_id, current)
    updated = store.update_settings_profile(profile_id, **body.model_dump(exclude_unset=True))
    assert updated is not None  # just confirmed the profile exists above
    return updated


@router.post("/{printer_id}/settings-profiles/{profile_id}/duplicate", response_model=SettingsProfileRecord)
def duplicate_settings_profile(
    printer_id: str, profile_id: str, current: User = Depends(require_user)
) -> SettingsProfileRecord:
    _get_owned_settings_profile(printer_id, profile_id, current)
    duplicated = store.duplicate_settings_profile(profile_id, user_id=current.id)
    assert duplicated is not None  # just confirmed the profile exists above
    return duplicated


@router.delete("/{printer_id}/settings-profiles/{profile_id}")
def delete_settings_profile(
    printer_id: str, profile_id: str, current: User = Depends(require_user)
) -> dict[str, bool]:
    _get_owned_settings_profile(printer_id, profile_id, current)
    store.delete_settings_profile(profile_id)
    return {"ok": True}


@router.post("/{printer_id}/test-connection")
async def test_printer_connection(
    printer_id: str, current: User = Depends(require_user)
) -> dict[str, str]:
    """Cheap read-only ping against the printer's *stored* connection
    details -- edit-and-save first if you want to test a credential you
    just typed in."""
    _get_owned_printer(printer_id, current)
    row = store.get_printer_row(printer_id)
    assert row is not None  # just confirmed ownership above
    try:
        message = await printhost.test_connection(row)
    except printhost.PrintHostError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"message": message}


@router.post("/{printer_id}/send/{job_id}")
async def send_to_printer(
    printer_id: str,
    job_id: str,
    body: SendToPrinterRequest,
    current: User = Depends(require_user),
) -> dict[str, bool]:
    _get_owned_printer(printer_id, current)
    job = job_store.get(job_id)
    if job is None or job.user_id != current.id:
        raise HTTPException(status_code=404, detail="Job not found")
    gcode_path = resolve_job_gcode_path(job_id)

    row = store.get_printer_row(printer_id)
    assert row is not None  # just confirmed ownership above
    try:
        await printhost.send_gcode(row, gcode_path, body.start_print)
    except printhost.PrintHostError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True}
