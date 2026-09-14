from __future__ import annotations

import io

from app.auth import hash_password, verify_password
from app.userstore import UserStore


def test_hash_and_verify_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_userstore_secret_key_persists(tmp_path):
    db_path = tmp_path / "users.sqlite3"
    key1 = UserStore(db_path).get_secret_key()
    key2 = UserStore(db_path).get_secret_key()
    assert key1 == key2


def test_default_mode_behaves_like_single_user(client):
    # Fresh test DB: auth_mode is "unset" until /auth/setup runs. Uploading
    # and slicing should still work with zero auth friction -- unset behaves
    # like single-user, not like "nobody is authenticated".
    status = client.get("/auth/status").json()
    assert status["mode"] == "unset"
    assert status["logged_in"] is True

    resp = client.post(
        "/models", files={"file": ("cube.stl", io.BytesIO(b"fake stl"), "model/stl")}
    )
    assert resp.status_code == 200


def test_setup_single_mode(client):
    resp = client.post("/auth/setup", json={"mode": "single"})
    assert resp.status_code == 200
    assert resp.json() == {"mode": "single", "logged_in": True, "username": None}

    # Can't set up twice.
    again = client.post("/auth/setup", json={"mode": "single"})
    assert again.status_code == 409


def test_setup_multi_mode_and_login_roundtrip(client):
    resp = client.post(
        "/auth/setup", json={"mode": "multi", "username": "alice", "password": "hunter2"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"mode": "multi", "logged_in": True, "username": "alice"}
    # The setup response sets a session cookie -- confirm status reflects it.
    assert client.get("/auth/status").json()["logged_in"] is True

    client.post("/auth/logout")
    assert client.get("/auth/status").json()["logged_in"] is False

    bad = client.post("/auth/login", json={"username": "alice", "password": "wrong"})
    assert bad.status_code == 401

    good = client.post("/auth/login", json={"username": "alice", "password": "hunter2"})
    assert good.status_code == 200
    assert client.get("/auth/status").json()["logged_in"] is True


def test_multi_mode_requires_login_for_owned_endpoints(client):
    client.post("/auth/setup", json={"mode": "multi", "username": "alice", "password": "pw12345"})
    client.post("/auth/logout")

    resp = client.post(
        "/models", files={"file": ("cube.stl", io.BytesIO(b"fake stl"), "model/stl")}
    )
    assert resp.status_code == 401


def test_switch_to_multi_keeps_existing_data_owned_by_local_user(client):
    client.post("/auth/setup", json={"mode": "single"})
    upload = client.post(
        "/models", files={"file": ("cube.stl", io.BytesIO(b"fake stl"), "model/stl")}
    )
    assert upload.status_code == 200

    switched = client.post(
        "/auth/switch-to-multi", json={"username": "alice", "password": "hunter2"}
    )
    assert switched.status_code == 200
    assert switched.json()["username"] == "alice"

    # Now logged in as "alice" (== the former local user); a second account
    # created from here starts empty and isolated.
    created = client.post("/auth/users", json={"username": "bob", "password": "pw12345"})
    assert created.status_code == 200

    client.post("/auth/logout")
    client.post("/auth/login", json={"username": "bob", "password": "pw12345"})
    assert client.get("/jobs").json() == []


def test_creating_a_user_requires_being_logged_in(client):
    client.post("/auth/setup", json={"mode": "multi", "username": "alice", "password": "pw12345"})
    client.post("/auth/logout")
    resp = client.post("/auth/users", json={"username": "bob", "password": "pw12345"})
    assert resp.status_code == 401


def test_second_user_cannot_see_or_slice_first_users_model(client, monkeypatch):
    from app import cli_runner
    from app.cli_runner import SliceResult

    monkeypatch.setattr(
        cli_runner,
        "run_slice",
        lambda **kwargs: SliceResult(
            return_code=0, result_json={"return_code": 0}, stdout="", stderr="", used_result_json=True
        ),
    )

    client.post("/auth/setup", json={"mode": "multi", "username": "alice", "password": "pw12345"})
    model_resp = client.post(
        "/models", files={"file": ("cube.stl", io.BytesIO(b"fake stl"), "model/stl")}
    )
    model_id = model_resp.json()["model_id"]
    job_resp = client.post(
        "/jobs",
        json={"model_id": model_id, "printer_profile": "Generic Printer", "process_profile": "0.20mm Standard"},
    )
    job_id = job_resp.json()["id"]

    client.post("/auth/users", json={"username": "bob", "password": "pw12345"})
    client.post("/auth/logout")
    client.post("/auth/login", json={"username": "bob", "password": "pw12345"})

    assert client.get(f"/jobs/{job_id}").status_code == 404
    assert client.get("/jobs").json() == []
    slice_as_bob = client.post(
        "/jobs",
        json={"model_id": model_id, "printer_profile": "Generic Printer", "process_profile": "0.20mm Standard"},
    )
    assert slice_as_bob.status_code == 404


def test_switch_to_single_merges_everyones_data_and_removes_accounts(client, monkeypatch):
    from app import cli_runner
    from app.cli_runner import SliceResult

    monkeypatch.setattr(
        cli_runner,
        "run_slice",
        lambda **kwargs: SliceResult(
            return_code=0, result_json={"return_code": 0}, stdout="", stderr="", used_result_json=True
        ),
    )

    client.post("/auth/setup", json={"mode": "multi", "username": "alice", "password": "pw12345"})
    alice_model = client.post(
        "/models", files={"file": ("alice.stl", io.BytesIO(b"fake"), "model/stl")}
    ).json()["model_id"]
    alice_job = client.post(
        "/jobs",
        json={"model_id": alice_model, "printer_profile": "Generic Printer", "process_profile": "0.20mm Standard"},
    ).json()["id"]

    client.post("/auth/users", json={"username": "bob", "password": "pw12345"})
    client.post("/auth/logout")
    client.post("/auth/login", json={"username": "bob", "password": "pw12345"})
    bob_model = client.post(
        "/models", files={"file": ("bob.stl", io.BytesIO(b"fake"), "model/stl")}
    ).json()["model_id"]
    bob_job = client.post(
        "/jobs",
        json={"model_id": bob_model, "printer_profile": "Generic Printer", "process_profile": "0.20mm Standard"},
    ).json()["id"]

    switched = client.post("/auth/switch-to-single")
    assert switched.status_code == 200
    assert switched.json() == {"mode": "single", "logged_in": True, "username": None}

    # No login prompt of any kind afterward, and both accounts' jobs survive
    # merged under the one implicit user.
    assert client.get("/auth/status").json() == {"mode": "single", "logged_in": True, "username": None}
    job_ids = {j["id"] for j in client.get("/jobs").json()}
    assert job_ids == {alice_job, bob_job}

    # The old accounts are gone -- logging in as either no longer means
    # anything (mode isn't multi anymore).
    assert client.post("/auth/login", json={"username": "alice", "password": "pw12345"}).status_code == 400
