from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import resin as resin_module
from ..auth import require_user
from ..resin_user import user_resins
from ..schemas import MyResinRequest, ResinChoice, ResinInfo, ResinPrinterInfo
from ..userstore import User

router = APIRouter(prefix="/resin", tags=["resin"])


@router.get("/printers", response_model=list[ResinPrinterInfo])
def list_resin_printers(current: User = Depends(require_user)) -> list[ResinPrinterInfo]:
    return [ResinPrinterInfo(**p) for p in resin_module.catalog.printers()]


@router.get("/resins", response_model=list[ResinInfo])
def list_resins(current: User = Depends(require_user)) -> list[ResinInfo]:
    return [ResinInfo(**r) for r in resin_module.catalog.resins(current.id)]


@router.get("/choice", response_model=ResinChoice)
def resin_choice(
    resin: str = Query(...),
    printer: str = Query(...),
    layer_height: float = Query(..., gt=0, le=1),
    current: User = Depends(require_user),
) -> ResinChoice:
    """The row of `resin` the slicer picks for `printer` at `layer_height`."""
    material = resin_module.catalog.get_resin(resin, current.id)
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


@router.post("/my-resins", response_model=ResinInfo)
def save_my_resin(body: MyResinRequest, current: User = Depends(require_user)) -> ResinInfo:
    """Save the values as the user's own resin; under a name already theirs, the row for this printer and layer height is added or replaced."""
    if resin_module.catalog.is_built_in(body.name):
        raise HTTPException(status_code=409, detail=f"{body.name!r} is a built-in resin; choose another name")
    printer = resin_module.catalog.get_printer(body.printer)
    if printer is None:
        raise HTTPException(status_code=400, detail=f"Unknown resin printer: {body.printer!r}")
    unknown = sorted(set(body.settings) - set(resin_module.ROW_KEYS))
    if unknown:
        raise HTTPException(status_code=400, detail=f"Not a resin value: {unknown}")
    based_on = None
    if body.based_on:
        based_on = resin_module.catalog.get_resin(body.based_on, current.id)
        if based_on is None:
            raise HTTPException(status_code=400, detail=f"Unknown resin: {body.based_on!r}")
    return ResinInfo(
        **user_resins.save(current.id, body.name, printer["name"], body.layer_height, body.settings, based_on)
    )


@router.delete("/my-resins/{name}")
def delete_my_resin(name: str, current: User = Depends(require_user)) -> dict[str, bool]:
    if not user_resins.delete(current.id, name):
        raise HTTPException(status_code=404, detail="Not one of your resins")
    return {"ok": True}
