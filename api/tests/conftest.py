from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_tmp = tempfile.TemporaryDirectory()
_base = Path(_tmp.name)

os.environ.setdefault("ORCA_API_MODELS_DIR", str(_base / "models"))
os.environ.setdefault("ORCA_API_OUTPUT_DIR", str(_base / "output"))
os.environ.setdefault("ORCA_API_JOBSTORE_PATH", str(_base / "output" / "jobstore.sqlite3"))
os.environ.setdefault("ORCA_API_PROFILES_DIR", str(_base / "profiles"))
os.environ.setdefault("ORCA_API_ORCASLICER_DATADIR", str(_base / "datadir"))
os.environ.setdefault("ORCA_API_ORCASLICER_BIN", "orca-slicer-not-installed-in-tests")


@pytest.fixture()
def data_dirs() -> dict[str, Path]:
    return {
        "models": Path(os.environ["ORCA_API_MODELS_DIR"]),
        "output": Path(os.environ["ORCA_API_OUTPUT_DIR"]),
        "profiles": Path(os.environ["ORCA_API_PROFILES_DIR"]),
    }


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
