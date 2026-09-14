from __future__ import annotations


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
