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
os.environ.setdefault("ORCA_API_USERS_DB_PATH", str(_base / "output" / "users.sqlite3"))
os.environ.setdefault("ORCA_API_PRINTERS_DB_PATH", str(_base / "output" / "printers.sqlite3"))
os.environ.setdefault("ORCA_API_PROFILES_DIR", str(_base / "profiles"))
os.environ.setdefault("ORCA_API_ORCASLICER_DATADIR", str(_base / "datadir"))
os.environ.setdefault("ORCA_API_ORCASLICER_BIN", "orca-slicer-not-installed-in-tests")
os.environ.setdefault("ORCA_API_SAMPLE_MODELS_DIR", str(_base / "sample_models"))

# Stand-ins for the real vendor/orcaslicer/resources/handy_models files
# (not available in this test environment) -- test_sample_models.py's
# fixtures need actual files at the catalog's expected filenames for
# is_file()/copyfile() to succeed. Content is irrelevant; only the
# filename and presence matter here.
_sample_models_dir = Path(os.environ["ORCA_API_SAMPLE_MODELS_DIR"])
_sample_models_dir.mkdir(parents=True, exist_ok=True)
for _fixture_filename in ("3DBenchy.drc", "OrcaCube_v2.drc", "OrcaBadge.3mf", "Stanford_Bunny.drc"):
    (_sample_models_dir / _fixture_filename).write_bytes(b"fake sample model bytes")


@pytest.fixture()
def data_dirs() -> dict[str, Path]:
    return {
        "models": Path(os.environ["ORCA_API_MODELS_DIR"]),
        "output": Path(os.environ["ORCA_API_OUTPUT_DIR"]),
        "profiles": Path(os.environ["ORCA_API_PROFILES_DIR"]),
    }


@pytest.fixture(autouse=True)
def _reset_shared_state():
    # jobs/printers/users all live in process-wide singletons, so without a
    # reset, one test's jobs/accounts would leak into every test that runs
    # after it in the same pytest session.
    from app.jobstore import store as job_store
    from app.printerstore import store as printer_store
    from app.userstore import store as user_store

    user_store.reset_for_tests()
    printer_store.reset_for_tests()
    job_store.reset_for_tests()
    yield
    user_store.reset_for_tests()
    printer_store.reset_for_tests()
    job_store.reset_for_tests()


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
