"""Background sweep that deletes stale job output and uploaded models.

The explicit `DELETE /jobs/{id}` route (routers/jobs.py) covers "I'm
finished with this, remove it now"; this covers everything else, so
uploads/gcode don't accumulate on disk forever if nobody clicks that.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import datetime, timedelta, timezone

from .config import settings
from .jobstore import store
from .routers.models import delete_model, resolve_model_uploaded_at
from .schemas import JobStatus

logger = logging.getLogger(__name__)

_TERMINAL = {JobStatus.SUCCEEDED, JobStatus.FAILED}


def run_cleanup_once() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.retention_hours)

    # A model stays if *any* job (active, or terminal but not yet expired)
    # still references it -- only computed once all jobs have been visited,
    # so it doesn't matter which order jobs are processed in.
    surviving_model_ids: set[str] = set()
    for job in store.list_all():
        created = datetime.fromisoformat(job.created_at)
        if job.status in _TERMINAL and created < cutoff:
            shutil.rmtree(settings.output_dir / job.id, ignore_errors=True)
            store.delete(job.id)
        else:
            surviving_model_ids.add(job.model_id)

    if not settings.models_dir.is_dir():
        return
    for model_file in settings.models_dir.iterdir():
        if not model_file.is_file():
            continue  # skips the .meta/ sidecar directory
        model_id = model_file.stem
        if model_id in surviving_model_ids:
            continue
        uploaded_at = resolve_model_uploaded_at(model_id)
        if uploaded_at is None or uploaded_at.astimezone(timezone.utc) < cutoff:
            delete_model(model_id)


async def run_cleanup_loop() -> None:
    while True:
        try:
            run_cleanup_once()
        except Exception:  # noqa: BLE001 - a bad sweep shouldn't kill the loop
            logger.exception("Cleanup sweep failed")
        await asyncio.sleep(settings.cleanup_interval_minutes * 60)
