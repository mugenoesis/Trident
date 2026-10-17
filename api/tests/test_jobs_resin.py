import io
import time
from pathlib import Path

import pytest
from resin_support import FAKE_BIN, build_resin_dir

from app import resin as resin_module
from app.config import settings
from app.resin import ResinCatalog


@pytest.fixture()
def resin_setup(tmp_path: Path, monkeypatch):
    catalog = ResinCatalog(build_resin_dir(tmp_path / "resin"))
    catalog.load()
    monkeypatch.setattr(resin_module, "catalog", catalog)
    monkeypatch.setattr(settings, "orcaslicer_bin", str(FAKE_BIN))


def _upload(client, name="cube.stl") -> str:
    resp = client.post("/models", files={"file": (name, io.BytesIO(b"fake stl bytes"), "model/stl")})
    assert resp.status_code == 200
    return resp.json()["model_id"]


def _wait(client, job_id):
    for _ in range(100):
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("the job did not finish")


def _resin_job(**extra):
    return {"technology": "resin", "printer_profile": "Elegoo Mars 3", **extra}


def test_a_resin_job_slices_and_the_printer_file_can_be_downloaded(client, resin_setup):
    model_id = _upload(client, "miniature.stl")
    body = _resin_job(model_id=model_id, filament_profiles=["Test resin"], setting_overrides={"layer_height": 0.05})
    resp = client.post("/jobs", json=body)
    assert resp.status_code == 200, resp.text
    job = _wait(client, resp.json()["id"])
    assert job["status"] == "succeeded"
    assert job["result"]["printer_technology"] == "SLA"
    # the slicer writes text; the job result has numbers
    assert job["result"]["layer_count"] == 400
    assert job["result"]["resin_used_ml"] == 8.0
    assert job["result"]["estimated_print_time_s"] == 5000.0
    assert job["result"]["layer_height_mm"] == 0.05
    assert job["result"]["archive_format"] == "CTBENCRYPTED"

    archive = client.get(f"/jobs/{job['id']}/archive")
    assert archive.status_code == 200
    assert archive.content == b"fake printer file"
    # named after the upload, with the printer file's extension
    assert 'filename="miniature.ctb"' in archive.headers["content-disposition"]


def test_a_failed_resin_job_carries_the_slicers_error(client, resin_setup):
    model_id = _upload(client)
    body = _resin_job(model_id=model_id, setting_overrides={"hollowing_min_thickness": 99})
    job = _wait(client, client.post("/jobs", json=body).json()["id"])
    assert job["status"] == "failed"
    assert job["error"] == "does not fit"


def test_the_archive_of_a_job_that_made_none_is_a_404(client, resin_setup):
    model_id = _upload(client)
    body = _resin_job(model_id=model_id, setting_overrides={"hollowing_min_thickness": 99})
    job = _wait(client, client.post("/jobs", json=body).json()["id"])
    assert client.get(f"/jobs/{job['id']}/archive").status_code == 404


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"printer_profile": "Nope"}, "Unknown resin printer"),
        ({"printer_profile": "Elegoo Old"}, "cannot write yet"),
        ({"filament_profiles": ["Nope"]}, "Unknown resin"),
        ({"filament_profiles": ["Test resin", "Test resin"]}, "at most one resin"),
        ({"setting_overrides": {"print_host": "x"}}, "not available"),
        ({"copies": 2}, "not available for resin"),
    ],
)
def test_a_resin_job_that_cannot_be_honoured_is_refused_up_front(client, resin_setup, extra, message):
    model_id = _upload(client)
    body = {**_resin_job(model_id=model_id), **extra}
    resp = client.post("/jobs", json=body)
    assert resp.status_code == 400
    assert message in resp.json()["detail"]


def test_an_fdm_job_still_needs_a_process_profile(client):
    model_id = _upload(client)
    resp = client.post("/jobs", json={"model_id": model_id, "printer_profile": "Generic Printer"})
    assert resp.status_code == 422
