from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import printhost
from ..auth import require_user
from ..jobstore import store as job_store
from ..printerstore import store
from ..schemas import (
    MaterialProfileCreateRequest,
    MaterialProfileRecord,
    PrinterCreateRequest,
    PrinterRecord,
    SendToPrinterRequest,
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


@router.delete("/{printer_id}/materials/{material_id}")
def delete_material(
    printer_id: str, material_id: str, current: User = Depends(require_user)
) -> dict[str, bool]:
    _get_owned_printer(printer_id, current)
    material = store.get_material(material_id)
    if material is None or material.printer_id != printer_id:
        raise HTTPException(status_code=404, detail="Material profile not found")
    store.delete_material(material_id)
    return {"ok": True}


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
