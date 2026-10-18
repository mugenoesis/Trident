"""Hand-placed support points for resin printing: the slicer generates the points, Holecraft lets the user move them and sends
them back with the model, and the resin job builds supports for exactly those points.

Used by Holecraft's support editor; its key may upload models, hollow them and ask for support points."""

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
from app.routers import jobs as jobs_router

POINTS = {
    "objects": [
        {
            "points": [
                {"x": 5, "y": 5, "z": 0, "radius": 0.4, "type": "manual"},
                {"x": 15, "y": 5, "z": 0, "radius": 0.5, "type": "manual"},
            ]
        }
    ]
}


@pytest.fixture(autouse=True)
def setup(tmp_path: Path, monkeypatch):
    catalog = ResinCatalog(build_resin_dir(tmp_path / "resin"))
    catalog.load()
    monkeypatch.setattr(resin_module, "catalog", catalog)
    monkeypatch.setattr(settings, "orcaslicer_bin", str(FAKE_BIN))
    monkeypatch.setattr(jobs_router, "_job_output_dir", lambda job_id: tmp_path / "jobs" / job_id)


def _supports(client, name="cube.stl", data=b"fake stl bytes", **fields):
    fields = {"printer": "Elegoo Mars 3", **fields}
    return client.post(
        "/resin/supports", files={"file": (name, io.BytesIO(data), "application/octet-stream")}, data=fields
    )


def _upload(client, points=None, name="cube.stl"):
    """Upload a model; with `points`, also store them with it (a second request: PUT .../support-points)."""
    resp = client.post("/models", files={"file": (name, io.BytesIO(b"fake stl bytes"), "model/stl")})
    if points is None or resp.status_code != 200:
        return resp
    return _put_points(client, resp.json()["model_id"], points)


def _put_points(client, model_id, points, headers=None):
    body = points if isinstance(points, str) else json.dumps(points)
    return client.put(
        f"/models/{model_id}/support-points",
        content=body,
        headers={"content-type": "application/json", **(headers or {})},
    )


def _wait(client, job_id):
    for _ in range(100):
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("the job did not finish")


def _job_args(tmp_path: Path, job_id: str) -> dict:
    return json.loads((tmp_path / "jobs" / job_id / "args.json").read_text())


def _run_job(client, model_id, **extra):
    body = {"technology": "resin", "printer_profile": "Elegoo Mars 3", "model_id": model_id, **extra}
    resp = client.post("/jobs", json=body)
    assert resp.status_code == 200, resp.text
    return _wait(client, resp.json()["id"])


def test_the_slicer_generates_support_points_for_a_model(client):
    resp = _supports(client)
    assert resp.status_code == 200, resp.text
    points = resp.json()["objects"][0]["points"]
    assert len(points) == 3  # what the stand-in slicer makes up
    assert set(points[0]) >= {"x", "y", "z", "radius", "type"}


def test_the_printer_and_settings_reach_the_slicer(client, tmp_path):
    resp = _supports(client, settings=json.dumps({"support_points_density_relative": 150}))
    assert resp.status_code == 200, resp.text
    echoed = resp.json()["objects"][0]["points"][0]
    # the stand-in writes the printer's display width and the density it was given into the first point
    assert echoed["x"] == 143.43
    assert echoed["y"] == 150


@pytest.mark.parametrize(
    ("name", "fields", "status"),
    [
        ("notes.txt", {}, 400),
        ("cube.stl", {"printer": "No such printer"}, 404),
        ("cube.stl", {"printer": "Elegoo Old"}, 400),
        ("cube.stl", {"settings": "not json"}, 422),
        ("cube.stl", {"settings": json.dumps({"fill_density": 5})}, 400),
    ],
)
def test_a_request_that_makes_no_sense_is_refused(client, name, fields, status):
    assert _supports(client, name=name, **fields).status_code == status


def test_an_empty_file_is_refused(client):
    assert _supports(client, data=b"").status_code == 400


def test_a_model_the_slicer_cannot_place_points_on_says_why(client):
    resp = _supports(client, settings=json.dumps({"hollowing_min_thickness": 99}))
    assert resp.status_code == 422
    assert "does not fit" in resp.json()["detail"]


def test_a_model_uploaded_with_support_points_keeps_them(client):
    resp = _upload(client, POINTS)
    assert resp.status_code == 200, resp.text
    assert resp.json()["support_point_count"] == 2
    model_id = resp.json()["model_id"]
    assert client.get(f"/models/{model_id}").json()["support_point_count"] == 2


def test_a_model_uploaded_without_support_points_has_none(client):
    resp = _upload(client)
    assert resp.json()["support_point_count"] is None


@pytest.mark.parametrize(
    "points",
    [
        "not json",
        {"objects": 3},
        {"objects": [{"points": [{"x": 1}]}]},
        {"objects": [{"points": [{"x": 1, "y": 2, "z": 3, "radius": 0}]}]},
    ],
)
def test_support_points_that_are_not_usable_are_refused(client, points):
    assert _upload(client, points).status_code == 422


def test_a_resin_job_uses_the_support_points_of_its_model(client, tmp_path):
    model_id = _upload(client, POINTS).json()["model_id"]
    job = _run_job(client, model_id)
    assert job["status"] == "succeeded"
    given = _job_args(tmp_path, job["id"])["support_points_input"]
    assert given == POINTS
    assert job["result"]["support_point_count"] == 2


def test_a_resin_job_can_ignore_the_support_points_of_its_model(client, tmp_path):
    model_id = _upload(client, POINTS).json()["model_id"]
    job = _run_job(client, model_id, hand_placed_supports=False)
    assert job["status"] == "succeeded"
    assert _job_args(tmp_path, job["id"])["support_points_input"] is None
    assert job["result"]["support_point_count"] == 12  # generated: what the stand-in slicer makes up


def test_a_model_without_support_points_gets_generated_ones(client, tmp_path):
    model_id = _upload(client).json()["model_id"]
    job = _run_job(client, model_id)
    assert _job_args(tmp_path, job["id"])["support_points_input"] is None


def test_a_resin_key_may_upload_hollow_place_supports_and_see_the_printers_and_nothing_else(client):
    made = client.post("/auth/keys", json={"name": "Holecraft", "scope": "resin"})
    assert made.status_code == 200, made.text
    auth = {"Authorization": f"Bearer {made.json()['key']}"}
    assert client.get("/auth/keys").json()[0]["scope"] == "resin"
    files = {"file": ("cube.stl", io.BytesIO(b"fake stl bytes"), "model/stl")}
    assert (
        client.post("/resin/supports", files=files, data={"printer": "Elegoo Mars 3"}, headers=auth).status_code == 200
    )
    files = {"file": ("cube.stl", io.BytesIO(b"fake stl bytes"), "model/stl")}
    assert client.post("/resin/hollow", files=files, headers=auth).status_code == 200
    files = {"file": ("cube.stl", io.BytesIO(b"fake stl bytes"), "model/stl")}
    stored = client.post("/models", files=files, headers=auth)
    assert stored.status_code == 200
    assert _put_points(client, stored.json()["model_id"], POINTS, headers=auth).status_code == 200
    assert client.get("/jobs", headers=auth).status_code == 403
    # the printers: Holecraft offers them to place the points for
    printers = client.get("/resin/printers", headers=auth)
    assert printers.status_code == 200
    assert "Elegoo Mars 3" in [p["name"] for p in printers.json()]
    assert client.get("/resin/resins", headers=auth).status_code == 403


def test_an_upload_only_key_cannot_place_supports(client):
    made = client.post("/auth/keys", json={"name": "Holecraft", "scope": "upload"})
    auth = {"Authorization": f"Bearer {made.json()['key']}"}
    stored = client.post(
        "/models", files={"file": ("cube.stl", io.BytesIO(b"fake stl bytes"), "model/stl")}, headers=auth
    )
    assert _put_points(client, stored.json()["model_id"], POINTS, headers=auth).status_code == 403
    files = {"file": ("cube.stl", io.BytesIO(b"fake stl bytes"), "model/stl")}
    assert (
        client.post("/resin/supports", files=files, data={"printer": "Elegoo Mars 3"}, headers=auth).status_code == 403
    )


def test_the_layer_preview_is_made_with_the_same_support_points(client, tmp_path):
    model_id = _upload(client, POINTS).json()["model_id"]
    job = _run_job(client, model_id)
    preview_args = tmp_path / "jobs" / job["id"] / "preview" / "args.json"
    for _ in range(100):  # the preview is made right after the job reads as done
        if preview_args.is_file():
            break
        time.sleep(0.05)
    assert json.loads(preview_args.read_text())["support_points_input"] == POINTS


def test_support_points_can_be_replaced_and_taken_away(client):
    model_id = _upload(client, POINTS).json()["model_id"]
    one = {"objects": [{"points": [{"x": 1, "y": 2, "z": 3, "radius": 0.5}]}]}
    assert _put_points(client, model_id, one).json()["support_point_count"] == 1
    assert client.get(f"/models/{model_id}").json()["support_point_count"] == 1
    gone = client.delete(f"/models/{model_id}/support-points")
    assert gone.status_code == 200
    assert gone.json()["support_point_count"] is None
    assert client.get(f"/models/{model_id}").json()["support_point_count"] is None


def test_an_empty_list_of_points_is_kept_it_means_no_supports(client):
    model_id = _upload(client, {"objects": [{"points": []}]}).json()["model_id"]
    assert client.get(f"/models/{model_id}").json()["support_point_count"] == 0


def test_support_points_for_a_model_that_is_not_there_are_a_404(client):
    assert _put_points(client, "0" * 32, POINTS).status_code == 404
    assert client.delete(f"/models/{'0' * 32}/support-points").status_code == 404
