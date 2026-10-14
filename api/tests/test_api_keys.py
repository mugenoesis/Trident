"""API keys: another program (Holecraft, a script) uses this Trident without a login.

A key is made while signed in (or in single-user mode), shown once, stored only as a hash, and sent as
`Authorization: Bearer <key>`. Two kinds: `upload` (may only upload a model) and `full` (every API except
managing keys).
"""

from __future__ import annotations

import io

import pytest

from app.routers.models import resolve_model_owner
from app.userstore import store as user_store


def _model(name: str = "cube.stl") -> dict:
    return {"file": (name, io.BytesIO(b"fake stl bytes"), "model/stl")}


def _bearer(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def _make(client, name: str = "Holecraft", scope: str = "upload") -> dict:
    resp = client.post("/auth/keys", json={"name": name, "scope": scope})
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture()
def single(client):
    """Single-user mode: nothing to log into."""
    client.post("/auth/setup", json={"mode": "single"})
    return client


@pytest.fixture()
def multi(client):
    """Multi-user mode with alice signed in (her session cookie is in the client)."""
    client.post("/auth/setup", json={"mode": "multi", "username": "alice", "password": "pw12345"})
    return client


def _anonymous(client):
    """The same app with no session cookie, as a program using a key would be."""
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def test_making_a_key_shows_it_once_and_lists_it_without_the_secret(single):
    made = _make(single)
    assert made["key"].startswith("trident_")
    assert len(made["key"]) >= 40
    assert made["name"] == "Holecraft"
    assert made["scope"] == "upload"
    listed = single.get("/auth/keys").json()
    assert [k["id"] for k in listed] == [made["id"]]
    assert "key" not in listed[0]
    assert listed[0]["last_used_at"] is None


def test_the_secret_is_not_stored(single):
    made = _make(single)
    assert made["key"] not in repr(user_store.list_api_keys(user_store.get_or_create_local_user().id))
    import sqlite3

    with sqlite3.connect(user_store._db_path) as conn:
        dump = " ".join(str(c) for row in conn.execute("SELECT * FROM api_keys") for c in row)
    assert made["key"] not in dump


def test_two_keys_get_different_secrets(single):
    assert _make(single)["key"] != _make(single, "Second")["key"]


@pytest.mark.parametrize(
    "body",
    [
        {"name": "", "scope": "upload"},
        {"name": "x" * 61, "scope": "upload"},
        {"name": "ok", "scope": "root"},
        {"scope": "upload"},
    ],
)
def test_a_key_needs_a_name_and_a_known_access(single, body):
    assert single.post("/auth/keys", json=body).status_code in (400, 422)


def test_an_upload_key_uploads_a_model_owned_by_its_user_without_a_login(multi):
    key = _make(multi)["key"]
    alice = user_store.get_user_by_username("alice")[0].id  # type: ignore[index]
    resp = _anonymous(multi).post("/models", files=_model(), headers=_bearer(key))
    assert resp.status_code == 200, resp.text
    assert resolve_model_owner(resp.json()["model_id"]) == alice


def test_an_upload_key_can_do_nothing_else(multi):
    key = _make(multi)["key"]
    anon = _anonymous(multi)
    assert anon.get("/jobs", headers=_bearer(key)).status_code == 403
    assert anon.get("/printers", headers=_bearer(key)).status_code == 403
    assert anon.post("/auth/keys", json={"name": "x", "scope": "full"}, headers=_bearer(key)).status_code in (401, 403)


def test_a_full_key_uses_the_other_apis_but_cannot_manage_keys(multi):
    key = _make(multi, "Script", "full")["key"]
    anon = _anonymous(multi)
    assert anon.get("/jobs", headers=_bearer(key)).status_code == 200
    assert anon.post("/models", files=_model(), headers=_bearer(key)).status_code == 200
    assert anon.post("/auth/keys", json={"name": "x", "scope": "full"}, headers=_bearer(key)).status_code in (401, 403)
    assert anon.get("/auth/keys", headers=_bearer(key)).status_code in (401, 403)


def test_without_a_login_or_a_key_a_multi_user_server_still_says_no(multi):
    assert _anonymous(multi).post("/models", files=_model()).status_code == 401


def test_a_wrong_key_is_refused_even_when_nothing_needs_a_login(single):
    # a mistyped key should say so, not be silently ignored
    assert single.post("/models", files=_model(), headers=_bearer("trident_notarealkey")).status_code == 401
    assert single.post("/models", files=_model(), headers={"Authorization": "Bearer "}).status_code == 401


def test_with_no_login_a_key_is_not_needed(single):
    assert single.post("/models", files=_model()).status_code == 200


def test_a_revoked_key_stops_working_at_once(multi):
    made = _make(multi)
    anon = _anonymous(multi)
    assert anon.post("/models", files=_model(), headers=_bearer(made["key"])).status_code == 200
    assert multi.delete(f"/auth/keys/{made['id']}").status_code == 200
    assert anon.post("/models", files=_model(), headers=_bearer(made["key"])).status_code == 401
    assert multi.get("/auth/keys").json() == []


def test_using_a_key_records_when(multi):
    made = _make(multi)
    _anonymous(multi).post("/models", files=_model(), headers=_bearer(made["key"]))
    assert multi.get("/auth/keys").json()[0]["last_used_at"] is not None


def test_you_only_see_and_revoke_your_own_keys(client):
    client.post("/auth/setup", json={"mode": "multi", "username": "alice", "password": "pw12345"})
    mine = _make(client)
    client.post("/auth/users", json={"username": "bob", "password": "pw54321"})
    client.post("/auth/login", json={"username": "bob", "password": "pw54321"})
    assert client.get("/auth/keys").json() == []
    assert client.delete(f"/auth/keys/{mine['id']}").status_code == 404
    client.post("/auth/login", json={"username": "alice", "password": "pw12345"})
    assert [k["id"] for k in client.get("/auth/keys").json()] == [mine["id"]]


def test_revoking_an_unknown_key_is_a_404(single):
    assert single.delete("/auth/keys/nope").status_code == 404


def test_keys_must_be_managed_from_a_login_in_multi_user_mode(multi):
    assert _anonymous(multi).get("/auth/keys").status_code == 401
    assert _anonymous(multi).post("/auth/keys", json={"name": "x", "scope": "upload"}).status_code == 401


def test_keys_survive_switching_back_to_single_user(multi):
    made = _make(multi)
    assert multi.post("/auth/switch-to-single").status_code == 200
    assert [k["id"] for k in multi.get("/auth/keys").json()] == [made["id"]]
    assert multi.post("/models", files=_model(), headers=_bearer(made["key"])).status_code == 200


def test_an_uploaded_model_can_be_looked_up_again_by_its_owner(multi):
    key = _make(multi)["key"]
    uploaded = _anonymous(multi).post("/models", files=_model("cube.stl"), headers=_bearer(key)).json()
    again = multi.get(f"/models/{uploaded['model_id']}")
    assert again.status_code == 200
    assert again.json()["model_id"] == uploaded["model_id"]
    assert again.json()["filename"] == "cube.stl"


def test_someone_elses_model_is_not_found(client):
    client.post("/auth/setup", json={"mode": "multi", "username": "alice", "password": "pw12345"})
    model_id = client.post("/models", files=_model()).json()["model_id"]
    client.post("/auth/users", json={"username": "bob", "password": "pw54321"})
    client.post("/auth/login", json={"username": "bob", "password": "pw54321"})
    assert client.get(f"/models/{model_id}").status_code == 404
    assert client.get("/models/no-such-model").status_code == 404
