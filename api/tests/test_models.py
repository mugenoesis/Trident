import io

from app.routers.models import resolve_model_original_name


def test_upload_rejects_unknown_extension(client):
    resp = client.post(
        "/models", files={"file": ("model.txt", io.BytesIO(b"not a model"), "text/plain")}
    )
    assert resp.status_code == 400


def test_upload_accepts_stl(client, data_dirs):
    resp = client.post(
        "/models", files={"file": ("cube.stl", io.BytesIO(b"fake stl bytes"), "model/stl")}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["filename"] == "cube.stl"
    model_id = body["model_id"]
    assert (data_dirs["models"] / f"{model_id}.stl").exists()
    assert resolve_model_original_name(model_id) == "cube.stl"


def test_resolve_model_original_name_missing_returns_none():
    assert resolve_model_original_name("no-such-model-id") is None
