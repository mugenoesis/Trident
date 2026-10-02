from __future__ import annotations

import math
import shutil
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse

from .. import belt_align, cli_runner, gcode_stats, gcode_thumbnail, threemf_objects
from ..auth import require_user
from ..blocked_settings import blocked_keys
from ..config import settings
from ..jobstore import store
from ..schemas import JobCreateRequest, JobProgress, JobRecord, JobStatus
from ..userstore import User
from .models import (
    delete_model,
    resolve_model_original_name,
    resolve_model_owner,
    resolve_model_path,
    resolve_model_plates,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _job_output_dir(job_id: str) -> Path:
    return settings.output_dir / job_id


def _machine_bed(printer_profile: str, user_id: str | None = None) -> tuple[bool, float]:
    """(is a belt printer, X centre of the bed in mm) for a machine profile."""
    detail = cli_runner._resolve_profile_detail("machine", printer_profile, user_id)
    belt_flag = detail.data.get("belt_printer_infinite_y")
    is_belt = belt_flag in ("1", 1, True)
    xs: list[float] = []
    for point in detail.data.get("printable_area") or []:
        try:
            xs.append(float(str(point).split("x")[0]))
        except ValueError:
            continue
    return is_belt, (min(xs) + max(xs)) / 2 if xs else 0.0


def _machine_bed_area(printer_profile: str, user_id: str | None = None) -> tuple[list[str] | None, float | None]:
    """The printer's printable_area strings and height, as the derived 3mf
    must declare them (see threemf_objects.write_derived_3mf)."""
    data = cli_runner._resolve_profile_detail("machine", printer_profile, user_id).data
    area = data.get("printable_area")
    try:
        height = float(data.get("printable_height"))
    except (TypeError, ValueError):
        height = None
    return ([str(p) for p in area] if isinstance(area, list) and area else None), height


# Per-nozzle settings a file saved for another (multi-nozzle) printer carries.
# If the selected printer's profile does not define them, the file's values
# would leak into the slice (e.g. an X2D's second-nozzle print area makes the
# U1 reject objects near the left edge).
_PRINTER_SPECIFIC_KEYS = ("extruder_printable_area", "extruder_printable_height")


def _leaked_printer_keys(
    model_path: Path, printer_profile: str, user_id: str | None, filament_count: int = 1
) -> set[str]:
    if model_path.suffix.lower() != ".3mf":
        return set()
    drop = threemf_objects.keys_sized_for_fewer_filaments(model_path, filament_count)
    present = threemf_objects.project_keys(model_path, _PRINTER_SPECIFIC_KEYS)
    if present:
        machine = cli_runner._resolve_profile_detail("machine", printer_profile, user_id).data
        drop |= {k for k in present if k not in machine}
    return drop


def _prepare_model(
    job_id: str, model_path: Path, request: JobCreateRequest, user_id: str | None = None
) -> tuple[Path, int | None, bool, bool]:
    """(model to slice, plate to slice, whether the CLI may re-arrange,
    whether it must keep every object exactly where placed).

    A .3mf is sliced with the positions and plates it came with (the slicer
    re-centres a file saved for a different bed itself); run_job retries with
    a forced re-arrange if those positions turn out not to fit. Unchanged
    otherwise unless the user excluded objects, asked for a belt layout,
    copies or a placement, in which case a derived copy of the .3mf is
    written next to the job output (an STL/OBJ/STEP is first converted).
    """
    copies = request.copies
    try:
        is_belt, center_x = _machine_bed(request.printer_profile, user_id)
        drop = _leaked_printer_keys(model_path, request.printer_profile, user_id, len(request.filament_profiles))
    except ValueError:
        # Unknown profile: run_slice reports it; nothing to decide here.
        is_belt, center_x, drop = False, 0.0, set()
    # Belt printers keep the older forced re-arrange (their bed is a narrow strip
    # a foreign file's positions rarely fit).
    keep_file_layout = not is_belt
    if not request.excluded_objects and not request.belt_layout and not request.placement and copies == 1 and not drop:
        return model_path, request.plate_index, not keep_file_layout, False
    out_dir = _job_output_dir(job_id)
    derived = out_dir / "input.3mf"
    excluded = set(request.excluded_objects)
    bed_area, bed_height = _machine_bed_area(request.printer_profile, user_id)
    source = model_path
    if model_path.suffix.lower() != ".3mf":
        source = cli_runner.convert_model(model_path, out_dir / "converted.3mf")
    if is_belt and (request.belt_layout or copies > 1):
        layout = request.belt_layout
        threemf_objects.write_derived_3mf(
            source,
            derived,
            excluded=excluded,
            order=layout.order if layout else [],
            gap_mm=layout.gap_mm if layout else 10.0,
            center_x=center_x,
            copies=copies,
            bed_area=bed_area,
            bed_height=bed_height,
            drop_project_keys=drop,
        )
        # Everything now sits on plate 1, placed explicitly.
        return derived, 1, False, False
    if copies > 1:
        # Copies start stacked; the slicer's own arrange spreads them out.
        threemf_objects.write_derived_3mf(
            source, derived, excluded=excluded, copies=copies, bed_area=bed_area, bed_height=bed_height, drop_project_keys=drop
        )
        return derived, request.plate_index, True, False
    if request.placement:
        threemf_objects.write_derived_3mf(
            source,
            derived,
            excluded=excluded,
            placement=(request.placement.x, request.placement.y),
            bed_area=bed_area,
            bed_height=bed_height,
            drop_project_keys=drop,
        )
        return derived, 1, False, True
    threemf_objects.write_derived_3mf(
        source, derived, excluded=excluded, bed_area=bed_area, bed_height=bed_height, drop_project_keys=drop
    )
    return derived, request.plate_index, not keep_file_layout, False


# A print that starts within this of the purge line is left alone.
_ALIGN_TOLERANCE_MM = 0.3
# Moving the print also changes its support, so the result is measured again
# and refined (up to this many re-slices), to a looser tolerance (the purge
# line itself is 0.4 mm wide).
_ALIGN_PASSES = 3
_ALIGN_REFINE_TOLERANCE_MM = 0.5
_ALIGN_BACKOFF_TRIES = 4
_ALIGN_BACKOFF_STEP_MM = 1.5


def _align_to_purge_line(job_id: str, request: JobCreateRequest, user_id: str | None, slice_args: dict, result):
    """Belt printers: make the very start of the print (support and brim
    included, not just the model) touch the purge line.

    The support is only known once the print is sliced, so this measures the
    first result and, if the start is off, slices again with the default
    placement moved along the belt (up to _ALIGN_PASSES times, each shift
    corrected from the measured response). A re-slice replaces the previous
    result only if it succeeds.
    """
    out_dir = _job_output_dir(job_id)
    try:
        machine = cli_runner._resolve_profile_detail("machine", request.printer_profile, user_id).data
        xs, ys = [], []
        for point in machine.get("printable_area") or []:
            px, _, py = str(point).partition("x")
            xs.append(float(px))
            ys.append(float(py))
        transform = belt_align.parse_belt_transform(
            machine, (max(xs), max(ys), float(machine.get("printable_height", 0)))
        )
        applied = 0.0  # the belt shift the current gcode was sliced with
        history: list[tuple[float, float]] = []  # (shift, where the print started)
        for attempt in range(_ALIGN_PASSES):
            gcodes = sorted(out_dir.glob("plate_*.gcode"))
            if transform is None or not gcodes:
                break
            measured = belt_align.measure_start(gcodes[0], transform)
            if measured is None:
                break
            history.append((applied, measured.start_y))
            error = measured.purge_y - measured.start_y
            if abs(error) <= (_ALIGN_TOLERANCE_MM if attempt == 0 else _ALIGN_REFINE_TOLERANCE_MM):
                break
            # How far the start moves per mm of shift is not 1: moving the
            # model also changes the support grown under it. Learn it from the
            # last two slices (secant method); the first guess is 1.
            slope = 1.0
            if len(history) >= 2:
                (s0, y0), (s1, y1) = history[-2], history[-1]
                if abs(s1 - s0) > 1e-6:
                    slope = min(5.0, max(0.3, (y1 - y0) / (s1 - s0)))
            wanted = applied + error / slope
            store.update_progress(job_id, JobProgress(message="Lining the print up with the purge line…"))
            redo_dir = out_dir / "realigned"
            redo = None
            # The slicer refuses a placement that reaches past the bed's own
            # edge (a model with no support cannot get as close as the support
            # would); back off a little at a time until one is accepted.
            for _ in range(_ALIGN_BACKOFF_TRIES):
                candidate = cli_runner.run_slice(**{**slice_args, "output_dir": redo_dir, "belt_shift_y": wanted, "on_progress": None})
                if candidate.succeeded:
                    redo = candidate
                    applied = wanted
                    break
                shutil.rmtree(redo_dir, ignore_errors=True)
                wanted -= math.copysign(min(_ALIGN_BACKOFF_STEP_MM, abs(wanted - applied)), wanted - applied)
            if redo is None:
                break
            for src in [*redo_dir.glob("plate_*.gcode"), *redo_dir.glob("result.json")]:
                shutil.move(str(src), out_dir / src.name)
            shutil.rmtree(redo_dir, ignore_errors=True)
            result = redo
        return result
    except Exception:  # noqa: BLE001 - alignment is an improvement, never a reason to fail the slice
        return result
    finally:
        shutil.rmtree(out_dir / "realigned", ignore_errors=True)


def _run_job(job_id: str, model_path: Path, request: JobCreateRequest, user_id: str | None = None) -> None:
    store.set_status(job_id, JobStatus.RUNNING)
    try:
        model_path, plate_index, arrange, keep_positions = _prepare_model(job_id, model_path, request, user_id)
        slice_args = dict(
            model_path=model_path,
            output_dir=_job_output_dir(job_id),
            printer_profile=request.printer_profile,
            process_profile=request.process_profile,
            filament_profiles=request.filament_profiles,
            setting_overrides=request.setting_overrides,
            plate_index=plate_index,
            arrange=arrange,
            keep_positions=keep_positions,
            user_id=user_id,
        )
        result = cli_runner.run_slice(**slice_args, on_progress=lambda p: store.update_progress(job_id, p))
        # The file's own layout did not fit this printer's bed: fall back to
        # having the slicer arrange everything (what every 3mf used to get).
        if (
            not result.succeeded
            and not arrange
            and not keep_positions
            and "boundary of the heated bed" in str((result.result_json or {}).get("error_string", ""))
        ):
            shutil.rmtree(_job_output_dir(job_id) / "realigned", ignore_errors=True)
            result = cli_runner.run_slice(**{**slice_args, "arrange": True}, on_progress=lambda p: store.update_progress(job_id, p))
        # An exact position the user chose is never moved.
        if result.succeeded and not keep_positions:
            result = _align_to_purge_line(job_id, request, user_id, slice_args, result)
    except Exception as exc:  # noqa: BLE001 - report to job record, don't crash the worker
        store.finish(job_id, status=JobStatus.FAILED, error=str(exc))
        return

    if result.succeeded:
        if request.preview_image_base64:
            gcode_thumbnail.embed_preview(_job_output_dir(job_id), request.preview_image_base64)
        # OrcaSlicer's own result.json never carries this (see
        # gcode_stats.py) -- folded into the same free-form result blob
        # rather than a new JobRecord/DB column, same as everything else
        # here that's "whatever the slice produced."
        result_json = dict(result.result_json) if result.result_json else {}
        filament_grams = gcode_stats.total_filament_grams_for_job(_job_output_dir(job_id))
        if filament_grams is not None:
            result_json["filament_used_g"] = round(filament_grams, 2)
        store.finish(job_id, status=JobStatus.SUCCEEDED, result=result_json)
    else:
        error = result.result_json.get("error_string") if result.result_json else result.stderr
        store.finish(
            job_id,
            status=JobStatus.FAILED,
            result=result.result_json,
            error=error or f"exit code {result.return_code}",
        )


@router.post("", response_model=JobRecord)
def create_job(
    request: JobCreateRequest, background_tasks: BackgroundTasks, current: User = Depends(require_user)
) -> JobRecord:
    rejected = blocked_keys(request.setting_overrides)
    if rejected:
        raise HTTPException(
            status_code=400,
            detail=f"Settings not overridable via CLI (nocli): {sorted(rejected)}",
        )

    model_path = resolve_model_path(request.model_id)
    # A model with no recorded owner predates per-user ownership and stays
    # accessible (nothing to enforce); one with a *different* owner is a 404,
    # not a 403, so this doesn't confirm the model_id exists to a non-owner.
    owner = resolve_model_owner(request.model_id)
    if owner is not None and owner != current.id:
        raise HTTPException(status_code=404, detail="model_id not found")

    if request.placement and request.belt_layout:
        raise HTTPException(status_code=400, detail="placement and belt_layout cannot be combined")
    # Any other file type is converted to a .3mf before slicing (see
    # _prepare_model), so a belt layout or copies work on it; picking objects
    # does not, because the browser has no object list to pick from.
    if request.excluded_objects or (request.belt_layout and model_path.suffix.lower() == ".3mf"):
        if model_path.suffix.lower() != ".3mf":
            raise HTTPException(status_code=400, detail="Object selection needs a .3mf")
        objects = resolve_model_plates(request.model_id).objects
        known = {o.index for o in objects}
        if not set(request.excluded_objects) <= known:
            raise HTTPException(status_code=400, detail="excluded_objects has an unknown object index")
        kept = [o for o in objects if o.index not in set(request.excluded_objects)]
        if not kept:
            raise HTTPException(status_code=400, detail="Every object is excluded; nothing to print")
        if request.plate_index is not None and not request.belt_layout:
            if not any(o.plate == request.plate_index for o in kept):
                raise HTTPException(status_code=400, detail="Every object on the chosen plate is excluded")

    job = store.create(
        user_id=current.id,
        model_id=request.model_id,
        printer_profile=request.printer_profile,
        process_profile=request.process_profile,
        filament_profiles=request.filament_profiles,
        setting_overrides=request.setting_overrides,
        plate_index=request.plate_index,
    )
    background_tasks.add_task(_run_job, job.id, model_path, request, current.id)
    return job


@router.get("", response_model=list[JobRecord])
def list_jobs(current: User = Depends(require_user)) -> list[JobRecord]:
    return store.list(current.id)


def _get_owned_job(job_id: str, current: User) -> JobRecord:
    job = store.get(job_id)
    if job is None or job.user_id != current.id:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/{job_id}", response_model=JobRecord)
def get_job(job_id: str, current: User = Depends(require_user)) -> JobRecord:
    return _get_owned_job(job_id, current)


def resolve_job_gcode_path(job_id: str) -> Path:
    """The on-disk sliced gcode file for a job -- shared by the download
    route below and the send-to-printer route (routers/printers.py), which
    needs the same file to actually upload it.

    When the job requested a specific plate, OrcaSlicer names its output
    plate_{plate_index}.gcode (confirmed: --slice N and the resulting
    plate_N.gcode share the same 1-based N) -- prefer that exact file so a
    job never returns some other plate's output by glob-order luck. Falls
    through to the glob for every job that didn't request a specific plate
    (including all jobs predating plate_index), or if the specific file
    isn't there yet (still slicing) -- same "not ready yet" 404 as today.
    """
    job = store.get(job_id)
    if job is not None and job.plate_index is not None:
        specific = _job_output_dir(job_id) / f"plate_{job.plate_index}.gcode"
        if specific.is_file():
            return specific
    matches = list(_job_output_dir(job_id).glob("*.gcode"))
    if not matches:
        raise HTTPException(status_code=404, detail="No gcode produced (yet) for this job")
    return matches[0]


@router.get("/{job_id}/gcode")
def get_job_gcode(job_id: str, current: User = Depends(require_user)) -> FileResponse:
    job = _get_owned_job(job_id, current)
    gcode_path = resolve_job_gcode_path(job_id)

    # Name the download after the upload (e.g. "my_model.gcode") rather than
    # OrcaSlicer's generic on-disk "plate_1.gcode", which means nothing once
    # there's more than one job in flight. Falls back to the actual output
    # filename for models uploaded before this metadata existed.
    original_name = resolve_model_original_name(job.model_id)
    download_name = f"{Path(original_name).stem}.gcode" if original_name else gcode_path.name

    # Not text/plain: .gcode isn't a MIME-registered extension, and browsers
    # (confirmed: Chrome on Android) "correct" the download filename to match
    # the Content-Type they were given, appending .txt over the intended
    # .gcode. application/octet-stream is the standard fix -- it doesn't map
    # to any particular extension, so the filename's own .gcode is left alone.
    return FileResponse(
        gcode_path, media_type="application/octet-stream", filename=download_name
    )


@router.delete("/{job_id}")
def delete_job(job_id: str, current: User = Depends(require_user)) -> dict[str, bool]:
    """"I'm finished with this" -- deletes the job's output (gcode/thumbnail)
    immediately, and the uploaded model too if no other job still points at
    it. Complements the automatic retention sweep (cleanup.py) for anyone
    who wants files gone right away instead of waiting out the retention
    window."""
    job = _get_owned_job(job_id, current)
    shutil.rmtree(_job_output_dir(job_id), ignore_errors=True)
    store.delete(job_id)
    still_referenced = any(j.model_id == job.model_id for j in store.list_all())
    if not still_referenced:
        delete_model(job.model_id)
    return {"ok": True}
