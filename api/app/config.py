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

    # Writable --datadir (presets/cache), distinct from profiles_dir.
    orcaslicer_datadir: Path = Path("/data/orcaslicer-datadir")

    # Uploaded models and per-job output.
    models_dir: Path = Path("/data/models")
    output_dir: Path = Path("/data/output")

    # SQLite job store.
    jobstore_path: Path = Path("/data/output/jobstore.sqlite3")

    # AGPL-3.0 source-offer info (see docs/AGPL-COMPLIANCE.md).
    orcaslicer_fork_url: str = "https://github.com/TBD/OrcaSlicer/tree/headless-cli"
    orcaslicer_commit_sha: str = "unknown"
    wrapper_repo_url: str = "https://github.com/TBD/headless-orca"

    # How long the --pipe FIFO reader waits for the subprocess to open it,
    # mirroring cli_callback_mgr_t::start()'s ~1s open retry loop.
    pipe_open_timeout_s: float = 5.0


settings = Settings()
