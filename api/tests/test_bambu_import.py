"""Turning the printers of a Bambu account into saved printers (app/bambu_import.py): which catalogue printer a model is, what is saved for
it, and the short-lived list that keeps each printer's serial number and access code on the server (never in the browser).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import bambu_import as imp

X1C_DATA = {
    "default_print_profile": "0.20mm Standard @BBL X1C",
    "default_filament_profile": ["Bambu PLA Basic @BBL X1C", "Bambu ABS @BBL X1C"],
    "printable_area": ["0x0", "256x0", "256x256", "0x256"],
    "printable_height": "250",
}
A1M_DATA = {
    "default_print_profile": "0.20mm Standard @BBL A1M",
    "default_filament_profile": "Bambu PLA Basic @BBL A1M",
    "printable_area": ["0x0", "180x0", "180x180", "0x180"],
    "printable_height": "180",
}


class FakeCatalog:
    """Just the lookup the import uses (profiles.ProfileCatalog.get_by_name)."""

    def __init__(self, machines: dict[str, dict]):
        self.machines = machines

    def get_by_name(self, kind: str, name: str, user_id: str | None = None):
        data = self.machines.get(name) if kind == "machine" else None
        return None if data is None else SimpleNamespace(name=name, vendor="BBL", kind=kind, data=data)


CATALOG = FakeCatalog({"Bambu Lab X1 Carbon 0.4 nozzle": X1C_DATA, "Bambu Lab A1 mini 0.4 nozzle": A1M_DATA})
DEVICE = {"serial": "00M00A000000000", "access_code": "12345678", "model": "X1 Carbon", "name": "Shed", "online": True}


def test_a_model_is_the_catalogue_printer_with_its_own_defaults():
    request = imp.printer_request(DEVICE, "192.168.1.58", CATALOG)
    assert request == {
        "name": "Shed",
        "vendor": "BBL",
        "machine_profile": "Bambu Lab X1 Carbon 0.4 nozzle",
        "process_profile": "0.20mm Standard @BBL X1C",
        "filament_profiles": ["Bambu PLA Basic @BBL X1C"],
        "filament_colors": ["#ffffff"],
        "bed_width": 256.0,
        "bed_depth": 256.0,
        "bed_height": 250.0,
        "host_type": "bambu",
        "print_host": "192.168.1.58",
        "printhost_apikey": "12345678",
        "device_id": "00M00A000000000",
        "monitor_only": True,
    }


def test_a_default_material_given_as_one_name_works_too():
    request = imp.printer_request({**DEVICE, "model": "A1 mini"}, "192.168.1.195", CATALOG)
    assert request is not None
    assert request["filament_profiles"] == ["Bambu PLA Basic @BBL A1M"] and request["bed_width"] == 180.0


def test_a_printer_without_a_name_is_called_by_its_model():
    request = imp.printer_request({**DEVICE, "name": None}, None, CATALOG)
    assert request is not None and request["name"] == "X1 Carbon"


def test_a_printer_whose_address_was_not_found_is_saved_without_one():
    request = imp.printer_request(DEVICE, None, CATALOG)
    assert request is not None and request["print_host"] is None


def test_a_model_the_catalogue_does_not_have_is_not_saved():
    assert imp.printer_request({**DEVICE, "model": "Some New Printer"}, "192.168.1.9", CATALOG) is None
    assert imp.has_profile("Some New Printer", CATALOG) is False
    assert imp.has_profile("X1 Carbon", CATALOG) is True


def test_a_catalogue_printer_with_no_bed_size_is_saved_without_one():
    bare = FakeCatalog(
        {"Bambu Lab X1 Carbon 0.4 nozzle": {"default_print_profile": "p", "default_filament_profile": ["f"]}}
    )
    request = imp.printer_request(DEVICE, None, bare)
    assert request is not None and request["bed_width"] is None and request["bed_height"] is None


@pytest.mark.parametrize("address", ["192.168.1.58", "10.0.0.7", " 192.168.1.58 "])
def test_an_ip_address_is_taken_as_typed(address):
    assert imp.clean_ip(address) == address.strip()


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_no_address_is_none(empty):
    assert imp.clean_ip(empty) is None


@pytest.mark.parametrize(
    "bad",
    ["printer.local", "192.168.1", "192.168.1.999", "192.168.1.5:8883", "http://192.168.1.5", "::1", "1.2.3.4 5.6.7.8"],
)
def test_only_an_ipv4_address_is_accepted(bad):
    with pytest.raises(ValueError, match="IP address"):
        imp.clean_ip(bad)


def test_the_account_list_is_kept_briefly_and_can_be_read_again():
    now = [1000.0]
    pending = imp.PendingAccounts(ttl_s=600, clock=lambda: now[0])
    key = pending.put([DEVICE])
    assert pending.get(key) == [DEVICE]
    now[0] += 599
    assert pending.get(key) == [DEVICE]


def test_the_account_list_expires():
    now = [1000.0]
    pending = imp.PendingAccounts(ttl_s=600, clock=lambda: now[0])
    key = pending.put([DEVICE])
    now[0] += 601
    assert pending.get(key) is None


def test_the_account_list_can_be_forgotten():
    pending = imp.PendingAccounts()
    key = pending.put([DEVICE])
    pending.forget(key)
    assert pending.get(key) is None


def test_a_made_up_key_gets_nothing_and_keys_are_not_guessable():
    pending = imp.PendingAccounts()
    first, second = pending.put([DEVICE]), pending.put([DEVICE])
    assert first != second and len(first) >= 22
    assert pending.get("nope") is None and pending.get("") is None


def _step(devices):
    return [{"step": "is_user_login", "value": True}, {"step": "account_devices", "value": devices}]


def test_the_helpers_device_step_becomes_the_accounts_printers_with_their_secrets():
    raw = {
        "dev_id": "00M00A000000000",
        "dev_access_code": "12345678",
        "dev_name": "Shed",
        "dev_online": True,
        "dev_product_name": "X1 Carbon",
        "dev_model_name": "BL-P001",
    }
    assert imp.private_devices(_step([raw])) == [DEVICE]


def test_a_model_is_the_product_name_or_else_the_model_code():
    raw = {"dev_id": "s", "dev_access_code": "c", "dev_model_name": "N1"}
    assert imp.private_devices(_step([raw]))[0]["model"] == "N1"
    assert imp.private_devices(_step([{}]))[0]["model"] == "Unknown"


def test_a_device_with_odd_values_gets_safe_ones():
    raw = {"dev_id": 5, "dev_access_code": None, "dev_name": "", "dev_online": "boolean", "dev_product_name": ["x"]}
    assert imp.private_devices(_step([raw, "junk"])) == [
        {"serial": "", "access_code": "", "model": "Unknown", "name": None, "online": None}
    ]


@pytest.mark.parametrize(
    "steps", [[], [{"step": "account_devices", "value": "not a list"}], [{"step": "account_devices"}], ["junk"]]
)
def test_no_device_step_means_no_printers(steps):
    assert imp.private_devices(steps) == []


def test_only_the_latest_few_account_lists_are_kept():
    pending = imp.PendingAccounts(keep=3)
    keys = [pending.put([{**DEVICE, "name": str(i)}]) for i in range(5)]
    assert [pending.get(k) is not None for k in keys] == [False, False, True, True, True]
