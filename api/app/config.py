"""Runtime configuration, sourced entirely from the environment.

Every path here is baked to match the Docker volume layout in
docs/ARCHITECTURE.md (`/data/models`, `/data/output`, `/data/orcaslicer-datadir`)
but defaults to local ./data dirs for running the API outside the container.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ORCA_API_", extra="ignore")

    # Path to the built OrcaSlicer binary inside the runtime image.
    orcaslicer_bin: str = "orca-slicer"

    # Baked-in, read-only profile catalog (vendor/orcaslicer/resources/profiles).
    profiles_dir: Path = Path("/opt/orcaslicer/resources/profiles")

    # Baked-in sample models bundled with OrcaSlicer itself (a curated
    # subset is exposed via GET /sample-models -- see api/app/sample_models.py).
    sample_models_dir: Path = Path("/opt/orcaslicer/resources/handy_models")

    # Writable --datadir (presets/cache), distinct from profiles_dir.
    orcaslicer_datadir: Path = Path("/data/orcaslicer-datadir")

    # Uploaded models and per-job output.
    models_dir: Path = Path("/data/models")
    output_dir: Path = Path("/data/output")

    # SQLite job store.
    jobstore_path: Path = Path("/data/output/jobstore.sqlite3")

    # SQLite user/account + auth-mode store.
    users_db_path: Path = Path("/data/output/users.sqlite3")

    # SQLite saved-printers + material-profiles store.
    printers_db_path: Path = Path("/data/output/printers.sqlite3")

    # How long a terminal (succeeded/failed) job's output, and an uploaded
    # model with no remaining job referencing it, survive before the
    # background cleanup sweep deletes them. Active (queued/running) jobs
    # are never touched regardless of age.
    retention_hours: float = 48.0
    cleanup_interval_minutes: float = 30.0

    # AGPL-3.0 source-offer info (see docs/AGPL-COMPLIANCE.md).
    orcaslicer_fork_url: str = "https://github.com/mugenoesis/Pseudorca/tree/headless-orca"
    orcaslicer_commit_sha: str = "unknown"
    wrapper_repo_url: str = "https://github.com/mugenoesis/Trident"

    # How long the --pipe FIFO reader waits for the subprocess to open it,
    # mirroring cli_callback_mgr_t::start()'s ~1s open retry loop.
    pipe_open_timeout_s: float = 5.0

    # Built web/ frontend (npm run build's dist/). Relative default matches
    # running `uvicorn` from the api/ dir against a locally-built frontend;
    # the Docker image overrides this to the baked-in static dir. Mounting
    # is skipped entirely if this path doesn't exist (see main.py), so a
    # missing frontend build never breaks the API itself.
    static_dir: Path = Path("../web/dist")


settings = Settings()

