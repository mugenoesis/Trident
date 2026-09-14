from __future__ import annotations

import io

from app import printhost


def _printer_body(**overrides):
    body = dict(
        name="Living room A1",
        vendor="BBL",
        machine_profile="Bambu Lab A1 0.4 nozzle",
        process_profile="0.20mm Standard @BBL A1",
        filament_profile="Bambu PLA Basic @BBL A1",
        bed_width=256.0,
        bed_depth=256.0,
        bed_height=256.0,
    )
    body.update(overrides)
    return body


def test_create_list_delete_printer(client):
    created = client.post("/printers", json=_printer_body())
    assert created.status_code == 200
    printer_id = created.json()["id"]

    listed = client.get("/printers")
    assert listed.status_code == 200
    assert [p["id"] for p in listed.json()] == [printer_id]

    deleted = client.delete(f"/printers/{printer_id}")
    assert deleted.status_code == 200
    assert client.get("/printers").json() == []


def test_credentials_never_returned(client):
    created = client.post(
        "/printers",
        json=_printer_body(host_type="moonraker", print_host="http://printer.local", printhost_apikey="topsecret"),
    )
    body = created.json()
    assert body["has_credentials"] is True
    assert "topsecret" not in created.text
    assert "printhost_apikey" not in body


def test_material_profile_crud(client):
    printer_id = client.post("/printers", json=_printer_body()).json()["id"]

    created = client.post(
        f"/printers/{printer_id}/materials",
        json={
            "name": "PLA",
            "quick_settings": {"layer_height": "0.2"},
            "advanced_overrides": {},
        },
    )
    assert created.status_code == 200
    material_id = created.json()["id"]

    listed = client.get(f"/printers/{printer_id}/materials")
    assert [m["id"] for m in listed.json()] == [material_id]

    deleted = client.delete(f"/printers/{printer_id}/materials/{material_id}")
    assert deleted.status_code == 200
    assert client.get(f"/printers/{printer_id}/materials").json() == []


def _material_body(**overrides):
    body = dict(name="PLA", quick_settings={"layer_height": "0.2"}, advanced_overrides={})
    body.update(overrides)
    return body


def test_rename_material_profile(client):
    printer_id = client.post("/printers", json=_printer_body()).json()["id"]
    material_id = client.post(f"/printers/{printer_id}/materials", json=_material_body()).json()["id"]

    resp = client.put(f"/printers/{printer_id}/materials/{material_id}", json={"name": "PLA v2"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "PLA v2"
    assert body["quick_settings"] == {"layer_height": "0.2"}  # untouched


def test_update_mode_overwrites_material_settings(client):
    printer_id = client.post("/printers", json=_printer_body()).json()["id"]
    material_id = client.post(f"/printers/{printer_id}/materials", json=_material_body()).json()["id"]

    resp = client.put(
        f"/printers/{printer_id}/materials/{material_id}",
        json={"quick_settings": {"layer_height": "0.3"}, "advanced_overrides": {"x": "1"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "PLA"  # untouched
    assert body["quick_settings"] == {"layer_height": "0.3"}
    assert body["advanced_overrides"] == {"x": "1"}


def test_duplicate_material_profile(client):
    printer_id = client.post("/printers", json=_printer_body()).json()["id"]
    material_id = client.post(f"/printers/{printer_id}/materials", json=_material_body()).json()["id"]

    resp = client.post(f"/printers/{printer_id}/materials/{material_id}/duplicate")
    assert resp.status_code == 200
    dup = resp.json()
    assert dup["name"] == "PLA (2)"
    assert dup["id"] != material_id
    assert dup["quick_settings"] == {"layer_height": "0.2"}

    listed = client.get(f"/printers/{printer_id}/materials").json()
    assert {m["name"] for m in listed} == {"PLA", "PLA (2)"}


def test_material_actions_404_for_another_users_printer(client):
    client.post("/auth/setup", json={"mode": "multi", "username": "alice", "password": "pw12345"})
    printer_id = client.post("/printers", json=_printer_body()).json()["id"]
    material_id = client.post(f"/printers/{printer_id}/materials", json=_material_body()).json()["id"]

    client.post("/auth/users", json={"username": "bob", "password": "pw12345"})
    client.post("/auth/logout")
    client.post("/auth/login", json={"username": "bob", "password": "pw12345"})

    assert client.put(f"/printers/{printer_id}/materials/{material_id}", json={"name": "x"}).status_code == 404
    assert client.post(f"/printers/{printer_id}/materials/{material_id}/duplicate").status_code == 404


def test_ad_hoc_test_connection_success(client, monkeypatch):
    from app import printhost

    async def fake_test_connection(printer, **kwargs):
        assert printer["print_host"] == "http://printer.local"
        assert printer["printhost_apikey"] == "k123"
        return "Connected"

    monkeypatch.setattr(printhost, "test_connection", fake_test_connection)

    resp = client.post(
        "/printers/test-connection",
        json={"host_type": "moonraker", "print_host": "http://printer.local", "printhost_apikey": "k123"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"message": "Connected"}


def test_ad_hoc_test_connection_surfaces_error(client, monkeypatch):
    from app import printhost

    async def failing(*args, **kwargs):
        raise printhost.PrintHostError("no route to host")

    monkeypatch.setattr(printhost, "test_connection", failing)

    resp = client.post("/printers/test-connection", json={"host_type": "moonraker", "print_host": "http://x"})
    assert resp.status_code == 502
    assert "no route to host" in resp.json()["detail"]


def test_printers_isolated_between_users(client):
    client.post("/auth/setup", json={"mode": "multi", "username": "alice", "password": "pw12345"})
    client.post("/printers", json=_printer_body(name="Alice's printer"))

    client.post("/auth/users", json={"username": "bob", "password": "pw12345"})
    client.post("/auth/logout")
    client.post("/auth/login", json={"username": "bob", "password": "pw12345"})

    assert client.get("/printers").json() == []


def test_cannot_delete_or_view_another_users_printer(client):
    client.post("/auth/setup", json={"mode": "multi", "username": "alice", "password": "pw12345"})
    printer_id = client.post("/printers", json=_printer_body()).json()["id"]

    client.post("/auth/users", json={"username": "bob", "password": "pw12345"})
    client.post("/auth/logout")
    client.post("/auth/login", json={"username": "bob", "password": "pw12345"})

    assert client.get(f"/printers/{printer_id}/materials").status_code == 404
    assert client.delete(f"/printers/{printer_id}").status_code == 404


def test_update_printer_connection_fields(client):
    printer_id = client.post(
        "/printers", json=_printer_body(host_type="octoprint", print_host="http://old.local")
    ).json()["id"]

    resp = client.put(f"/printers/{printer_id}", json={"print_host": "http://new.local"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["print_host"] == "http://new.local"
    assert body["host_type"] == "octoprint"  # left alone
    assert body["name"] == "Living room A1"  # left alone


def test_update_printer_can_set_and_clear_credential(client):
    printer_id = client.post("/printers", json=_printer_body()).json()["id"]

    with_key = client.put(f"/printers/{printer_id}", json={"printhost_apikey": "newkey"})
    assert with_key.json()["has_credentials"] is True

    cleared = client.put(f"/printers/{printer_id}", json={"printhost_apikey": ""})
    assert cleared.json()["has_credentials"] is False


def test_update_another_users_printer_404s(client):
    client.post("/auth/setup", json={"mode": "multi", "username": "alice", "password": "pw12345"})
    printer_id = client.post("/printers", json=_printer_body()).json()["id"]

    client.post("/auth/users", json={"username": "bob", "password": "pw12345"})
    client.post("/auth/logout")
    client.post("/auth/login", json={"username": "bob", "password": "pw12345"})

    resp = client.put(f"/printers/{printer_id}", json={"name": "Hijacked"})
    assert resp.status_code == 404


def test_test_connection_success(client, monkeypatch):
    from app import printhost

    printer_id = client.post(
        "/printers", json=_printer_body(host_type="moonraker", print_host="http://printer.local")
    ).json()["id"]

    async def fake_test_connection(printer, **kwargs):
        assert printer["print_host"] == "http://printer.local"
        return "Connected (Klipper state: ready)"

    monkeypatch.setattr(printhost, "test_connection", fake_test_connection)

    resp = client.post(f"/printers/{printer_id}/test-connection")
    assert resp.status_code == 200
    assert resp.json() == {"message": "Connected (Klipper state: ready)"}


def test_test_connection_surfaces_error(client, monkeypatch):
    from app import printhost

    printer_id = client.post(
        "/printers", json=_printer_body(host_type="moonraker", print_host="http://printer.local")
    ).json()["id"]

    async def failing_test_connection(*args, **kwargs):
        raise printhost.PrintHostError("connection refused")

    monkeypatch.setattr(printhost, "test_connection", failing_test_connection)

    resp = client.post(f"/printers/{printer_id}/test-connection")
    assert resp.status_code == 502
    assert "connection refused" in resp.json()["detail"]


def _sliced_job(client, monkeypatch) -> str:
    from app import cli_runner
    from app.cli_runner import SliceResult

    def fake_run_slice(**kwargs):
        output_dir = kwargs["output_dir"]
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "plate_1.gcode").write_text("; fake\n")
        return SliceResult(
            return_code=0, result_json={"return_code": 0}, stdout="", stderr="", used_result_json=True
        )

    monkeypatch.setattr(cli_runner, "run_slice", fake_run_slice)
    model_id = client.post(
        "/models", files={"file": ("cube.stl", io.BytesIO(b"fake"), "model/stl")}
    ).json()["model_id"]
    job_resp = client.post(
        "/jobs", json={"model_id": model_id, "printer_profile": "p", "process_profile": "q"}
    )
    return job_resp.json()["id"]


def test_send_to_printer_success(client, monkeypatch):
    printer_id = client.post(
        "/printers",
        json=_printer_body(host_type="moonraker", print_host="http://printer.local", printhost_apikey="k"),
    ).json()["id"]
    job_id = _sliced_job(client, monkeypatch)

    async def fake_send_gcode(printer, gcode_path, start_print, **kwargs):
        assert printer["print_host"] == "http://printer.local"
        assert gcode_path.name == "plate_1.gcode"
        assert start_print is False

    monkeypatch.setattr(printhost, "send_gcode", fake_send_gcode)

    resp = client.post(f"/printers/{printer_id}/send/{job_id}", json={})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_send_to_printer_surfaces_printhost_error(client, monkeypatch):
    printer_id = client.post(
        "/printers", json=_printer_body(host_type="moonraker", print_host="http://printer.local")
    ).json()["id"]
    job_id = _sliced_job(client, monkeypatch)

    async def failing_send_gcode(*args, **kwargs):
        raise printhost.PrintHostError("printer is off")

    monkeypatch.setattr(printhost, "send_gcode", failing_send_gcode)

    resp = client.post(f"/printers/{printer_id}/send/{job_id}", json={})
    assert resp.status_code == 502
    assert "printer is off" in resp.json()["detail"]


def test_send_to_printer_404s_for_unowned_job(client, monkeypatch):
    client.post("/auth/setup", json={"mode": "multi", "username": "alice", "password": "pw12345"})
    printer_id = client.post("/printers", json=_printer_body()).json()["id"]
    job_id = _sliced_job(client, monkeypatch)

    client.post("/auth/users", json={"username": "bob", "password": "pw12345"})
    client.post("/auth/logout")
    client.post("/auth/login", json={"username": "bob", "password": "pw12345"})

    resp = client.post(f"/printers/{printer_id}/send/{job_id}", json={})
    assert resp.status_code == 404
