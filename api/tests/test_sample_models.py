def test_list_sample_models(client):
    resp = client.get("/sample-models")
    assert resp.status_code == 200
    body = resp.json()
    ids = {s["id"] for s in body}
    assert {"benchy", "calibration-cube", "orca-badge", "orca-badge-colored", "stanford-bunny"} <= ids
    assert all({"id", "name", "description"} <= s.keys() for s in body)


def test_load_colored_sample_produces_a_real_color_tree(client):
    """orca-badge-colored is a real file (api/app/sample_assets/, not a
    test fixture) -- unlike the other samples in this test module, its
    /plates response should reflect genuine parsed color data, proving
    the file itself is wired correctly end to end."""
    resp = client.post("/sample-models/orca-badge-colored/load")
    assert resp.status_code == 200
    model_id = resp.json()["model_id"]

    plates = client.get(f"/models/{model_id}/plates")
    assert plates.status_code == 200
    body = plates.json()
    assert len(body["embedded_filament_colors"]) == 4
    assert len(body["color_tree"]) == 3  # 3 top-level composite objects, per the real badge structure
    # Every leaf color actually came from embedded_filament_colors.
    def all_colors(nodes):
        for n in nodes:
            if n["children"]:
                yield from all_colors(n["children"])
            elif n["color"]:
                yield n["color"]

    seen = set(all_colors(body["color_tree"]))
    assert seen
    assert seen <= set(body["embedded_filament_colors"])


def test_load_sample_model_creates_a_model_id(client, data_dirs):
    resp = client.post("/sample-models/benchy/load")
    assert resp.status_code == 200
    body = resp.json()
    assert body["filename"] == "3DBenchy.drc"
    model_id = body["model_id"]
    assert (data_dirs["models"] / f"{model_id}.drc").exists()


def test_load_sample_model_3mf_gets_plate_inspection(client):
    resp = client.post("/sample-models/orca-badge/load")
    model_id = resp.json()["model_id"]
    plates = client.get(f"/models/{model_id}/plates")
    assert plates.status_code == 200
    # Fixture content is a fake byte blob, not a real zip -- inspect_3mf
    # degrades gracefully to a single implicit plate, same as any corrupt
    # .3mf upload would.
    assert plates.json()["plates"] == [{"index": 1, "name": None, "object_count": None, "thumbnail": None}]


def test_load_unknown_sample_model_404s(client):
    resp = client.post("/sample-models/does-not-exist/load")
    assert resp.status_code == 404


def test_loaded_sample_model_is_downloadable(client):
    model_id = client.post("/sample-models/calibration-cube/load").json()["model_id"]
    resp = client.get(f"/models/{model_id}/file")
    assert resp.status_code == 200
    assert resp.content == b"fake sample model bytes"
    # A space in the filename makes Starlette use RFC 5987's percent-encoded
    # filename* form (filename*=utf-8''Calibration%20Cube.drc) rather than a
    # plain quoted filename="..." -- assert on the encoded name itself
    # rather than a specific prefix, which is Starlette-version-dependent.
    assert "Calibration%20Cube.drc" in resp.headers["content-disposition"]


def test_sample_model_is_owned_by_the_loading_user(client):
    client.post("/auth/setup", json={"mode": "multi", "username": "alice", "password": "pw12345"})
    model_id = client.post("/sample-models/benchy/load").json()["model_id"]

    client.post("/auth/users", json={"username": "bob", "password": "pw12345"})
    client.post("/auth/logout")
    client.post("/auth/login", json={"username": "bob", "password": "pw12345"})

    assert client.get(f"/models/{model_id}/file").status_code == 404
