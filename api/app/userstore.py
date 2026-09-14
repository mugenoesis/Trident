"""SQLite-backed user accounts + app-wide auth-mode config.

Mirrors jobstore.py's style: raw sqlite3, one connection per call
(_connect()), WAL mode, one file per store. Two auth modes, tracked in the
app_config table:
  - "unset" (fresh install) / "single": there is exactly one implicit user,
    LOCAL_USER_ID, with no username/password -- nothing to log into.
  - "multi": real accounts with a username + password_hash, gated by a
    session cookie (see auth.py).
Switching single -> multi (auth.py's switch_to_multi) sets credentials
directly on the existing LOCAL_USER_ID row rather than migrating data to a
new id, since that row already owns everything created so far.
"""
from __future__ import annotations

import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .config import settings

LOCAL_USER_ID = "local"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE,
    password_hash TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class User:
    id: str
    username: str | None


class UserStore:
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

    # -- app-wide config (auth mode, session-signing secret) ----------------

    def _get_config(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM app_config WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def _set_config(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO app_config (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get_auth_mode(self) -> str:
        return self._get_config("auth_mode") or "unset"

    def set_auth_mode(self, mode: str) -> None:
        self._set_config("auth_mode", mode)

    def get_secret_key(self) -> str:
        # Generated once, persisted -- must survive restarts or every
        # redeploy would silently invalidate every session cookie.
        key = self._get_config("secret_key")
        if key is None:
            key = secrets.token_hex(32)
            self._set_config("secret_key", key)
        return key

    # -- users ----------------------------------------------------------

    def get_or_create_local_user(self) -> User:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (id, username, password_hash, created_at) "
                "VALUES (?, NULL, NULL, ?)",
                (LOCAL_USER_ID, _now()),
            )
        return self.get_user(LOCAL_USER_ID)  # type: ignore[return-value]

    def create_user(self, *, username: str, password_hash: str) -> User:
        user_id = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO users (id, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (user_id, username, password_hash, _now()),
            )
        return self.get_user(user_id)  # type: ignore[return-value]

    def set_credentials(self, user_id: str, *, username: str, password_hash: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET username = ?, password_hash = ? WHERE id = ?",
                (username, password_hash, user_id),
            )

    def get_user(self, user_id: str) -> User | None:
        with self._connect() as conn:
            row = conn.execute("SELECT id, username FROM users WHERE id = ?", (user_id,)).fetchone()
        return User(id=row["id"], username=row["username"]) if row else None

    def reset_for_tests(self) -> None:
        """Wipe accounts and auth mode back to a fresh-install state.

        Only meaningful in tests: auth_mode/users are process-wide state on
        this module-level singleton, so without a reset one test switching
        to multi-user mode would otherwise leak into every test that runs
        after it in the same pytest session.
        """
        with self._connect() as conn:
            conn.execute("DELETE FROM users")
            conn.execute("DELETE FROM app_config WHERE key = 'auth_mode'")

    def get_user_by_username(self, username: str) -> tuple[User, str] | None:
        """(User, password_hash) for login verification, or None if the
        username doesn't exist or has no password set yet."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, username, password_hash FROM users WHERE username = ?", (username,)
            ).fetchone()
        if not row or not row["password_hash"]:
            return None
        return User(id=row["id"], username=row["username"]), row["password_hash"]


store = UserStore(settings.users_db_path)
