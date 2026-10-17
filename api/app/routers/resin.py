from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import resin as resin_module
from ..auth import require_user
from ..schemas import ResinChoice, ResinInfo, ResinPrinterInfo
from ..userstore import User

router = APIRouter(prefix="/resin", tags=["resin"])


@router.get("/printers", response_model=list[ResinPrinterInfo])
def list_resin_printers(current: User = Depends(require_user)) -> list[ResinPrinterInfo]:
    return [ResinPrinterInfo(**p) for p in resin_module.catalog.printers()]


@router.get("/resins", response_model=list[ResinInfo])
def list_resins(current: User = Depends(require_user)) -> list[ResinInfo]:
    return [ResinInfo(**r) for r in resin_module.catalog.resins()]


@router.get("/choice", response_model=ResinChoice)
def resin_choice(
    resin: str = Query(...),
    printer: str = Query(...),
    layer_height: float = Query(..., gt=0, le=1),
    current: User = Depends(require_user),
) -> ResinChoice:
    """The row of `resin` the slicer picks for `printer` at `layer_height`."""
    material = resin_module.catalog.get_resin(resin)
    if material is None:
        raise HTTPException(status_code=404, detail="Unknown resin")
    printer_info = resin_module.catalog.get_printer(printer)
    if printer_info is None:
        raise HTTPException(status_code=404, detail="Unknown resin printer")
    names = [printer_info["name"], printer_info["model"]]
    row = resin_module.choose_row(material, names, layer_height)
    if row is None:
        raise HTTPException(status_code=404, detail=f"{resin} has no settings for {printer}")
    return ResinChoice(
        resin=resin,
        printer=printer,
        layer_height=float(row["layer_height"]),
        match=resin_module.match_kind(row, names),
        exact_layer_height=abs(float(row["layer_height"]) - layer_height) < 0.0005,
        settings={k: row[k] for k in resin_module.ROW_KEYS if k in row},
        source=str(row.get("source", "")),
        retrieved=str(row.get("retrieved", "")),
        notes=str(row.get("notes", "")),
    )
