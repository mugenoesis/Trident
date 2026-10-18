"""Hollowing a model for resin printing: a model goes in, the same model with a cavity in it comes out, as an STL.

Used by Holecraft's Hollow button; its key may upload models and hollow them, and do nothing else."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from resin_support import FAKE_BIN, build_resin_dir

from app import resin as resin_module
from app.config import settings
from app.resin import ResinCatalog


@pytest.fixture(autouse=True)
def setup(tmp_path: Path, monkeypatch):
    catalog = ResinCatalog(build_resin_dir(tmp_path / "resin"))
    catalog.load()
    monkeypatch.setattr(resin_module, "catalog", catalog)
    monkeypatch.setattr(settings, "orcaslicer_bin", str(FAKE_BIN))


def _hollow(client, name="cube.stl", data=b"fake stl bytes", **fields):
    return client.post(
        "/resin/hollow", files={"file": (name, io.BytesIO(data), "application/octet-stream")}, data=fields
    )


def test_a_model_comes_back_hollowed_as_an_stl(client):
    resp = _hollow(client, wall_thickness="3", quality="0.75")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "model/stl"
    assert resp.headers["content-disposition"].endswith('cube-hollow.stl"')
    # the slicer was asked for the wall and the accuracy, and given the model that was sent
    assert b"wall=3 " in resp.content
    assert b"quality=0.75" in resp.content
    assert b"model=.stl" in resp.content
    assert resp.headers["x-volume-before-mm3"] == "8000.0"
    assert resp.headers["x-volume-after-mm3"] == "3900.0"


def test_the_wall_and_accuracy_start_at_2_mm_and_normal(client):
    resp = _hollow(client)
    assert b"wall=2 " in resp.content
    assert b"quality=0.5" in resp.content


@pytest.mark.parametrize("name", ["part.3mf", "part.obj", "PART.STL"])
def test_models_of_the_usual_kinds_are_accepted(client, name):
    assert _hollow(client, name=name).status_code == 200


@pytest.mark.parametrize(
    ("name", "fields", "status"),
    [
        ("notes.txt", {}, 400),
        ("cube.stl", {"wall_thickness": "0"}, 422),
        ("cube.stl", {"wall_thickness": "0.1"}, 422),
        ("cube.stl", {"wall_thickness": "50"}, 422),
        ("cube.stl", {"quality": "0"}, 422),
        ("cube.stl", {"quality": "2"}, 422),
        ("cube.stl", {"wall_thickness": "abc"}, 422),
    ],
)
def test_a_request_that_makes_no_sense_is_refused(client, name, fields, status):
    assert _hollow(client, name=name, **fields).status_code == status


def test_a_model_too_thin_for_the_wall_says_so(client):
    resp = _hollow(client, wall_thickness="13")
    assert resp.status_code == 422
    assert "too thin" in resp.json()["detail"]


def test_an_empty_file_is_refused(client):
    assert _hollow(client, data=b"").status_code == 400


def test_a_key_that_may_hollow_can_upload_and_hollow_and_nothing_else(client):
    made = client.post("/auth/keys", json={"name": "Holecraft", "scope": "hollow"})
    assert made.status_code == 200, made.text
    auth = {"Authorization": f"Bearer {made.json()['key']}"}
    assert client.get("/auth/keys").json()[0]["scope"] == "hollow"
    files = {"file": ("cube.stl", io.BytesIO(b"fake stl bytes"), "model/stl")}
    assert client.post("/resin/hollow", files=files, headers=auth).status_code == 200
    assert (
        client.post(
            "/models", files={"file": ("cube.stl", io.BytesIO(b"fake stl bytes"), "model/stl")}, headers=auth
        ).status_code
        == 200
    )
    assert client.get("/jobs", headers=auth).status_code == 403
    assert client.get("/resin/printers", headers=auth).status_code == 403


def test_an_upload_only_key_cannot_hollow(client):
    made = client.post("/auth/keys", json={"name": "Holecraft", "scope": "upload"})
    auth = {"Authorization": f"Bearer {made.json()['key']}"}
    files = {"file": ("cube.stl", io.BytesIO(b"fake stl bytes"), "model/stl")}
    assert client.post("/resin/hollow", files=files, headers=auth).status_code == 403


def test_a_full_access_key_can_hollow(client):
    made = client.post("/auth/keys", json={"name": "All", "scope": "full"})
    auth = {"Authorization": f"Bearer {made.json()['key']}"}
    files = {"file": ("cube.stl", io.BytesIO(b"fake stl bytes"), "model/stl")}
    assert client.post("/resin/hollow", files=files, headers=auth).status_code == 200
