"""SQLite-backed job store.

Single-user scale (docs/ARCHITECTURE.md decision #1): no Redis/Celery,
just FastAPI BackgroundTasks + this store, so job state survives API
restarts. One connection per call, WAL mode for concurrent readers
while a background task is writing progress.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import settings
from .schemas import JobProgress, JobRecord, JobStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    model_id TEXT NOT NULL,
    printer_profile TEXT NOT NULL,
    process_profile TEXT NOT NULL,
    filament_profiles TEXT NOT NULL,
    setting_overrides TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    progress TEXT,
    result TEXT,
    error TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def create(
        self,
        *,
        model_id: str,
        printer_profile: str,
        process_profile: str,
        filament_profiles: list[str],
        setting_overrides: dict[str, Any],
    ) -> JobRecord:
        job_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO jobs (
                    id, status, model_id, printer_profile, process_profile,
                    filament_profiles, setting_overrides, created_at, updated_at,
                    progress, result, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)""",
                (
                    job_id,
                    JobStatus.QUEUED.value,
                    model_id,
                    printer_profile,
                    process_profile,
                    json.dumps(filament_profiles),
                    json.dumps(setting_overrides),
                    now,
                    now,
                ),
            )
        return self.get(job_id)  # type: ignore[return-value]

    def get(self, job_id: str) -> JobRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_record(row) if row else None

    def list(self) -> list[JobRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
        return [self._row_to_record(r) for r in rows]

    def set_status(self, job_id: str, status: JobStatus) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, _now(), job_id),
            )

    def update_progress(self, job_id: str, progress: JobProgress) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET progress = ?, updated_at = ? WHERE id = ?",
                (progress.model_dump_json(), _now(), job_id),
            )

    def finish(
        self,
        job_id: str,
        *,
        status: JobStatus,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """UPDATE jobs SET status = ?, result = ?, error = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    status.value,
                    json.dumps(result) if result is not None else None,
                    error,
                    _now(),
                    job_id,
                ),
            )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> JobRecord:
        progress_raw = row["progress"]
        return JobRecord(
            id=row["id"],
            status=JobStatus(row["status"]),
            model_id=row["model_id"],
            printer_profile=row["printer_profile"],
            process_profile=row["process_profile"],
            filament_profiles=json.loads(row["filament_profiles"]),
            setting_overrides=json.loads(row["setting_overrides"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            progress=JobProgress.model_validate_json(progress_raw) if progress_raw else None,
            result=json.loads(row["result"]) if row["result"] else None,
            error=row["error"],
        )


store = JobStore(settings.jobstore_path)
