# AGPL-3.0 compliance posture

OrcaSlicer is AGPL-3.0. Since this service may be hosted for others (not purely personal use), the network-use clause applies in practice: anyone interacting with the service over a network is entitled to the corresponding source, including our patches.

## What we're doing about it

- The patched OrcaSlicer fork stays **public** on GitHub at all times — the single most important, cheapest compliance action. Fork URL: https://github.com/mugenoesis/Pseudorca (branch `headless-orca`).
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

## Bambu's network plug-in (experiment, not part of the image)

With `ORCA_API_EXPERIMENTAL_BAMBU_CLOUD=1`, Trident can load Bambu's own network plug-in (`libbambu_networking.so`, the one Bambu Studio and OrcaSlicer download on first use). It is closed software under Bambu's terms, so:

- **It is never in the image or in this repository.** It is downloaded from Bambu's own servers, to the user's data folder, only when the user asks for it under **Add from Bambu account**. The plug-in's checksum is kept next to it.
- **What runs it is ours and public:** `api/helper/bbl_session.cpp`, a small program built from source in the Docker image's first stage (g++ and nlohmann-json), which loads the plug-in with `dlopen` and calls it in the order OrcaSlicer and Bambu Studio do. The parameter layout it passes is copied from OrcaSlicer's `bambu_networking.hpp`.
- **It talks to Bambu's servers and the user's printer as the plug-in itself does.** Trident sets no client name or other identity for Bambu's server, and the sign-in is done by the user in their own browser: Trident never sees a password.
