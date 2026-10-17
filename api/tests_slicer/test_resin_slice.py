"""Resin slicing through the real slicer: the catalogue, a resin's settings, and a job that writes the printer's file."""

from __future__ import annotations

import io
import time

import pytest


def _cube_stl(size: float = 5.0) -> bytes:
    """An ASCII STL box, so the test needs no fixture file."""
    v = [(x, y, z) for z in (0, size) for y in (0, size) for x in (0, size)]
    lines = ["solid box"]
    for a, b, c, d in ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)):
        for tri in ((v[a], v[b], v[c]), (v[a], v[c], v[d])):
            lines.append("facet normal 0 0 0\nouter loop")
            lines += [f"vertex {p[0]:g} {p[1]:g} {p[2]:g}" for p in tri]
            lines.append("endloop\nendfacet")
    lines.append("endsolid box")
    return "\n".join(lines).encode()


def _upload(client) -> str:
    resp = client.post("/models", files={"file": ("cube.stl", io.BytesIO(_cube_stl()), "model/stl")})
    assert resp.status_code == 200, resp.text
    return resp.json()["model_id"]


def _wait(client, job_id, timeout=300):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.5)
    raise AssertionError("the resin job did not finish")


def test_the_catalogue_has_the_printers_and_resins(client):
    printers = {p["name"]: p for p in client.get("/resin/printers").json()}
    mars = printers["Elegoo Mars 3"]
    assert mars["supported"] is True
    assert mars["pixels_x"] > 1000
    assert "UniFormation GKtwo" in printers
    assert "TinyMaker TinyMaker" in printers
    resins = {r["name"] for r in client.get("/resin/resins").json()}
    assert "Siraya Tech Easy Grey" in resins


def test_a_resin_shows_the_makers_settings_for_a_printer(client):
    body = client.get(
        "/resin/choice", params={"resin": "Siraya Tech Easy Grey", "printer": "Elegoo Mars 3", "layer_height": 0.05}
    ).json()
    assert body["match"] == "exact"
    assert body["exact_layer_height"] is True
    assert body["settings"]["exposure_time"] == pytest.approx(2.0)
    assert body["settings"]["initial_exposure_time"] == pytest.approx(20.0)
    assert body["source"].startswith("https://siraya.tech/")


def test_a_resin_job_writes_the_printers_file(client):
    model_id = _upload(client)
    body = {
        "technology": "resin",
        "printer_profile": "Elegoo Mars 3",
        "model_id": model_id,
        "filament_profiles": ["Siraya Tech Easy Grey"],
        "setting_overrides": {
            "layer_height": 0.1,
            "initial_layer_height": 0.1,
            "supports_enable": False,
            "pad_enable": False,
        },
    }
    resp = client.post("/jobs", json=body)
    assert resp.status_code == 200, resp.text
    job = _wait(client, resp.json()["id"])
    assert job["status"] == "succeeded", job.get("error")
    assert job["result"]["printer_technology"] == "SLA"
    assert job["result"]["layer_count"] == pytest.approx(50, abs=2)
    assert job["result"]["resin_used_ml"] == pytest.approx(0.125, rel=0.1)  # a 5 mm cube

    archive = client.get(f"/jobs/{job['id']}/archive")
    assert archive.status_code == 200
    assert int.from_bytes(archive.content[:4], "little") == 0x12FD0107  # the encrypted CTB magic
    assert len(archive.content) > 10_000


def test_a_resin_with_no_row_for_the_printer_fails_with_a_clear_message(client):
    model_id = _upload(client)
    body = {
        "technology": "resin",
        "printer_profile": "Elegoo Mars 3",
        "model_id": model_id,
        "filament_profiles": ["Siraya Tech Build"],
        "setting_overrides": {"layer_height": 0.1},
    }
    job = _wait(client, client.post("/jobs", json=body).json()["id"])
    assert job["status"] == "failed"
    assert "no settings for this printer" in (job["error"] or "")


def test_a_layer_preview_is_the_real_slice_as_png_layers(client):
    model_id = _upload(client)
    body = {
        "technology": "resin",
        "model_id": model_id,
        "printer_profile": "Elegoo Mars 3",
        "filament_profiles": ["Siraya Tech Easy Grey"],
        "setting_overrides": {
            "layer_height": 0.1,
            "supports_enable": False,
            "pad_enable": False,
            "hollowing_enable": False,
        },
    }
    job = _wait(client, client.post("/jobs", json=body).json()["id"])
    assert job["status"] == "succeeded"
    assert client.post(f"/jobs/{job['id']}/layer-preview").status_code == 200
    preview: dict = {}
    for _ in range(600):
        preview = client.get(f"/jobs/{job['id']}/layer-preview").json()
        if preview["status"] != "running":
            break
        time.sleep(0.5)
    assert preview["status"] == "ready", preview
    assert preview["layer_count"] == job["result"]["layer_count"]
    # a 5 mm cube: its largest layer is 5 x 5 mm = 0.25 cm2, nowhere near a hard peel
    assert 0.15 < preview["peak_area_cm2"] < 0.35
    assert preview["peel_warning"] is False
    layer = client.get(f"/jobs/{job['id']}/layers/{preview['layer_count'] // 2}.png")
    assert layer.status_code == 200
    assert layer.content.startswith(b"\x89PNG")


def test_a_printer_made_by_the_user_is_sliced_for_by_the_real_slicer(client):
    made = client.post(
        "/resin/my-printers",
        json={
            "name": "My test printer",
            "display_width_mm": 143.36,
            "display_height_mm": 89.6,
            "pixels_x": 2048,
            "pixels_y": 1280,
            "build_height_mm": 175,
            "format": "GOO",
            "copy_from": "Elegoo Mars 3",
        },
    )
    assert made.status_code == 200, made.text
    body = {
        "technology": "resin",
        "model_id": _upload(client),
        "printer_profile": "My test printer",
        "filament_profiles": ["Siraya Tech Easy Grey"],
        "setting_overrides": {
            "layer_height": 0.1,
            "supports_enable": False,
            "pad_enable": False,
            "hollowing_enable": False,
        },
    }
    job = _wait(client, client.post("/jobs", json=body).json()["id"])
    assert job["status"] == "succeeded", job["error"]
    assert job["result"]["archive_format"] == "GOO"
    assert job["result"]["archive_file"].endswith(".goo")
    archive = client.get(f"/jobs/{job['id']}/archive")
    assert archive.status_code == 200
    assert archive.headers["content-disposition"].endswith('.goo"')
    assert client.delete("/resin/my-printers/My test printer").status_code == 200
