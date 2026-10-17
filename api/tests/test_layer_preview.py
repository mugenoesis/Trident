"""Layer previews of a resin job: the same slice written again as an SL1 archive, whose layer images are served one by one and
measured, so a layer that will be hard to peel can be pointed out."""

from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pytest
from resin_support import FAKE_BIN, build_resin_dir

from app import layer_preview
from app import resin as resin_module
from app.config import settings
from app.resin import ResinCatalog

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# the stand-in slicer writes 100 x 60 pixel layers; layer i has ((i + 1) * 5) ** 2 white pixels, three layers
# the printer's screen in resin_support is 143.43 x 89.6 mm
PIXEL_MM2 = (143.43 / 100) * (89.6 / 60)
LAYER_CM2 = [((i + 1) * 5) ** 2 * PIXEL_MM2 / 100 for i in range(3)]


@pytest.fixture(autouse=True)
def setup(tmp_path: Path, monkeypatch):
    catalog = ResinCatalog(build_resin_dir(tmp_path / "resin"))
    catalog.load()
    monkeypatch.setattr(resin_module, "catalog", catalog)
    monkeypatch.setattr(settings, "orcaslicer_bin", str(FAKE_BIN))


def _settled(client, job_id):
    for _ in range(300):
        body = client.get(f"/jobs/{job_id}/layer-preview").json()
        if body["status"] in ("ready", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError("the layer preview did not settle")


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


def test_the_preview_is_made_by_itself_once_a_resin_job_has_succeeded(client):
    job_id = _resin_job(client)
    ready = _settled(client, job_id)
    assert ready["status"] == "ready"
    assert ready["layer_count"] == 3
    first = client.get(f"/jobs/{job_id}/layers/0.png")
    assert first.status_code == 200
    assert first.headers["content-type"] == "image/png"
    assert first.content.startswith(PNG_SIGNATURE)
    assert client.get(f"/jobs/{job_id}/layers/2.png").status_code == 200
    assert client.get(f"/jobs/{job_id}/layers/3.png").status_code == 404


def test_the_preview_is_the_same_slice_in_an_sl1_archive(client):
    job_id = _resin_job(client, exposure_time=2.5)
    _settled(client, job_id)
    args = json.loads((Path(settings.output_dir) / job_id / "preview" / "args.json").read_text())
    assert args["printer"]["sla_archive_format"] == "SL1"
    assert args["printer"]["name"] == "Elegoo Mars 3"
    assert args["process"]["exposure_time"] == "2.5"
    assert args["material"]["name"] == "Test resin"
    # the job's own printer file is untouched
    assert (Path(settings.output_dir) / job_id / "plate_1.ctb").is_file()


def test_the_largest_layer_is_found_and_measured_in_square_centimetres(client):
    ready = _settled(client, _resin_job(client))
    assert ready["peak_layer"] == 2
    assert ready["peak_area_cm2"] == pytest.approx(LAYER_CM2[2], rel=0.01)
    assert ready["peel_warning"] is False


def test_a_layer_over_the_limit_raises_the_warning(client, monkeypatch):
    monkeypatch.setattr(layer_preview, "PEEL_WARNING_CM2", LAYER_CM2[1] + 0.1)
    ready = _settled(client, _resin_job(client))
    assert ready["peel_warning"] is True
    assert ready["peel_warning_cm2"] == pytest.approx(LAYER_CM2[1] + 0.1)
    assert ready["peak_layer"] == 2


def test_asking_again_does_not_slice_again(client):
    job_id = _resin_job(client)
    _settled(client, job_id)
    marker = Path(settings.output_dir) / job_id / "preview" / "args.json"
    first = marker.stat().st_mtime_ns
    assert client.post(f"/jobs/{job_id}/layer-preview").json()["status"] == "ready"
    time.sleep(0.2)
    assert marker.stat().st_mtime_ns == first


def test_a_preview_that_fails_says_why_and_can_be_asked_for_again(client):
    job_id = _resin_job(client, elefant_foot_compensation=98)
    body = _settled(client, job_id)
    assert body["status"] == "failed"
    assert "preview failed" in body["error"]
    assert client.get(f"/jobs/{job_id}/layers/0.png").status_code == 404
    marker = Path(settings.output_dir) / job_id / "preview" / "args.json"
    first = marker.stat().st_mtime_ns
    client.post(f"/jobs/{job_id}/layer-preview")
    assert _settled(client, job_id)["status"] == "failed"
    assert marker.stat().st_mtime_ns > first


def test_only_a_finished_resin_job_has_a_preview(client):
    failed = _resin_job(client, hollowing_enable=True, hollowing_min_thickness=99)
    assert client.get(f"/jobs/{failed}/layer-preview").json()["status"] == "none"
    assert client.post(f"/jobs/{failed}/layer-preview").status_code == 409
    assert client.post("/jobs/nope/layer-preview").status_code == 404
    assert client.get("/jobs/nope/layers/0.png").status_code == 404
