from __future__ import annotations

import io

import pytest

from app import bambu_link, printhost


def _printer_body(**overrides):
    body = {
        "name": "Living room A1",
        "vendor": "BBL",
        "machine_profile": "Bambu Lab A1 0.4 nozzle",
        "process_profile": "0.20mm Standard @BBL A1",
        "filament_profiles": ["Bambu PLA Basic @BBL A1"],
        "filament_colors": ["#ffffff"],
        "bed_width": 256.0,
        "bed_depth": 256.0,
        "bed_height": 256.0,
    }
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


def test_create_printer_with_multiple_filament_slots(client):
    created = client.post(
        "/printers",
        json=_printer_body(
            vendor="Snapmaker",
            machine_profile="Snapmaker U1 (0.4+0.6 nozzle)",
            filament_profiles=["Generic PLA", "Generic PETG"],
            filament_colors=["#ff0000", "#0000ff"],
        ),
    )
    assert created.status_code == 200
    body = created.json()
    assert body["filament_profiles"] == ["Generic PLA", "Generic PETG"]
    assert body["filament_colors"] == ["#ff0000", "#0000ff"]


def test_material_profile_crud(client):
    printer_id = client.post("/printers", json=_printer_body()).json()["id"]

    created = client.post(
        f"/printers/{printer_id}/materials",
        json={"name": "PLA", "filament_profiles": ["Generic PLA"], "filament_colors": ["#ffffff"]},
    )
    assert created.status_code == 200
    material_id = created.json()["id"]

    listed = client.get(f"/printers/{printer_id}/materials")
    assert [m["id"] for m in listed.json()] == [material_id]

    deleted = client.delete(f"/printers/{printer_id}/materials/{material_id}")
    assert deleted.status_code == 200
    assert client.get(f"/printers/{printer_id}/materials").json() == []


def _material_body(**overrides):
    body = {"name": "PLA", "filament_profiles": ["Generic PLA"], "filament_colors": ["#ffffff"]}
    body.update(overrides)
    return body


def test_rename_material_profile(client):
    printer_id = client.post("/printers", json=_printer_body()).json()["id"]
    material_id = client.post(f"/printers/{printer_id}/materials", json=_material_body()).json()["id"]

    resp = client.put(f"/printers/{printer_id}/materials/{material_id}", json={"name": "PLA v2"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "PLA v2"
    assert body["filament_profiles"] == ["Generic PLA"]  # untouched


def test_update_material_filament_slots(client):
    printer_id = client.post("/printers", json=_printer_body()).json()["id"]
    material_id = client.post(f"/printers/{printer_id}/materials", json=_material_body()).json()["id"]

    resp = client.put(
        f"/printers/{printer_id}/materials/{material_id}",
        json={"filament_profiles": ["A", "B"], "filament_colors": ["#111111", "#222222"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["filament_profiles"] == ["A", "B"]
    assert body["filament_colors"] == ["#111111", "#222222"]


def test_duplicate_material_profile(client):
    printer_id = client.post("/printers", json=_printer_body()).json()["id"]
    material_id = client.post(f"/printers/{printer_id}/materials", json=_material_body()).json()["id"]

    resp = client.post(f"/printers/{printer_id}/materials/{material_id}/duplicate")
    assert resp.status_code == 200
    dup = resp.json()
    assert dup["name"] == "PLA (2)"
    assert dup["id"] != material_id
    assert dup["filament_profiles"] == ["Generic PLA"]

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


def _settings_profile_body(**overrides):
    body = {"name": "Standard", "quick_settings": {"layer_height": "0.2"}, "advanced_overrides": {}}
    body.update(overrides)
    return body


def test_settings_profile_crud(client):
    printer_id = client.post("/printers", json=_printer_body()).json()["id"]

    created = client.post(f"/printers/{printer_id}/settings-profiles", json=_settings_profile_body())
    assert created.status_code == 200
    profile_id = created.json()["id"]

    listed = client.get(f"/printers/{printer_id}/settings-profiles")
    assert [p["id"] for p in listed.json()] == [profile_id]

    deleted = client.delete(f"/printers/{printer_id}/settings-profiles/{profile_id}")
    assert deleted.status_code == 200
    assert client.get(f"/printers/{printer_id}/settings-profiles").json() == []


def test_rename_settings_profile(client):
    printer_id = client.post("/printers", json=_printer_body()).json()["id"]
    profile_id = client.post(f"/printers/{printer_id}/settings-profiles", json=_settings_profile_body()).json()["id"]

    resp = client.put(f"/printers/{printer_id}/settings-profiles/{profile_id}", json={"name": "Standard v2"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Standard v2"
    assert body["quick_settings"] == {"layer_height": "0.2"}  # untouched


def test_update_mode_overwrites_settings_profile(client):
    printer_id = client.post("/printers", json=_printer_body()).json()["id"]
    profile_id = client.post(f"/printers/{printer_id}/settings-profiles", json=_settings_profile_body()).json()["id"]

    resp = client.put(
        f"/printers/{printer_id}/settings-profiles/{profile_id}",
        json={"quick_settings": {"layer_height": "0.3"}, "advanced_overrides": {"x": "1"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Standard"  # untouched
    assert body["quick_settings"] == {"layer_height": "0.3"}
    assert body["advanced_overrides"] == {"x": "1"}


def test_duplicate_settings_profile(client):
    printer_id = client.post("/printers", json=_printer_body()).json()["id"]
    profile_id = client.post(f"/printers/{printer_id}/settings-profiles", json=_settings_profile_body()).json()["id"]

    resp = client.post(f"/printers/{printer_id}/settings-profiles/{profile_id}/duplicate")
    assert resp.status_code == 200
    dup = resp.json()
    assert dup["name"] == "Standard (2)"
    assert dup["id"] != profile_id
    assert dup["quick_settings"] == {"layer_height": "0.2"}

    listed = client.get(f"/printers/{printer_id}/settings-profiles").json()
    assert {p["name"] for p in listed} == {"Standard", "Standard (2)"}


def test_settings_profile_actions_404_for_another_users_printer(client):
    client.post("/auth/setup", json={"mode": "multi", "username": "alice", "password": "pw12345"})
    printer_id = client.post("/printers", json=_printer_body()).json()["id"]
    profile_id = client.post(f"/printers/{printer_id}/settings-profiles", json=_settings_profile_body()).json()["id"]

    client.post("/auth/users", json={"username": "bob", "password": "pw12345"})
    client.post("/auth/logout")
    client.post("/auth/login", json={"username": "bob", "password": "pw12345"})

    assert client.put(f"/printers/{printer_id}/settings-profiles/{profile_id}", json={"name": "x"}).status_code == 404
    assert client.post(f"/printers/{printer_id}/settings-profiles/{profile_id}/duplicate").status_code == 404
    assert client.get(f"/printers/{printer_id}/settings-profiles").status_code == 404


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
        return SliceResult(return_code=0, result_json={"return_code": 0}, stdout="", stderr="", used_result_json=True)

    monkeypatch.setattr(cli_runner, "run_slice", fake_run_slice)
    model_id = client.post("/models", files={"file": ("cube.stl", io.BytesIO(b"fake"), "model/stl")}).json()["model_id"]
    job_resp = client.post("/jobs", json={"model_id": model_id, "printer_profile": "p", "process_profile": "q"})
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


# ---- import a printer from a Klipper printer's own config ----

_KLIPPER_SNAPSHOT = {
    "info": {"state": "ready", "hostname": "voron", "software_version": "v0.12.0"},
    "settings": {
        "printer": {"kinematics": "cartesian", "max_velocity": 300, "max_accel": 3000},
        "stepper_x": {"position_min": 0, "position_max": 235},
        "stepper_y": {"position_min": 0, "position_max": 230},
        "stepper_z": {"position_min": 0, "position_max": 250},
        "extruder": {"nozzle_diameter": 0.4},
    },
    "objects": ["extruder"],
}


def test_klipper_import_answers_a_filled_in_printer_form(client, monkeypatch):
    seen = {}

    async def fake_read(printer, **kwargs):
        seen.update(printer)
        return _KLIPPER_SNAPSHOT

    monkeypatch.setattr(printhost, "read_klipper", fake_read)
    response = client.post(
        "/printers/klipper-import", json={"print_host": "http://voron.local", "printhost_apikey": "topsecret"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["form"]["name"] == "voron"
    assert (body["form"]["width"], body["form"]["depth"], body["form"]["height"]) == (235, 230, 250)
    assert body["findings"] and body["klipper"]["hostname"] == "voron"
    # it is asked as a Klipper printer, with the address and key as given, and the key never comes back
    assert (
        seen["host_type"] == "moonraker"
        and seen["print_host"] == "http://voron.local"
        and seen["printhost_apikey"] == "topsecret"
    )
    assert "topsecret" not in response.text


def test_klipper_import_says_why_the_printer_could_not_be_read(client, monkeypatch):
    async def failing(*args, **kwargs):
        raise printhost.PrintHostError("Couldn't reach the printer: refused")

    monkeypatch.setattr(printhost, "read_klipper", failing)
    response = client.post("/printers/klipper-import", json={"print_host": "http://voron.local"})
    assert response.status_code == 502
    assert "Couldn't reach the printer" in response.json()["detail"]


def test_klipper_import_says_why_a_config_cannot_be_used(client, monkeypatch):
    async def polar(*args, **kwargs):
        return {"info": {"state": "ready"}, "settings": {"printer": {"kinematics": "polar"}}, "objects": []}

    monkeypatch.setattr(printhost, "read_klipper", polar)
    response = client.post("/printers/klipper-import", json={"print_host": "http://voron.local"})
    assert response.status_code == 422
    assert "polar" in response.json()["detail"]


def test_klipper_import_needs_an_address(client):
    assert client.post("/printers/klipper-import", json={}).status_code == 422


# ---- the live printer page: status, controls, webcams ----


def _klipper_printer(client):
    body = _printer_body(
        name="Voron", host_type="moonraker", print_host="http://voron.local", printhost_apikey="topsecret"
    )
    return client.post("/printers", json=body).json()["id"]


def test_status_is_the_printers_state_in_a_form_the_page_can_show(client, monkeypatch):
    printer_id = _klipper_printer(client)
    asked = {}

    async def fake_read(printer, **kwargs):
        asked.update(printer)
        return {
            "print_stats": {"state": "printing", "filename": "part.gcode", "print_duration": 600},
            "virtual_sdcard": {"progress": 0.25},
        }

    monkeypatch.setattr(printhost, "read_status", fake_read)
    response = client.get(f"/printers/{printer_id}/status")
    assert response.status_code == 200
    body = response.json()
    assert (body["state"], body["file"], body["progress"], body["remaining_s"]) == (
        "printing",
        "part.gcode",
        0.25,
        1800,
    )
    assert body["can"]["pause"] is True
    assert asked["print_host"] == "http://voron.local" and asked["printhost_apikey"] == "topsecret"
    assert "topsecret" not in response.text


def test_status_of_a_printer_that_cannot_be_reached_is_a_502_with_the_reason(client, monkeypatch):
    printer_id = _klipper_printer(client)

    async def failing(*args, **kwargs):
        raise printhost.PrintHostError("Couldn't reach the printer: refused")

    monkeypatch.setattr(printhost, "read_status", failing)
    response = client.get(f"/printers/{printer_id}/status")
    assert response.status_code == 502
    assert "reach" in response.json()["detail"]


def test_status_of_a_printer_that_is_not_a_known_printer_is_a_404(client):
    assert client.get("/printers/nope/status").status_code == 404


def test_a_printer_with_no_klipper_connection_has_no_status(client):
    printer_id = client.post("/printers", json=_printer_body()).json()["id"]
    response = client.get(f"/printers/{printer_id}/status")
    assert response.status_code == 400
    assert "Klipper" in response.json()["detail"]


@pytest.mark.parametrize("action", ["pause", "resume", "cancel"])
def test_pause_resume_and_cancel_are_passed_to_the_printer(client, monkeypatch, action):
    printer_id = _klipper_printer(client)
    done = []

    async def fake_control(printer, what, **kwargs):
        done.append(what)

    monkeypatch.setattr(printhost, "print_control", fake_control)
    response = client.post(f"/printers/{printer_id}/print/{action}")
    assert response.status_code == 200 and response.json() == {"ok": True}
    assert done == [action]


def test_nothing_else_can_be_asked_of_the_printer_through_it(client, monkeypatch):
    printer_id = _klipper_printer(client)
    monkeypatch.setattr(
        printhost, "print_control", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called"))
    )
    assert client.post(f"/printers/{printer_id}/print/emergency_stop").status_code == 422


def test_a_refusal_by_the_printer_is_a_502_in_its_words(client, monkeypatch):
    printer_id = _klipper_printer(client)

    async def refusing(*args, **kwargs):
        raise printhost.PrintHostError("Klippy Disconnected")

    monkeypatch.setattr(printhost, "print_control", refusing)
    response = client.post(f"/printers/{printer_id}/print/pause")
    assert response.status_code == 502 and "Klippy Disconnected" in response.json()["detail"]


def test_the_webcams_are_listed_by_name_without_their_addresses(client, monkeypatch):
    printer_id = _klipper_printer(client)

    async def fake_list(printer, **kwargs):
        return [{"name": "tool", "snapshot_url": "http://voron.local/snap", "stream_url": "http://voron.local/stream"}]

    monkeypatch.setattr(printhost, "webcam_list", fake_list)
    response = client.get(f"/printers/{printer_id}/webcams")
    assert response.status_code == 200
    assert response.json() == [{"index": 0, "name": "tool"}]


def test_a_webcam_snapshot_is_the_picture(client, monkeypatch):
    printer_id = _klipper_printer(client)

    async def fake_snapshot(printer, index, **kwargs):
        return b"\xff\xd8jpeg", "image/jpeg"

    monkeypatch.setattr(printhost, "webcam_snapshot", fake_snapshot)
    response = client.get(f"/printers/{printer_id}/webcams/0/snapshot")
    assert response.status_code == 200
    assert response.content == b"\xff\xd8jpeg"
    assert response.headers["content-type"] == "image/jpeg"
    assert "no-store" in response.headers["cache-control"]


def test_a_webcam_that_is_not_there_is_a_404(client, monkeypatch):
    printer_id = _klipper_printer(client)

    async def missing(printer, index, **kwargs):
        raise printhost.NoSuchCamera("There is no camera 3 on this printer")

    monkeypatch.setattr(printhost, "webcam_snapshot", missing)
    assert client.get(f"/printers/{printer_id}/webcams/3/snapshot").status_code == 404


# ---- Bambu printers (LAN / Developer mode) ----

SERIAL = "00M00A000000000"


def _bambu_printer(client, **overrides):
    body = _printer_body(
        name="X1C",
        host_type="bambu",
        print_host="192.168.1.50",
        printhost_apikey="12345678",
        device_id=SERIAL,
        **overrides,
    )
    return client.post("/printers", json=body).json()


def test_a_bambu_printer_is_saved_with_its_serial_number_and_the_access_code_never_comes_back(client):
    created = client.post(
        "/printers",
        json=_printer_body(host_type="bambu", print_host="192.168.1.50", printhost_apikey="12345678", device_id=SERIAL),
    )
    body = created.json()
    assert body["device_id"] == SERIAL and body["host_type"] == "bambu" and body["has_credentials"] is True
    assert "12345678" not in created.text
    assert client.get("/printers").json()[0]["device_id"] == SERIAL


def test_the_serial_number_can_be_edited_with_the_connection(client):
    printer = _bambu_printer(client)
    updated = client.put(f"/printers/{printer['id']}", json={"device_id": "01P00A000000000"})
    assert updated.status_code == 200 and updated.json()["device_id"] == "01P00A000000000"


def test_status_of_a_bambu_printer_is_made_from_its_report(client, monkeypatch):
    printer = _bambu_printer(client)
    asked = {}

    async def fake_report(row):
        asked.update({k: row[k] for k in ("print_host", "device_id", "printhost_apikey")})
        return {
            "gcode_state": "RUNNING",
            "subtask_name": "benchy",
            "mc_percent": 42,
            "mc_remaining_time": 98,
            "chamber_temper": 30,
            "nozzle_temper": 200,
        }

    monkeypatch.setattr(bambu_link, "read_report", fake_report)
    response = client.get(f"/printers/{printer['id']}/status")
    assert response.status_code == 200
    body = response.json()
    assert (body["state"], body["file"], body["progress"], body["remaining_s"]) == ("printing", "benchy", 0.42, 5880)
    assert [t["name"] for t in body["temperatures"]] == ["Nozzle", "Chamber"]  # an X1's serial number: it has a chamber
    assert asked == {"print_host": "192.168.1.50", "device_id": SERIAL, "printhost_apikey": "12345678"}
    assert "12345678" not in response.text


def test_a_bambu_printer_that_cannot_be_reached_is_a_502_in_the_links_words(client, monkeypatch):
    printer = _bambu_printer(client)

    async def failing(row):
        raise bambu_link.BambuError("The printer refused the access code")

    monkeypatch.setattr(bambu_link, "read_report", failing)
    response = client.get(f"/printers/{printer['id']}/status")
    assert response.status_code == 502 and "access code" in response.json()["detail"]


def test_a_bambu_printer_with_no_serial_number_cannot_have_a_status(client):
    body = _printer_body(host_type="bambu", print_host="192.168.1.50", printhost_apikey="12345678")
    printer = client.post("/printers", json=body).json()
    response = client.get(f"/printers/{printer['id']}/status")
    assert response.status_code == 400 and "serial number" in response.json()["detail"]


@pytest.mark.parametrize("action", ["pause", "resume", "cancel"])
def test_pause_resume_and_cancel_go_to_a_bambu_printer(client, monkeypatch, action):
    printer = _bambu_printer(client)
    done = []

    async def fake_control(row, what):
        done.append(what)

    monkeypatch.setattr(bambu_link, "control", fake_control)
    assert client.post(f"/printers/{printer['id']}/print/{action}").json() == {"ok": True}
    assert done == [action]


def test_a_bambu_printer_has_no_webcams_listed_yet(client):
    printer = _bambu_printer(client)
    assert client.get(f"/printers/{printer['id']}/webcams").json() == []


def test_testing_a_bambu_connection_connects_to_the_printer(client, monkeypatch):
    asked = {}

    async def fake_check(host, serial, code):
        asked.update(host=host, serial=serial, code=code)
        return "Connected (printer state: standby)"

    monkeypatch.setattr(bambu_link, "check_connection", fake_check)
    response = client.post(
        "/printers/test-connection",
        json={"host_type": "bambu", "print_host": "192.168.1.50", "printhost_apikey": "12345678", "device_id": SERIAL},
    )
    assert response.status_code == 200 and "Connected" in response.json()["message"]
    assert asked == {"host": "192.168.1.50", "serial": SERIAL, "code": "12345678"}


def test_testing_a_saved_bambu_printers_connection_uses_what_is_saved(client, monkeypatch):
    printer = _bambu_printer(client)
    asked = {}

    async def fake_check(host, serial, code):
        asked.update(host=host, serial=serial, code=code)
        return "Connected"

    monkeypatch.setattr(bambu_link, "check_connection", fake_check)
    assert client.post(f"/printers/{printer['id']}/test-connection").status_code == 200
    assert asked == {"host": "192.168.1.50", "serial": SERIAL, "code": "12345678"}


def test_a_failed_bambu_connection_test_is_a_502(client, monkeypatch):
    async def failing(host, serial, code):
        raise bambu_link.BambuError("Couldn't reach the printer: timed out")

    monkeypatch.setattr(bambu_link, "check_connection", failing)
    response = client.post(
        "/printers/test-connection",
        json={"host_type": "bambu", "print_host": "192.168.1.50", "printhost_apikey": "x", "device_id": SERIAL},
    )
    assert response.status_code == 502 and "reach" in response.json()["detail"]
