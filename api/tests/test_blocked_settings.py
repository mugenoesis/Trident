from app.blocked_settings import BLOCKED_SETTINGS, blocked_keys


def test_printhost_credentials_are_blocked():
    assert "print_host" in BLOCKED_SETTINGS
    assert "printhost_apikey" in BLOCKED_SETTINGS


def test_commented_out_nocli_keys_are_allowed():
    for key in ("filament_settings_id", "print_settings_id", "printer_settings_id"):
        assert key not in BLOCKED_SETTINGS


def test_blocked_keys_reports_only_offenders():
    overrides = {"layer_height": 0.2, "print_host": "http://example"}
    assert blocked_keys(overrides) == ["print_host"]


def test_blocked_keys_empty_when_clean():
    assert blocked_keys({"layer_height": 0.2}) == []
