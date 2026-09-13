"""Settings keys the CLI rejects (`ConfigOptionDef::nocli`).

Mirrors docs/AGPL-COMPLIANCE.md's audit of
vendor/orcaslicer/src/libslic3r/PrintConfig.cpp. Re-derive that list with
`grep -n "nocli" src/libslic3r/PrintConfig.cpp` after each upstream merge
and update both places together.
"""
from __future__ import annotations

PRINTHOST_KEYS = frozenset(
    {
        "bbl_use_printhost",
        "use_3mf",
        "printer_agent",
        "print_host",
        "print_host_webui",
        "printhost_apikey",
        "flashforge_serial_number",
        "printhost_port",
        "printhost_cafile",
        "printhost_user",
        "printhost_password",
        "printhost_ssl_ignore_revoke",
        "printhost_authorization_type",
    }
)

PRESET_IDENTITY_KEYS = frozenset(
    {
        "compatible_printers",
        "upward_compatible_machine",
        "compatible_printers_condition",
        "compatible_prints",
        "compatible_prints_condition",
        "compatible_machine_expression_group",
        "compatible_process_expression_group",
        "different_settings_to_system",
        "print_compatible_printers",
        "default_filament_profile",
        "default_print_profile",
        "filament_ids",
        "filament_vendor",
        "inherits",
        "inherits_group",
        "printer_model",
        "printer_variant",
        "extruder_variant_list",
        "printer_extruder_id",
        "printer_extruder_variant",
        "print_extruder_id",
        "print_extruder_variant",
        "filament_extruder_id",
        "filament_extruder_variant",
        "filament_self_index",
        "material_vendor",
        "default_sla_material_profile",
        "sla_material_settings_id",
        "default_sla_print_profile",
        "sla_print_settings_id",
    }
)

# NOT blocked despite appearing in PrintConfig.cpp as commented-out nocli markers.
EXPLICITLY_ALLOWED = frozenset(
    {"filament_settings_id", "print_settings_id", "printer_settings_id"}
)

BLOCKED_SETTINGS = (PRINTHOST_KEYS | PRESET_IDENTITY_KEYS) - EXPLICITLY_ALLOWED


def blocked_keys(overrides: dict[str, object]) -> list[str]:
    """Return which override keys are on the nocli blocklist, if any."""
    return [k for k in overrides if k in BLOCKED_SETTINGS]
