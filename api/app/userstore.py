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

import hashlib
import secrets
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import settings

LOCAL_USER_ID = "local"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE,
    password_hash TEXT,
    last_printer_id TEXT,
    last_material_id TEXT,
    last_settings_profile_id TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- Keys another program uses instead of a login (see auth.py). Only the SHA-256 of the secret is kept.
CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    scope TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    last_used_at TEXT
);
"""

# Columns added after the initial release -- CREATE TABLE IF NOT EXISTS is a
# no-op against an already-existing table, so these need an explicit
# migration for DBs created before they existed (same pattern as
# jobstore.py's user_id column).
_MIGRATED_COLUMNS = ("last_printer_id", "last_material_id", "last_settings_profile_id")


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class User:
    id: str
    username: str | None
    last_printer_id: str | None = None
    last_material_id: str | None = None
    last_settings_profile_id: str | None = None


@dataclass(frozen=True)
class ApiKey:
    id: str
    user_id: str
    name: str
    scope: str  # "upload" (may only upload a model), "hollow" (may upload and hollow a model) or "full" (every API except managing keys)
    created_at: str
    last_used_at: str | None = None


API_KEY_PREFIX = "trident_"


def _hash_secret(secret: str) -> str:
    # The secret is 32 random bytes, so an unsalted fast hash is enough: there is nothing to guess.
    return hashlib.sha256(secret.encode()).hexdigest()


class UserStore:
    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
            for column in _MIGRATED_COLUMNS:
                if column not in columns:
                    conn.execute(f"ALTER TABLE users ADD COLUMN {column} TEXT")

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
                "INSERT OR IGNORE INTO users (id, username, password_hash, created_at) " "VALUES (?, NULL, NULL, ?)",
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
            row = conn.execute(
                "SELECT id, username, last_printer_id, last_material_id, last_settings_profile_id "
                "FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return self._row_to_user(row) if row else None

    def set_last_selection(
        self,
        user_id: str,
        *,
        printer_id: str | None,
        material_id: str | None,
        settings_profile_id: str | None,
    ) -> None:
        """Remembers the printer/material/settings profile last selected, so
        they come back as the default next time this user opens the site --
        always set together (a full replace), since the frontend re-sends
        all three fields together on every selection change, and
        material_id/settings_profile_id without their owning printer_id
        would be meaningless to restore."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET last_printer_id = ?, last_material_id = ?, "
                "last_settings_profile_id = ? WHERE id = ?",
                (printer_id, material_id, settings_profile_id, user_id),
            )

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> User:
        return User(
            id=row["id"],
            username=row["username"],
            last_printer_id=row["last_printer_id"],
            last_material_id=row["last_material_id"],
            last_settings_profile_id=row["last_settings_profile_id"],
        )

    # -- API keys ---------------------------------------------------------

    @staticmethod
    def _row_to_key(row: sqlite3.Row) -> ApiKey:
        return ApiKey(
            id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            scope=row["scope"],
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
        )

    def create_api_key(self, user_id: str, *, name: str, scope: str) -> tuple[ApiKey, str]:
        """A new key for a user, and its secret -- the only time the secret exists in the clear."""
        secret = API_KEY_PREFIX + secrets.token_urlsafe(32)
        key_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO api_keys (id, user_id, name, scope, key_hash, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (key_id, user_id, name, scope, _hash_secret(secret), now),
            )
        return ApiKey(id=key_id, user_id=user_id, name=name, scope=scope, created_at=now), secret

    def list_api_keys(self, user_id: str) -> list[ApiKey]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM api_keys WHERE user_id = ? ORDER BY created_at, id", (user_id,)
            ).fetchall()
        return [self._row_to_key(r) for r in rows]

    def delete_api_key(self, user_id: str, key_id: str) -> bool:
        with self._connect() as conn:
            return conn.execute("DELETE FROM api_keys WHERE id = ? AND user_id = ?", (key_id, user_id)).rowcount > 0

    def resolve_api_key(self, secret: str) -> tuple[ApiKey, User] | None:
        """The key and its user for a secret, noting that it was used; None if there is no such key."""
        digest = _hash_secret(secret)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM api_keys WHERE key_hash = ?", (digest,)).fetchone()
            if row is None:
                return None
            used = _now()
            conn.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (used, row["id"]))
        user = self.get_user(row["user_id"])
        if user is None:
            return None
        key = self._row_to_key(row)
        return ApiKey(**{**key.__dict__, "last_used_at": used}), user

    def collapse_to_single_user(self) -> None:
        """Deletes every account and returns to the implicit local user.

        Used by switch-to-single (auth.py) -- reassigning jobs/models/
        printers back to LOCAL_USER_ID is the caller's job, since this
        store only knows about accounts, not the data they own.
        """
        with self._connect() as conn:
            # every account's keys go with their data to the one implicit user
            conn.execute("UPDATE api_keys SET user_id = ?", (LOCAL_USER_ID,))
            conn.execute("DELETE FROM users")
        self.get_or_create_local_user()
        self.set_auth_mode("single")

    def reset_for_tests(self) -> None:
        """Wipe accounts and auth mode back to a fresh-install state.

        Only meaningful in tests: auth_mode/users are process-wide state on
        this module-level singleton, so without a reset one test switching
        to multi-user mode would otherwise leak into every test that runs
        after it in the same pytest session.
        """
        with self._connect() as conn:
            conn.execute("DELETE FROM users")
            conn.execute("DELETE FROM api_keys")
            conn.execute("DELETE FROM app_config WHERE key = 'auth_mode'")

    def get_user_by_username(self, username: str) -> tuple[User, str] | None:
        """(User, password_hash) for login verification, or None if the
        username doesn't exist or has no password set yet."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, username, password_hash, last_printer_id, last_material_id, "
                "last_settings_profile_id FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        if not row or not row["password_hash"]:
            return None
        return self._row_to_user(row), row["password_hash"]


store = UserStore(settings.users_db_path)
