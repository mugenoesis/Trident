from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import resin as resin_module
from ..auth import require_user
from ..resin_printers_user import build_preset, user_resin_printers
from ..resin_user import user_resins
from ..schemas import MyResinPrinterRequest, MyResinRequest, ResinChoice, ResinFormat, ResinInfo, ResinPrinterInfo
from ..userstore import User

router = APIRouter(prefix="/resin", tags=["resin"])


@router.get("/printers", response_model=list[ResinPrinterInfo])
def list_resin_printers(current: User = Depends(require_user)) -> list[ResinPrinterInfo]:
    return [ResinPrinterInfo(**p) for p in resin_module.catalog.printers(current.id)]


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
    printer_info = resin_module.catalog.get_printer(printer, current.id)
    if printer_info is None:
        raise HTTPException(status_code=404, detail="Unknown resin printer")
    names = resin_module.catalog.settings_names(printer_info["name"], current.id)
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
    printer = resin_module.catalog.get_printer(body.printer, current.id)
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


@router.get("/formats", response_model=list[ResinFormat])
def list_formats(current: User = Depends(require_user)) -> list[ResinFormat]:
    """The printer file formats the slicer can write, for making a printer of your own."""
    return [
        ResinFormat(id=f, extension=ext, label=resin_module.format_label(f))
        for f, ext in sorted(resin_module.catalog.formats().items(), key=lambda kv: resin_module.format_label(kv[0]))
    ]


# The pixel of a resin screen is some 20 to 100 micrometres; a screen whose numbers give a pixel far outside that, or one that is not
# square, has a number wrong somewhere (and a printer refuses a file whose size does not match its screen).
_PIXEL_MM = (0.005, 0.5)
_SQUARE_WITHIN = 0.02


def _check_my_printer(body: MyResinPrinterRequest, current: User, *, replacing: str | None) -> dict[str, Any] | None:
    """Refuse a printer that cannot work; the preset to copy from, if any."""
    taken = resin_module.catalog.is_built_in_printer(body.name) or (
        body.name != replacing and user_resin_printers.exists(current.id, body.name)
    )
    if taken:
        raise HTTPException(
            status_code=409, detail=f"A printer called {body.name!r} already exists; choose another name"
        )
    if body.format not in resin_module.catalog.formats():
        raise HTTPException(status_code=400, detail=f"The slicer cannot write {body.format!r} files")
    pitch_x, pitch_y = body.display_width_mm / body.pixels_x, body.display_height_mm / body.pixels_y
    if not _PIXEL_MM[0] <= min(pitch_x, pitch_y) <= max(pitch_x, pitch_y) <= _PIXEL_MM[1]:
        raise HTTPException(
            status_code=400,
            detail=f"These numbers give pixels of {pitch_x:.4f} x {pitch_y:.4f} mm, which no resin screen has: check them",
        )
    if not body.rectangular_pixels and abs(pitch_x / pitch_y - 1) > _SQUARE_WITHIN:
        raise HTTPException(
            status_code=400,
            detail=(
                f"These numbers give pixels of {pitch_x:.4f} x {pitch_y:.4f} mm, which are not square: check the screen size and the pixel "
                "counts (a printer rejects a file that does not match its screen), or say the pixels are rectangular"
            ),
        )
    if body.copy_from is None:
        return None
    base = resin_module.catalog.printer_preset(body.copy_from, current.id)
    if base is None:
        raise HTTPException(status_code=400, detail=f"Unknown resin printer: {body.copy_from!r}")
    return base


def _save_my_printer(body: MyResinPrinterRequest, current: User, *, replacing: str | None) -> ResinPrinterInfo:
    base = _check_my_printer(body, current, replacing=replacing)
    form = body.model_dump()
    user_resin_printers.save(current.id, body.name, build_preset(form, base), form)
    mine = next(p for p in resin_module.catalog.printers(current.id) if p["name"] == body.name)
    return ResinPrinterInfo(**mine)


@router.post("/my-printers", response_model=ResinPrinterInfo)
def make_my_printer(body: MyResinPrinterRequest, current: User = Depends(require_user)) -> ResinPrinterInfo:
    return _save_my_printer(body, current, replacing=None)


@router.get("/my-printers/{name}", response_model=MyResinPrinterRequest)
def read_my_printer(name: str, current: User = Depends(require_user)) -> MyResinPrinterRequest:
    form = user_resin_printers.form(current.id, name)
    if form is None:
        raise HTTPException(status_code=404, detail="Not one of your printers")
    return MyResinPrinterRequest(**form)


@router.put("/my-printers/{name}", response_model=ResinPrinterInfo)
def change_my_printer(
    name: str, body: MyResinPrinterRequest, current: User = Depends(require_user)
) -> ResinPrinterInfo:
    """Replace the values of one of your printers (its name stays)."""
    if not user_resin_printers.exists(current.id, name):
        raise HTTPException(status_code=404, detail="Not one of your printers")
    return _save_my_printer(body.model_copy(update={"name": name}), current, replacing=name)


@router.delete("/my-printers/{name}")
def delete_my_printer(name: str, current: User = Depends(require_user)) -> dict[str, bool]:
    if not user_resin_printers.delete(current.id, name):
        raise HTTPException(status_code=404, detail="Not one of your printers")
    return {"ok": True}
