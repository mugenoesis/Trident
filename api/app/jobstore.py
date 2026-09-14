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
    user_id TEXT NOT NULL DEFAULT 'local',
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
            # Migration for DBs created before user_id existed: CREATE TABLE
            # IF NOT EXISTS above is a no-op against an existing table, so
            # the column has to be added explicitly. New rows on a fresh
            # table already get it from the CREATE TABLE's DEFAULT.
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
            if "user_id" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN user_id TEXT NOT NULL DEFAULT 'local'")

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
        user_id: str,
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
                    id, user_id, status, model_id, printer_profile, process_profile,
                    filament_profiles, setting_overrides, created_at, updated_at,
                    progress, result, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)""",
                (
                    job_id,
                    user_id,
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

    def list(self, user_id: str) -> list[JobRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def list_all(self) -> list[JobRecord]:
        """Every job regardless of owner -- used by the cleanup sweep,
        which operates system-wide, not on behalf of a particular user."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
        return [self._row_to_record(r) for r in rows]

    def delete(self, job_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    def reassign_all_to_user(self, user_id: str) -> None:
        """Used by switch-to-single: merges every job, regardless of
        current owner, onto one account."""
        with self._connect() as conn:
            conn.execute("UPDATE jobs SET user_id = ?", (user_id,))

    def reset_for_tests(self) -> None:
        """Wipe all jobs -- see UserStore.reset_for_tests() for why this is
        needed (a process-wide singleton would otherwise leak jobs between
        tests in the same pytest session)."""
        with self._connect() as conn:
            conn.execute("DELETE FROM jobs")

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
            user_id=row["user_id"],
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
