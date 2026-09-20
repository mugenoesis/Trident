import io
import zipfile

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


def test_get_model_file_returns_original_bytes(client):
    model_id = client.post(
        "/models", files={"file": ("cube.stl", io.BytesIO(b"fake stl bytes"), "model/stl")}
    ).json()["model_id"]

    resp = client.get(f"/models/{model_id}/file")
    assert resp.status_code == 200
    assert resp.content == b"fake stl bytes"
    assert 'filename="cube.stl"' in resp.headers["content-disposition"]


def test_get_model_file_404s_for_unknown_model(client):
    assert client.get("/models/does-not-exist/file").status_code == 404


def test_plates_endpoint_synthetic_single_plate_for_non_3mf(client):
    model_id = client.post(
        "/models", files={"file": ("cube.stl", io.BytesIO(b"fake stl bytes"), "model/stl")}
    ).json()["model_id"]

    resp = client.get(f"/models/{model_id}/plates")
    assert resp.status_code == 200
    body = resp.json()
    assert body["plates"] == [{"index": 1, "name": None, "object_count": None, "thumbnail": None}]
    assert body["extruder_indices"] == []


def _build_multiplate_3mf() -> bytes:
    buf = io.BytesIO()
    xml = """
    <config>
      <object id="1"><metadata key="extruder" value="1"/></object>
      <object id="2"><metadata key="extruder" value="2"/></object>
      <plate>
        <metadata key="plater_id" value="1"/>
        <metadata key="plater_name" value="Plate A"/>
        <model_instance><metadata key="object_id" value="1"/></model_instance>
      </plate>
      <plate>
        <metadata key="plater_id" value="2"/>
        <metadata key="plater_name" value="Plate B"/>
        <model_instance><metadata key="object_id" value="2"/></model_instance>
      </plate>
    </config>
    """
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("3D/3dmodel.model", "<model/>")
        zf.writestr("Metadata/model_settings.config", xml)
    return buf.getvalue()


def test_plates_endpoint_parses_multiplate_3mf(client):
    model_id = client.post(
        "/models", files={"file": ("project.3mf", io.BytesIO(_build_multiplate_3mf()), "model/3mf")}
    ).json()["model_id"]

    resp = client.get(f"/models/{model_id}/plates")
    assert resp.status_code == 200
    body = resp.json()
    assert [p["index"] for p in body["plates"]] == [1, 2]
    assert [p["name"] for p in body["plates"]] == ["Plate A", "Plate B"]
    assert body["extruder_indices"] == [1, 2]


def test_plates_endpoint_404s_for_unknown_model(client):
    assert client.get("/models/does-not-exist/plates").status_code == 404
