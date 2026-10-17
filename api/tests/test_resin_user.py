"""Resins made by the user ("My resins"): saved from values on screen, listed and chosen like the built-in ones, private to the user."""

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
from app.resin_user import UserResins

CHOICE = {"printer": "Elegoo Mars 3", "layer_height": 0.05}


@pytest.fixture(autouse=True)
def setup(tmp_path: Path, monkeypatch):
    catalog = ResinCatalog(build_resin_dir(tmp_path / "resin"))
    catalog.load()
    monkeypatch.setattr(resin_module, "catalog", catalog)
    monkeypatch.setattr(settings, "models_dir", tmp_path / "models")
    monkeypatch.setattr(settings, "orcaslicer_bin", str(FAKE_BIN))


def _mine(**overrides):
    body = {
        "name": "My grey",
        **CHOICE,
        "settings": {"exposure_time": 3.1, "initial_exposure_time": 25, "lift_distance": 6},
        "based_on": "Test resin",
    }
    body.update(overrides)
    return body


def test_a_resin_made_from_values_is_listed_with_the_built_in_ones(client):
    resp = client.post("/resin/my-resins", json=_mine())
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "My grey"
    assert resp.json()["vendor"] == "My resins"
    names = {r["name"]: r for r in client.get("/resin/resins").json()}
    assert "Test resin" in names
    assert names["My grey"]["vendor"] == "My resins"


def test_the_choice_for_my_resin_is_the_values_i_saved(client):
    client.post("/resin/my-resins", json=_mine())
    body = client.get("/resin/choice", params={"resin": "My grey", **CHOICE}).json()
    assert body["match"] == "exact"
    assert body["exact_layer_height"] is True
    assert body["settings"]["exposure_time"] == pytest.approx(3.1)
    assert body["settings"]["lift_distance"] == pytest.approx(6)
    assert "Test resin" in body["notes"]


def test_saving_under_a_name_i_already_made_adds_a_row_for_that_printer_and_layer_height(client):
    client.post("/resin/my-resins", json=_mine())
    client.post("/resin/my-resins", json=_mine(layer_height=0.1, settings={"exposure_time": 6}))
    client.post("/resin/my-resins", json=_mine(settings={"exposure_time": 3.3}))
    fine = client.get("/resin/choice", params={"resin": "My grey", **CHOICE}).json()
    coarse = client.get(
        "/resin/choice", params={"resin": "My grey", "printer": "Elegoo Mars 3", "layer_height": 0.1}
    ).json()
    assert fine["settings"]["exposure_time"] == pytest.approx(3.3)  # the same printer and layer height is replaced
    assert coarse["settings"]["exposure_time"] == pytest.approx(6)
    assert len([r for r in client.get("/resin/resins").json() if r["name"] == "My grey"]) == 1


@pytest.mark.parametrize(
    ("overrides", "status"),
    [
        ({"name": "Test resin"}, 409),  # a built-in name
        ({"name": ""}, 422),
        ({"printer": "Nobody Nothing"}, 400),
        ({"settings": {"hollowing_enable": 1}}, 400),  # not one of the resin's own values
        ({"settings": {"exposure_time": "long"}}, 422),
        ({"layer_height": 0}, 422),
        ({"based_on": "No such resin"}, 400),
    ],
)
def test_a_resin_that_cannot_be_saved_is_refused(client, overrides, status):
    assert client.post("/resin/my-resins", json=_mine(**overrides)).status_code == status


def test_a_resin_of_mine_can_be_deleted_but_a_built_in_one_cannot(client):
    client.post("/resin/my-resins", json=_mine())
    assert client.delete("/resin/my-resins/My grey").status_code == 200
    assert "My grey" not in {r["name"] for r in client.get("/resin/resins").json()}
    assert client.delete("/resin/my-resins/My grey").status_code == 404
    assert client.delete("/resin/my-resins/Test resin").status_code == 404


def test_a_resin_of_mine_is_a_resin_to_slice_with(client):
    client.post("/resin/my-resins", json=_mine())
    up = client.post("/models", files={"file": ("cube.stl", io.BytesIO(b"fake stl bytes"), "model/stl")})
    body = {
        "technology": "resin",
        "model_id": up.json()["model_id"],
        "printer_profile": "Elegoo Mars 3",
        "filament_profiles": ["My grey"],
        "setting_overrides": {"layer_height": 0.05},
    }
    job_id = client.post("/jobs", json=body).json()["id"]
    job: dict = {}
    for _ in range(100):
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "succeeded", job
    args = json.loads(Path(settings.output_dir, job_id, "args.json").read_text())
    assert args["material"]["name"] == "My grey"
    assert args["material"]["settings"][0]["exposure_time"] == 3.1


def test_one_users_resins_are_not_another_users(tmp_path: Path):
    store = UserResins(tmp_path)
    store.save("alice", "Alice grey", "Elegoo Mars 3", 0.05, {"exposure_time": 2}, based_on=None)
    assert [r["name"] for r in store.list("alice")] == ["Alice grey"]
    assert store.list("bob") == []
    assert store.path("bob", "Alice grey") is None
    assert store.path("alice", "Alice grey") is not None


def test_a_bottle_price_and_size_are_kept_with_my_resin(client):
    client.post(
        "/resin/my-resins", json=_mine(settings={"exposure_time": 3, "bottle_cost": 29.9, "bottle_volume": 1000})
    )
    body = client.get("/resin/choice", params={"resin": "My grey", **CHOICE}).json()
    assert body["settings"]["bottle_cost"] == pytest.approx(29.9)
    assert body["settings"]["bottle_volume"] == pytest.approx(1000)
