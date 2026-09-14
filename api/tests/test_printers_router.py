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
