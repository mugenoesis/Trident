"""SQLite-backed saved printers + per-printer material profiles.

Mirrors jobstore.py/userstore.py's style: raw sqlite3, one connection per
call, WAL. Connection secrets (printhost_apikey/printhost_user/
printhost_password) are stored as given -- they need to be replayed to the
printer's own API (send-to-printer), so there's nothing to hash -- but
never leave via PrinterRecord; callers only ever see has_credentials.
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
from .schemas import MaterialProfileRecord, PrinterRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS printers (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    vendor TEXT NOT NULL,
    machine_profile TEXT NOT NULL,
    process_profile TEXT NOT NULL,
    filament_profile TEXT NOT NULL,
    bed_width REAL,
    bed_depth REAL,
    bed_height REAL,
    host_type TEXT,
    print_host TEXT,
    printhost_apikey TEXT,
    printhost_user TEXT,
    printhost_password TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS material_profiles (
    id TEXT PRIMARY KEY,
    printer_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    quick_settings TEXT NOT NULL,
    advanced_overrides TEXT NOT NULL,
    process_profile TEXT,
    filament_profile TEXT,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PrinterStore:
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

    # -- printers ---------------------------------------------------------

    def create_printer(self, *, user_id: str, **fields: Any) -> PrinterRecord:
        printer_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO printers (
                    id, user_id, name, vendor, machine_profile, process_profile,
                    filament_profile, bed_width, bed_depth, bed_height, host_type,
                    print_host, printhost_apikey, printhost_user, printhost_password,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    printer_id,
                    user_id,
                    fields["name"],
                    fields["vendor"],
                    fields["machine_profile"],
                    fields["process_profile"],
                    fields["filament_profile"],
                    fields.get("bed_width"),
                    fields.get("bed_depth"),
                    fields.get("bed_height"),
                    fields.get("host_type"),
                    fields.get("print_host"),
                    fields.get("printhost_apikey"),
                    fields.get("printhost_user"),
                    fields.get("printhost_password"),
                    now,
                ),
            )
        return self.get_printer(printer_id)  # type: ignore[return-value]

    def list_printers(self, user_id: str) -> list[PrinterRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM printers WHERE user_id = ? ORDER BY created_at", (user_id,)
            ).fetchall()
        return [self._row_to_printer(r) for r in rows]

    def get_printer(self, printer_id: str) -> PrinterRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM printers WHERE id = ?", (printer_id,)).fetchone()
        return self._row_to_printer(row) if row else None

    # Columns a settings edit is allowed to touch -- deliberately excludes
    # vendor/machine_profile/process_profile/filament_profile/bed_* (a
    # printer's slicing identity): fixing one of those is delete-and-recreate,
    # same reasoning as skipping edit entirely in the first pass. This is
    # just for the connection details (+ name) added after the fact.
    _UPDATABLE_COLUMNS = frozenset(
        {"name", "host_type", "print_host", "printhost_apikey", "printhost_user", "printhost_password"}
    )

    def update_printer(self, printer_id: str, **fields: Any) -> PrinterRecord | None:
        updates = {k: v for k, v in fields.items() if k in self._UPDATABLE_COLUMNS}
        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            with self._connect() as conn:
                conn.execute(
                    f"UPDATE printers SET {set_clause} WHERE id = ?",  # noqa: S608 - keys are our own frozenset, not user input
                    (*updates.values(), printer_id),
                )
        return self.get_printer(printer_id)

    def get_printer_row(self, printer_id: str) -> sqlite3.Row | None:
        """Raw row, secrets included -- for printhost.py's actual upload,
        which needs the real apikey/password, not the masked PrinterRecord
        that never leaves this module otherwise."""
        with self._connect() as conn:
            return conn.execute("SELECT * FROM printers WHERE id = ?", (printer_id,)).fetchone()

    def get_owner(self, printer_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT user_id FROM printers WHERE id = ?", (printer_id,)).fetchone()
        return row["user_id"] if row else None

    def reset_for_tests(self) -> None:
        """Wipe all printers/materials -- see UserStore.reset_for_tests()
        for why this is needed (a process-wide singleton would otherwise
        leak state between tests in the same pytest session)."""
        with self._connect() as conn:
            conn.execute("DELETE FROM material_profiles")
            conn.execute("DELETE FROM printers")

    def reassign_all_to_user(self, user_id: str) -> None:
        """Used by switch-to-single: merges every printer + material
        profile, regardless of current owner, onto one account."""
        with self._connect() as conn:
            conn.execute("UPDATE printers SET user_id = ?", (user_id,))
            conn.execute("UPDATE material_profiles SET user_id = ?", (user_id,))

    def delete_printer(self, printer_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM material_profiles WHERE printer_id = ?", (printer_id,))
            conn.execute("DELETE FROM printers WHERE id = ?", (printer_id,))

    @staticmethod
    def _row_to_printer(row: sqlite3.Row) -> PrinterRecord:
        return PrinterRecord(
            id=row["id"],
            name=row["name"],
            vendor=row["vendor"],
            machine_profile=row["machine_profile"],
            process_profile=row["process_profile"],
            filament_profile=row["filament_profile"],
            bed_width=row["bed_width"],
            bed_depth=row["bed_depth"],
            bed_height=row["bed_height"],
            host_type=row["host_type"],
            print_host=row["print_host"],
            has_credentials=bool(
                row["printhost_apikey"] or row["printhost_user"] or row["printhost_password"]
            ),
            created_at=row["created_at"],
        )

    # -- material profiles ------------------------------------------------

    def create_material(
        self,
        *,
        printer_id: str,
        user_id: str,
        name: str,
        quick_settings: dict[str, str],
        advanced_overrides: dict[str, str],
        process_profile: str | None,
        filament_profile: str | None,
    ) -> MaterialProfileRecord:
        material_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO material_profiles (
                    id, printer_id, user_id, name, quick_settings, advanced_overrides,
                    process_profile, filament_profile, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    material_id,
                    printer_id,
                    user_id,
                    name,
                    json.dumps(quick_settings),
                    json.dumps(advanced_overrides),
                    process_profile,
                    filament_profile,
                    now,
                ),
            )
        return self.get_material(material_id)  # type: ignore[return-value]

    def list_materials(self, printer_id: str) -> list[MaterialProfileRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM material_profiles WHERE printer_id = ? ORDER BY created_at",
                (printer_id,),
            ).fetchall()
        return [self._row_to_material(r) for r in rows]

    def get_material(self, material_id: str) -> MaterialProfileRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM material_profiles WHERE id = ?", (material_id,)
            ).fetchone()
        return self._row_to_material(row) if row else None

    def delete_material(self, material_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM material_profiles WHERE id = ?", (material_id,))

    @staticmethod
    def _row_to_material(row: sqlite3.Row) -> MaterialProfileRecord:
        return MaterialProfileRecord(
            id=row["id"],
            printer_id=row["printer_id"],
            name=row["name"],
            quick_settings=json.loads(row["quick_settings"]),
            advanced_overrides=json.loads(row["advanced_overrides"]),
            process_profile=row["process_profile"],
            filament_profile=row["filament_profile"],
            created_at=row["created_at"],
        )


store = PrinterStore(settings.printers_db_path)
