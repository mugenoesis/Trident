# AGPL-3.0 compliance posture

OrcaSlicer is AGPL-3.0. Since this service may be hosted for others (not purely personal use), the network-use clause applies in practice: anyone interacting with the service over a network is entitled to the corresponding source, including our patches.

## What we're doing about it

- The patched OrcaSlicer fork stays **public** on GitHub at all times — the single most important, cheapest compliance action. _Fork URL: TBD, add once created._
- The API exposes `GET /source` (mirrored as a response header) linking to:
  - the patched fork/branch **and exact commit SHA** the running image was built from (baked into the image at build time, e.g. via an env var or `/version` endpoint)
  - this wrapper repo itself, since the FastAPI layer directly driving OrcaSlicer's engine is plausibly a "combined work" under AGPL even as a separate process
- README + API landing page carry a short AGPL notice + the source link.
- No license-scanning tooling or SPDX pipeline — this is a pragmatic posture for a personal tool that might become a small service, not a legal treatise. Get real legal advice if actual commercialization is later considered.

## CLI settings that are blocked regardless (not an AGPL issue, just a reference)

Verified in `src/libslic3r/PrintConfig.cpp` on `OrcaSlicer/OrcaSlicer` `main` (2026-09-13): 48 `ConfigOptionDef::nocli` marker sites, 3 commented out (`filament_settings_id`, `print_settings_id`, `printer_settings_id` — these are actually NOT blocked despite appearances), leaving 45 active. The API should treat overrides to any of these keys as always-rejected (400). Re-run `grep -n "nocli" src/libslic3r/PrintConfig.cpp` after each upstream merge to catch additions/removals.

**Print-host network credentials / identity** (not needed for pure slicing automation):
`bbl_use_printhost`, `use_3mf`, `printer_agent`, `print_host`, `print_host_webui`, `printhost_apikey`, `flashforge_serial_number`, `printhost_port`, `printhost_cafile`, `printhost_user`, `printhost_password`, `printhost_ssl_ignore_revoke`, `printhost_authorization_type`

**Preset identity / inheritance / compatibility bookkeeping** (managed by the profile catalog, not per-job overrides):
`compatible_printers`, `upward_compatible_machine`, `compatible_printers_condition`, `compatible_prints`, `compatible_prints_condition`, `compatible_machine_expression_group`, `compatible_process_expression_group`, `different_settings_to_system`, `print_compatible_printers`, `default_filament_profile`, `default_print_profile`, `filament_ids`, `filament_vendor`, `inherits`, `inherits_group`, `printer_model`, `printer_variant`, `extruder_variant_list`, `printer_extruder_id`, `printer_extruder_variant`, `print_extruder_id`, `print_extruder_variant`, `filament_extruder_id`, `filament_extruder_variant`, `filament_self_index`, `material_vendor`, `default_sla_material_profile`, `sla_material_settings_id`, `default_sla_print_profile`, `sla_print_settings_id`

**Conclusion**: none of these are needed for automation-driven slicing. No unblocking patch is planned.
