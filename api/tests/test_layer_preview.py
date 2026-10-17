"""Layer previews of a resin job: a second slice of the same job to an SL1 archive, whose layer images are served one by one."""

from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pytest
from resin_support import FAKE_BIN, build_resin_dir

from app import resin as resin_module
from app.config import settings
from app.resin import ResinCatalog

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@pytest.fixture(autouse=True)
def setup(tmp_path: Path, monkeypatch):
    catalog = ResinCatalog(build_resin_dir(tmp_path / "resin"))
    catalog.load()
    monkeypatch.setattr(resin_module, "catalog", catalog)
    monkeypatch.setattr(settings, "orcaslicer_bin", str(FAKE_BIN))


def _wait(client, url, done=("ready", "failed", "none")):
    for _ in range(200):
        body = client.get(url).json()
        if body["status"] in done:
            return body
        time.sleep(0.05)
    raise AssertionError(f"{url} did not settle")


def _resin_job(client, **overrides) -> str:
    up = client.post("/models", files={"file": ("cube.stl", io.BytesIO(b"fake stl bytes"), "model/stl")})
    body = {
        "technology": "resin",
        "model_id": up.json()["model_id"],
        "printer_profile": "Elegoo Mars 3",
        "filament_profiles": ["Test resin"],
        "setting_overrides": {"layer_height": 0.05, **overrides},
    }
    job_id = client.post("/jobs", json=body).json()["id"]
    for _ in range(200):
        if client.get(f"/jobs/{job_id}").json()["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)
    return job_id


def test_there_is_no_preview_until_one_is_asked_for(client):
    job_id = _resin_job(client)
    assert client.get(f"/jobs/{job_id}/layer-preview").json() == {"status": "none", "layer_count": None, "error": None}
    assert client.get(f"/jobs/{job_id}/layers/0.png").status_code == 404


def test_a_preview_is_made_and_its_layers_are_served(client):
    job_id = _resin_job(client)
    started = client.post(f"/jobs/{job_id}/layer-preview")
    assert started.status_code == 200
    ready = _wait(client, f"/jobs/{job_id}/layer-preview")
    assert ready == {"status": "ready", "layer_count": 3, "error": None}
    first = client.get(f"/jobs/{job_id}/layers/0.png")
    assert first.status_code == 200
    assert first.headers["content-type"] == "image/png"
    assert first.content.startswith(PNG_SIGNATURE)
    assert client.get(f"/jobs/{job_id}/layers/2.png").status_code == 200
    assert client.get(f"/jobs/{job_id}/layers/3.png").status_code == 404


def test_the_preview_is_the_same_slice_in_an_sl1_archive(client):
    job_id = _resin_job(client, exposure_time=2.5)
    client.post(f"/jobs/{job_id}/layer-preview")
    _wait(client, f"/jobs/{job_id}/layer-preview")
    args = json.loads((Path(settings.output_dir) / job_id / "preview" / "args.json").read_text())
    assert args["printer"]["sla_archive_format"] == "SL1"
    assert args["printer"]["name"] == "Elegoo Mars 3"
    assert args["process"]["exposure_time"] == "2.5"
    assert args["material"]["name"] == "Test resin"
    # the job's own printer file is untouched
    assert (Path(settings.output_dir) / job_id / "plate_1.ctb").is_file()


def test_asking_again_does_not_slice_again(client):
    job_id = _resin_job(client)
    client.post(f"/jobs/{job_id}/layer-preview")
    _wait(client, f"/jobs/{job_id}/layer-preview")
    marker = Path(settings.output_dir) / job_id / "preview" / "args.json"
    first = marker.stat().st_mtime_ns
    client.post(f"/jobs/{job_id}/layer-preview")
    time.sleep(0.2)
    assert marker.stat().st_mtime_ns == first


def test_a_preview_that_fails_says_why(client):
    job_id = _resin_job(client, elefant_foot_compensation=98)
    client.post(f"/jobs/{job_id}/layer-preview")
    body = _wait(client, f"/jobs/{job_id}/layer-preview")
    assert body["status"] == "failed"
    assert "preview failed" in body["error"]
    assert client.get(f"/jobs/{job_id}/layers/0.png").status_code == 404


def test_only_a_finished_resin_job_has_a_preview(client):
    failed = _resin_job(client, hollowing_enable=True, hollowing_min_thickness=99)
    assert client.post(f"/jobs/{failed}/layer-preview").status_code == 409
    assert client.post("/jobs/nope/layer-preview").status_code == 404
    assert client.get("/jobs/nope/layers/0.png").status_code == 404
