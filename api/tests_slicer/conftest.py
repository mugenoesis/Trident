"""Tests that run the real OrcaSlicer on generated multi-colour projects.

They need the slicer binary and its profiles, so they live apart from the fast tests and are skipped when those are
missing. Run them in the container image:

    docker run --rm --entrypoint sh -v "$PWD/api":/src:ro mugenoesis/trident:latest -c \
        'cp -r /src /work && cd /work && /opt/api/.venv/bin/python -m pip install -q pytest && \
         /opt/api/.venv/bin/python -m pytest tests_slicer -v'
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pytest

_BIN = Path(os.environ.get("ORCA_API_ORCASLICER_BIN", "/opt/orcaslicer/orca-slicer"))
_PROFILES = Path(os.environ.get("ORCA_API_PROFILES_DIR", "/opt/orcaslicer/resources/profiles"))
_REAL = _BIN.is_file() and _PROFILES.is_dir()

_tmp = tempfile.TemporaryDirectory()
_base = Path(_tmp.name)
if _REAL:
    os.environ["ORCA_API_ORCASLICER_BIN"] = str(_BIN)
    os.environ["ORCA_API_PROFILES_DIR"] = str(_PROFILES)
    os.environ.setdefault("ORCA_API_MODELS_DIR", str(_base / "models"))
    os.environ.setdefault("ORCA_API_OUTPUT_DIR", str(_base / "output"))
    os.environ.setdefault("ORCA_API_JOBSTORE_PATH", str(_base / "output" / "jobstore.sqlite3"))
    os.environ.setdefault("ORCA_API_USERS_DB_PATH", str(_base / "output" / "users.sqlite3"))
    os.environ.setdefault("ORCA_API_PRINTERS_DB_PATH", str(_base / "output" / "printers.sqlite3"))
    os.environ.setdefault("ORCA_API_ORCASLICER_DATADIR", str(_base / "datadir"))


def pytest_collection_modifyitems(config, items):
    if _REAL:
        return
    skip = pytest.mark.skip(reason=f"the slicer ({_BIN}) and its profiles ({_PROFILES}) are not installed here")
    for item in items:
        item.add_marker(skip)


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def projects(client):
    """Multi-colour projects, made once each: projects(colours, authored_on) -> Path."""
    from app.config import settings

    from project_fixtures import make_project

    made: dict[tuple, Path] = {}
    folder = Path(tempfile.mkdtemp(prefix="slicer-projects-"))

    authors = {
        "x1c": dict(
            authoring_printer="Bambu Lab X1 Carbon 0.4 nozzle",
            authoring_process="0.20mm Standard @BBL X1C",
            authoring_filament="Bambu PLA Basic @BBL X1C",
        ),
        "u1": dict(
            authoring_printer="Snapmaker U1 (0.4 nozzle)",
            authoring_process="0.20 Standard @Snapmaker U1 (0.4 nozzle)",
            authoring_filament="Snapmaker PLA Basic @U1",
        ),
    }

    def make(colours: int, authored_on: str = "x1c") -> Path:
        key = (colours, authored_on)
        if key not in made:
            made[key] = make_project(
                folder / f"{authored_on}_{colours}.3mf",
                colours=colours,
                bin_path=settings.orcaslicer_bin,
                datadir=str(settings.orcaslicer_datadir),
                resolved_dir=Path(tempfile.mkdtemp(prefix="slicer-profiles-")),
                **authors[authored_on],
            )
        return made[key]

    return make


@pytest.fixture(scope="session")
def slice_project(client):
    """slice_project(path, printer, ...) -> (job status, error, G-code written): the job runs the way the app starts it."""
    from app import profiles
    from app.config import settings

    def run(path: Path, *, printer: str, process: str | None, material: str, profiles_count: int, nozzles: int, remap: str = "", colours: int = 1):
        if process is None:
            process = profiles.catalog.get_by_name("machine", printer, None).data.get("default_print_profile")
        overrides = {"nozzle_diameter": ",".join(["0.4"] * nozzles), "nozzle_type": ",".join(["hardened_steel"] * nozzles)}
        if colours > 1:
            overrides["enable_prime_tower"] = "1"  # the app turns it on once there is more than one filament
        if remap:
            overrides["remap_filament_extruder"] = remap
        model = client.post("/models", files={"file": (path.name, path.read_bytes(), "model/3mf")}).json()["model_id"]
        job = client.post(
            "/jobs",
            json={
                "model_id": model,
                "printer_profile": printer,
                "process_profile": process,
                "filament_profiles": [material] * profiles_count,
                "setting_overrides": overrides,
            },
        ).json()
        deadline = time.time() + 300
        state = {}
        while time.time() < deadline:
            state = client.get(f"/jobs/{job['id']}").json()
            if state["status"] in ("succeeded", "failed"):
                break
            time.sleep(0.5)
        gcode = client.get(f"/jobs/{job['id']}/gcode")
        return state["status"], state.get("error") or "", gcode.status_code == 200 and len(gcode.content) > 1000

    return run
