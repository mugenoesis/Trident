from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response

from .. import bambu_link, bambu_status, klipper_import, klipper_status, printhost
from .. import resin as resin_module
from ..auth import require_user
from ..jobstore import store as job_store
from ..printerstore import store
from ..schemas import (
    KlipperImportRequest,
    KlipperImportResult,
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
    if body.technology == "resin":
        try:
            resin_module.check_printer_and_resins(body.machine_profile, body.filament_profiles, current.id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return store.create_printer(user_id=current.id, **body.model_dump())


@router.post("/test-connection")
async def test_connection_ad_hoc(body: TestConnectionRequest, current: User = Depends(require_user)) -> dict[str, str]:
    """Validates connection fields before a printer is even saved (the
    create-printer form's Test connection button) -- for an already-saved
    printer, POST /printers/{id}/test-connection uses its stored
    credentials instead."""
    try:
        if body.host_type == "bambu":
            message = await bambu_link.check_connection(body.print_host, body.device_id, body.printhost_apikey)
        else:
            message = await printhost.test_connection(body.model_dump())
    except (printhost.PrintHostError, bambu_link.BambuError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"message": message}


@router.post("/klipper-import", response_model=KlipperImportResult)
async def import_from_klipper_printer(
    body: KlipperImportRequest, current: User = Depends(require_user)
) -> dict[str, Any]:
    """Reads a Klipper printer's own config through Moonraker (read-only) and answers the New printer form it makes, with where
    each value was read and what to check. Nothing is saved and nothing on the printer is changed."""
    try:
        snapshot = await printhost.read_klipper({**body.model_dump(), "host_type": "moonraker"})
    except printhost.PrintHostError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    try:
        return klipper_import.import_from_klipper(snapshot["info"], snapshot["settings"], snapshot["objects"])
    except klipper_import.KlipperImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _live_row(printer_id: str, current: User):
    """The stored connection of one of the user's own printers that has a live page: a Klipper (Moonraker) printer, or a Bambu one in LAN mode."""
    _get_owned_printer(printer_id, current)
    row = store.get_printer_row(printer_id)
    assert row is not None  # just confirmed ownership above
    if row["host_type"] == "bambu":
        if not (row["print_host"] and row["device_id"] and row["printhost_apikey"]):
            raise HTTPException(
                status_code=400, detail="This Bambu printer needs its IP address, serial number and access code saved"
            )
        return row
    if row["host_type"] != "moonraker" or not row["print_host"]:
        raise HTTPException(status_code=400, detail="This printer has no Klipper (Moonraker) or Bambu connection saved")
    return row


@router.get("/{printer_id}/status")
async def printer_status(printer_id: str, current: User = Depends(require_user)) -> dict[str, Any]:
    """The live state of a Klipper or Bambu printer: the print, its progress, the temperatures and what can be done to it. Read-only."""
    row = _live_row(printer_id, current)
    try:
        if row["host_type"] == "bambu":
            return bambu_status.status_from_bambu(await bambu_link.read_report(row), row["device_id"])
        return klipper_status.status_from_klipper(await printhost.read_status(row))
    except (printhost.PrintHostError, bambu_link.BambuError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{printer_id}/print/{action}")
async def control_print(
    printer_id: str, action: Literal["pause", "resume", "cancel"], current: User = Depends(require_user)
) -> dict[str, bool]:
    """Pause, resume or cancel the print on a Klipper or Bambu printer. Nothing else can be asked of it through here."""
    row = _live_row(printer_id, current)
    try:
        if row["host_type"] == "bambu":
            await bambu_link.control(row, action)
        else:
            await printhost.print_control(row, action)
    except (printhost.PrintHostError, bambu_link.BambuError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/{printer_id}/webcams")
async def printer_webcams(printer_id: str, current: User = Depends(require_user)) -> list[dict[str, Any]]:
    """The webcams of a Klipper printer, by name (their addresses stay here: a picture is fetched through the snapshot route)."""
    row = _live_row(printer_id, current)
    if row["host_type"] == "bambu":
        return []  # its camera is not supported yet
    try:
        cameras = await printhost.webcam_list(row)
    except printhost.PrintHostError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [{"index": i, "name": cam["name"]} for i, cam in enumerate(cameras)]


@router.get("/{printer_id}/webcams/{index}/snapshot")
async def printer_webcam_snapshot(printer_id: str, index: int, current: User = Depends(require_user)) -> Response:
    """One picture from a webcam of a Klipper printer (fetched here, so the printer's address and key stay on the server)."""
    row = _live_row(printer_id, current)
    if row["host_type"] == "bambu":
        raise HTTPException(status_code=404, detail="A Bambu printer's camera is not supported yet")
    try:
        data, kind = await printhost.webcam_snapshot(row, index)
    except printhost.NoSuchCamera as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except printhost.PrintHostError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=data, media_type=kind, headers={"Cache-Control": "no-store"})


@router.put("/{printer_id}", response_model=PrinterRecord)
def update_printer(printer_id: str, body: PrinterUpdateRequest, current: User = Depends(require_user)) -> PrinterRecord:
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
def delete_material(printer_id: str, material_id: str, current: User = Depends(require_user)) -> dict[str, bool]:
    _get_owned_material(printer_id, material_id, current)
    store.delete_material(material_id)
    return {"ok": True}


@router.get("/{printer_id}/settings-profiles", response_model=list[SettingsProfileRecord])
def list_settings_profiles(printer_id: str, current: User = Depends(require_user)) -> list[SettingsProfileRecord]:
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
def delete_settings_profile(printer_id: str, profile_id: str, current: User = Depends(require_user)) -> dict[str, bool]:
    _get_owned_settings_profile(printer_id, profile_id, current)
    store.delete_settings_profile(profile_id)
    return {"ok": True}


@router.post("/{printer_id}/test-connection")
async def test_printer_connection(printer_id: str, current: User = Depends(require_user)) -> dict[str, str]:
    """Cheap read-only ping against the printer's *stored* connection
    details -- edit-and-save first if you want to test a credential you
    just typed in."""
    _get_owned_printer(printer_id, current)
    row = store.get_printer_row(printer_id)
    assert row is not None  # just confirmed ownership above
    try:
        if row["host_type"] == "bambu":
            message = await bambu_link.check_connection(row["print_host"], row["device_id"], row["printhost_apikey"])
        else:
            message = await printhost.test_connection(row)
    except (printhost.PrintHostError, bambu_link.BambuError) as exc:
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
