def test_source_endpoint(client):
    resp = client.get("/source")
    assert resp.status_code == 200
    body = resp.json()
    assert body["license"] == "AGPL-3.0"
    assert "orcaslicer_fork_url" in body
    assert "wrapper_repo_url" in body


def test_version_endpoint(client):
    resp = client.get("/version")
    assert resp.status_code == 200
    assert "orcaslicer_commit_sha" in resp.json()


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_source_header_present_on_every_response(client):
    resp = client.get("/healthz")
    assert resp.headers["x-source-available-at"] == "/source"
