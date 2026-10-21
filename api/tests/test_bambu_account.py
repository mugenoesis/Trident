"""Listing the printers of a Bambu account and adding them as saved printers (POST /bambu-cloud/account and /bambu-cloud/import).

The helper program is a shell script that prints what the plug-in would, the network search and the printer catalogue are replaced, and
what is checked is what the browser is told (never a serial number or an access code), what is saved, and what is refused.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

from app import bambu_discovery, profiles
from app.printerstore import store

PASTED = "http://localhost:41999/?access_token=AAA&refresh_token=RRR&expires_in=7776000&refresh_expires_in=7776000"
X1C = {"serial": "00M00A000000000", "code": "12345678", "model": "X1 Carbon", "name": "Shed", "online": True}
P1S = {"serial": "01P00A000000000", "code": "87654321", "model": "P1S", "name": "Desk", "online": False}
ODD = {"serial": "09X00A000000000", "code": "11223344", "model": "Mystery Printer", "name": "Odd", "online": True}


def _steps(devices: list[dict]) -> list[dict]:
    raw = [
        {
            "dev_id": d["serial"],
            "dev_access_code": d["code"],
            "dev_name": d["name"],
            "dev_online": d["online"],
            "dev_product_name": d["model"],
            "dev_model_name": "X",
        }
        for d in devices
    ]
    return [
        {"step": "get_my_profile", "value": {"http_code": 200, "result": 0}},
        {"step": "is_user_login", "value": True},
        {"step": "user_name", "value": "maker"},
        {"step": "account_devices", "value": raw},
    ]


def _helper(tmp_path: Path, steps: list[dict]) -> Path:
    script = tmp_path / "helper"
    script.write_text("#!/bin/sh\ncat > /dev/null\n" + "".join(f"echo '{json.dumps(s)}'\n" for s in steps))
    script.chmod(0o755)
    return script


class FakeCatalog:
    machines: ClassVar[dict[str, dict]] = {
        "Bambu Lab X1 Carbon 0.4 nozzle": {
            "default_print_profile": "0.20mm Standard @BBL X1C",
            "default_filament_profile": ["Bambu PLA Basic @BBL X1C"],
            "printable_area": ["0x0", "256x0", "256x256", "0x256"],
            "printable_height": "250",
        },
        "Bambu Lab P1S 0.4 nozzle": {
            "default_print_profile": "0.20mm Standard @BBL X1C",
            "default_filament_profile": ["Bambu PLA Basic @BBL X1C"],
            "printable_area": ["0x0", "256x0", "256x256", "0x256"],
            "printable_height": "256",
        },
    }

    def get_by_name(self, kind, name, user_id=None):
        data = self.machines.get(name) if kind == "machine" else None
        return None if data is None else SimpleNamespace(name=name, vendor="BBL", kind=kind, data=data)


@pytest.fixture
def account(client, monkeypatch, tmp_path):
    """The experiment on, a plug-in that lists three printers, a catalogue with two of those models, and a search that finds two."""
    from app.config import settings

    monkeypatch.setattr(settings, "experimental_bambu_cloud", True)
    monkeypatch.setattr(settings, "orcaslicer_datadir", tmp_path)
    monkeypatch.setattr(settings, "bambu_helper_path", _helper(tmp_path, _steps([X1C, P1S, ODD])))
    monkeypatch.setattr(profiles, "catalog", FakeCatalog())
    searched: list[tuple[str, set[str]]] = []

    async def find(network, serials, **_):
        searched.append((network, set(serials)))
        return {X1C["serial"]: "192.168.1.58", P1S["serial"]: "192.168.1.45"}

    monkeypatch.setattr(bambu_discovery, "find_printers", find)
    yield SimpleNamespace(searched=searched)
    for printer in client.get("/printers").json():
        client.delete(f"/printers/{printer['id']}")


def _connect(client, **extra):
    return client.post("/bambu-cloud/account", json={"url": PASTED, "network": "192.168.1.0/24", **extra})


def test_the_account_lists_its_printers_with_where_they_were_found(client, account):
    body = _connect(client).json()
    assert body["signed_in"] is True and body["user"] == "maker" and body["network"] == "192.168.1.0/24"
    assert body["printers"] == [
        {"index": 0, "model": "X1 Carbon", "name": "Shed", "online": True, "ip": "192.168.1.58", "supported": True},
        {"index": 1, "model": "P1S", "name": "Desk", "online": False, "ip": "192.168.1.45", "supported": True},
        {"index": 2, "model": "Mystery Printer", "name": "Odd", "online": True, "ip": None, "supported": False},
    ]
    assert len(body["import_id"]) >= 22


def test_the_browser_is_never_told_a_serial_number_or_an_access_code(client, account):
    text = _connect(client).text
    for secret in ("00M00A000000000", "01P00A000000000", "12345678", "87654321", "AAA", "RRR"):
        assert secret not in text


def test_the_search_is_only_for_the_serials_the_account_has(client, account):
    _connect(client)
    assert account.searched == [("192.168.1.0/24", {"00M00A000000000", "01P00A000000000", "09X00A000000000"})]


def test_without_a_private_address_to_search_nothing_is_searched(client, account):
    body = client.post("/bambu-cloud/account", json={"url": PASTED}).json()
    assert account.searched == [] and body["network"] is None
    assert [p["ip"] for p in body["printers"]] == [None, None, None]


def test_a_network_that_may_not_be_searched_is_refused_before_anything_runs(client, account):
    response = _connect(client, network="8.8.8.0/24")
    assert response.status_code == 400 and "private" in response.json()["detail"]
    assert account.searched == []


def test_a_failed_sign_in_lists_nothing_to_add(client, account, monkeypatch, tmp_path):
    from app.config import settings

    failed = [
        {"step": "get_my_profile", "value": {"http_code": 60, "result": -1}},
        {"step": "is_user_login", "value": False},
    ]
    monkeypatch.setattr(settings, "bambu_helper_path", _helper(tmp_path, failed))
    body = _connect(client).json()
    assert (
        body["signed_in"] is False and body["printers"] == [] and body["import_id"] is None and "60" in body["problem"]
    )


def _import(client, key, *items):
    return client.post("/bambu-cloud/import", json={"import_id": key, "items": list(items)})


def test_adding_a_printer_saves_it_with_everything_from_the_account(client, account):
    key = _connect(client).json()["import_id"]
    response = _import(client, key, {"index": 0, "ip": "192.168.1.58"})
    assert response.status_code == 200
    added = response.json()["added"]
    assert [a["name"] for a in added] == ["Shed"]
    saved = client.get("/printers").json()
    assert len(saved) == 1
    printer = saved[0]
    assert (printer["name"], printer["vendor"], printer["host_type"], printer["print_host"]) == (
        "Shed",
        "BBL",
        "bambu",
        "192.168.1.58",
    )
    assert (
        printer["machine_profile"] == "Bambu Lab X1 Carbon 0.4 nozzle"
        and printer["process_profile"] == "0.20mm Standard @BBL X1C"
    )
    assert (
        printer["device_id"] == "00M00A000000000"
        and printer["monitor_only"] is True
        and printer["has_credentials"] is True
    )
    assert printer["bed_width"] == 256.0 and printer["filament_profiles"] == ["Bambu PLA Basic @BBL X1C"]
    assert store.get_printer_row(printer["id"])["printhost_apikey"] == "12345678"
    assert "12345678" not in response.text and "12345678" not in json.dumps(saved)


def test_the_address_can_be_changed_or_left_out_when_adding(client, account):
    key = _connect(client).json()["import_id"]
    _import(client, key, {"index": 0, "ip": " 192.168.1.99 "}, {"index": 1, "ip": ""})
    hosts = {p["name"]: p["print_host"] for p in client.get("/printers").json()}
    assert hosts == {"Shed": "192.168.1.99", "Desk": None}


def test_a_printer_already_saved_is_not_added_twice(client, account):
    key = _connect(client).json()["import_id"]
    _import(client, key, {"index": 0, "ip": "192.168.1.58"})
    again = _import(client, key, {"index": 0, "ip": "192.168.1.58"}, {"index": 1, "ip": "192.168.1.45"}).json()
    assert [a["name"] for a in again["added"]] == ["Desk"]
    assert again["skipped"] == [{"index": 0, "reason": "Already saved"}]
    assert len(client.get("/printers").json()) == 2


def test_a_model_the_catalogue_does_not_have_is_skipped_with_the_reason(client, account):
    key = _connect(client).json()["import_id"]
    result = _import(client, key, {"index": 2, "ip": ""}, {"index": 0, "ip": ""}).json()
    assert [a["name"] for a in result["added"]] == ["Shed"]
    assert result["skipped"] == [{"index": 2, "reason": "Trident has no profile for a Mystery Printer"}]


def test_a_list_that_is_gone_or_never_was_cannot_be_used(client, account):
    assert _import(client, "no-such-list", {"index": 0}).status_code == 404
    assert client.get("/printers").json() == []


def test_a_wrong_index_or_address_adds_nothing_at_all(client, account):
    key = _connect(client).json()["import_id"]
    assert _import(client, key, {"index": 0, "ip": ""}, {"index": 9}).status_code == 400
    bad = _import(client, key, {"index": 0, "ip": ""}, {"index": 1, "ip": "printer.local"})
    assert bad.status_code == 400 and "IP address" in bad.json()["detail"]
    assert client.get("/printers").json() == []


def test_nothing_is_added_when_nothing_is_chosen(client, account):
    key = _connect(client).json()["import_id"]
    assert _import(client, key).status_code == 422


def test_searching_again_finds_the_printers_on_another_network(client, account):
    key = client.post("/bambu-cloud/account", json={"url": PASTED}).json()["import_id"]
    response = client.post("/bambu-cloud/find", json={"import_id": key, "network": "192.168.7.0/24"})
    assert response.status_code == 200
    assert response.json() == {
        "network": "192.168.7.0/24",
        "printers": [{"index": 0, "ip": "192.168.1.58"}, {"index": 1, "ip": "192.168.1.45"}, {"index": 2, "ip": None}],
    }
    assert account.searched[-1] == ("192.168.7.0/24", {"00M00A000000000", "01P00A000000000", "09X00A000000000"})


def test_a_search_again_never_tells_the_browser_a_serial_number_or_an_access_code(client, account):
    key = _connect(client).json()["import_id"]
    text = client.post("/bambu-cloud/find", json={"import_id": key, "network": "192.168.1.0/24"}).text
    for secret in ("00M00A000000000", "01P00A000000000", "12345678", "87654321"):
        assert secret not in text


def test_what_a_search_again_finds_is_what_adding_uses_when_no_address_is_typed_over_it(client, account):
    key = client.post("/bambu-cloud/account", json={"url": PASTED}).json()["import_id"]
    client.post("/bambu-cloud/find", json={"import_id": key, "network": "192.168.1.0/24"})
    _import(client, key, {"index": 0, "ip": "192.168.1.58"})
    assert [p["print_host"] for p in client.get("/printers").json()] == ["192.168.1.58"]


def test_a_network_that_may_not_be_searched_is_refused_when_searching_again(client, account):
    key = _connect(client).json()["import_id"]
    before = len(account.searched)
    response = client.post("/bambu-cloud/find", json={"import_id": key, "network": "8.8.8.0/24"})
    assert response.status_code == 400 and "private" in response.json()["detail"]
    assert len(account.searched) == before


def test_searching_again_needs_a_list_that_still_exists(client, account):
    assert client.post("/bambu-cloud/find", json={"import_id": "gone", "network": "192.168.1.0/24"}).status_code == 404


def test_searching_again_is_off_unless_the_experiment_is_on(client):
    assert client.post("/bambu-cloud/find", json={"import_id": "x", "network": "192.168.1.0/24"}).status_code == 404


def test_adding_is_off_unless_the_experiment_is_on(client):
    assert _import(client, "x", {"index": 0}).status_code == 404
