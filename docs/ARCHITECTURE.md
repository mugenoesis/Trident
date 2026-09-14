# Architecture & Implementation Plan

This document is the working implementation plan for headless-orca: containerizing OrcaSlicer's slicing engine headlessly, patching its CLI for robustness, and exposing it over a FastAPI service.

## Context

OrcaSlicer already has a real, working CLI/headless mode (`src/OrcaSlicer.cpp`, entry `CLI::run`) — this project is not a build-from-scratch effort, it's extend, patch, and harden an existing feature, then wrap it in Docker + an API.

Key facts verified directly against the live `OrcaSlicer/OrcaSlicer` `main` branch source (not just secondhand docs):

- **Headless gcode-thumbnail rendering already exists and degrades gracefully.** `src/OrcaSlicer.cpp:6887-6922` calls `glfwInit()` then `glfwCreateWindow(640, 480, "base_window", NULL, NULL)` with `GLFW_VISIBLE=false` for a hidden OpenGL context, logging `"Failed to create GLFW window; skipping thumbnail rendering for CLI export"` and continuing without crashing if that fails. Thumbnails are a Docker/runtime config problem (get GLFW's X11/GLX backend working under Xvfb + software Mesa), **not** new C++/EGL engineering.
- **Structured machine-readable output already exists.** `record_exit_reson()` (`OrcaSlicer.cpp:425`) writes `result.json` to `--outputdir` on every exit path: `return_code`, `error_string`, per-plate slice stats, via a `cli_errors[...]` map of named exit codes (`CLI_SUCCESS`, `CLI_INVALID_PARAMS`, `CLI_FILE_NOTFOUND`, `CLI_FILELIST_INVALID_ORDER`, `CLI_FILE_VERSION_NOT_SUPPORTED`, `CLI_POSTPROCESS_NOT_SUPPORTED`, `CLI_INVALID_PRINTER_TECH`, `CLI_DATA_FILE_ERROR`, `CLI_CONFIG_FILE_ERROR`, others). `--pipe <fifo>` streams newline-delimited JSON progress (`plate_index`, `plate_count`, `plate_percent`, `total_percent`, `message`/`warning`). **`result.json` is the API's source of truth for job outcome; `--pipe` is for live progress only.**
- **The ~45 CLI-blocked ("nocli") settings are confirmed benign.** `src/libslic3r/PrintConfig.cpp` has 48 `ConfigOptionDef::nocli` marker sites (3 commented out). All active ones are print-host network credentials or preset-identity/inheritance bookkeeping — nothing needed for pure slicing automation. No unblocking patch needed.
- **`SLIC3R_GUI=OFF` is confirmed unbuildable as-is.** `src/CMakeLists.txt` only wraps `add_subdirectory(slic3r)` (the GUI library) in `if (SLIC3R_GUI)` (lines 16-133); `add_executable(OrcaSlicer OrcaSlicer.cpp OrcaSlicer.hpp)` (line 139) is unconditional and its translation unit references GUI-namespace code regardless. Build normally (GUI libs compiled in) and never open a real display at runtime.
- **License is AGPL-3.0** — see [AGPL-COMPLIANCE.md](AGPL-COMPLIANCE.md).
- **Build resources**: build on the 64GB build server, not a RAM-constrained dev machine — OrcaSlicer's own docs suggest ~16GB RAM for a full parallel build.

Confirmed product decisions:
1. **Scale**: personal/single-user — no job queue (Redis/Celery); FastAPI `BackgroundTasks` + SQLite job store is sufficient.
2. **Thumbnails**: wanted — a Docker/runtime config problem (Xvfb + software GL), not new C++.
3. **License/hosting**: may host for others — keep the patched fork public, expose a source-offer link from the API.

## Repo layout and patch workflow

```
headless-orca/
├── README.md
├── vendor/orcaslicer/      # git submodule -> public fork, pinned commit
├── docker/
│   ├── Dockerfile          # multi-stage: builder + runtime
│   └── entrypoint.sh       # xvfb-run wrapped entrypoint
├── api/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py
│   │   ├── routers/ (models.py, profiles.py, jobs.py, source.py)
│   │   ├── cli_runner.py   # subprocess + --pipe/result.json orchestration
│   │   ├── jobstore.py     # sqlite-backed job store
│   │   ├── profiles.py     # resources/profiles/*.json introspection
│   │   └── schemas.py
│   └── tests/
├── docs/
│   ├── ARCHITECTURE.md     # this file
│   └── AGPL-COMPLIANCE.md
└── scripts/
    └── smoke_test.sh       # docker run ... --slice ... end-to-end check
```

- **Fork `OrcaSlicer/OrcaSlicer` to a public repo** under the user's GitHub account (required — decision #3 above).
- Create a long-lived branch, e.g. `headless-cli`, with patches as normal commits (not a `.patch`-file directory) — cleanest AGPL "corresponding source" story: point at `github.com/<user>/OrcaSlicer/tree/headless-cli`.
- Add the fork as a **git submodule** at `vendor/orcaslicer`, pinned to a specific commit SHA.
- Add upstream as a second remote (`git remote add upstream https://github.com/OrcaSlicer/OrcaSlicer.git`) and **merge** (not rebase) `upstream/main` periodically — OrcaSlicer is very active; rebasing a long-lived branch repeatedly is high-friction. Keep the patch surface small (mainly `src/OrcaSlicer.cpp`, possibly `src/libslic3r/Config.hpp/.cpp`) to keep merges low-conflict.

## Source code changes (land as commits on `headless-cli`)

1. **Port Snapmaker's fork PR `Snapmaker/OrcaSlicer#839`** ("Make the CLI able to slice: fix the version check and two null GUI crashes") — ~~still open/unmerged upstream~~ **investigated and mostly moot as of `15ebdc3`** (full `CLI::run` call-graph trace, see `vendor/orcaslicer` commit `3990e71fac`): Defect 1 (version check) is already fixed upstream verbatim; Defect 3 (`expand_plate_extruders`/mixed-filament virtual extruder ids) is Snapmaker-fork-only code that doesn't exist in `OrcaSlicer/OrcaSlicer`. Only Defect 2 (`PartPlate::generate_plate_name_texture()` dereferencing `m_partplate_list->m_plater` before the null-check) was real, and it isn't currently reachable from the CLI's `--slice` path either (only reached via the interactive GLCanvas3D repaint path; the CLI's own thumbnail renderer explicitly skips `PartPlate::render()`) — ported defensively anyway since it's a real latent bug and cheap to close.
2. **Harden against blocking-on-input / modal dialogs** when running non-interactively (community reports, e.g. `dmikushin/orca-slicer-mcp`, describe hangs from this). ~~Same investigation as #1 — one combined workstream.~~ **Investigated as part of #1's call-graph trace: no live issue found.** Every other `wxGetApp()` call site in `PartPlate.cpp` reachable from `CLI::run` is already guarded, dead code, or behind a CLI-safe overload upstream has already built for this exact problem (`get_extruders_under_cli()`, `get_real_filament_maps()`, etc. — recent upstream commits explicitly cite CLI reachability as the reason). A full grep of `CLI::run` for `ShowModal`/`wxMessageBox`/`wxMessageDialog`/`wxProgressDialog`/blocking stdin reads: zero hits. Re-verify this if M1/M3 testing ever reproduces an actual `wxGetApp()` crash under `--slice` — that would mean the reachability analysis missed an indirect path worth re-tracing.
3. **No settings-unblocking patch needed** (see confirmed `nocli` audit) — document the blocked-keys list in [AGPL-COMPLIANCE.md](AGPL-COMPLIANCE.md) or here, re-run `grep -n "nocli" src/libslic3r/PrintConfig.cpp` after each upstream merge to catch additions.
4. **Thumbnail rendering — verify before patching.** Run the container under `xvfb-run`, check logs for `"glfwInit Success."` vs `"Failed to create GLFW window..."`. Only patch if that fails. Confirm exact thumbnail storage location (embedded `.3mf` metadata vs. elsewhere) in `src/libslic3r/Format/bbs_3mf.cpp`.
5. **New patch: `--help-json` schema dump.** `ConfigDef::print_cli_help` (`src/libslic3r/Config.hpp`, backs `--help-fff`/`--help-sla`) has full access to option name/type/description/enum/`nocli`. Add `ConfigDef::print_cli_help_json` + a `--help-json` CLI action serializing the same data as JSON — lets the API auto-generate its settings list.
6. **CLI ergonomics** — `--pipe` and `result.json` are already sufficient; no further patches anticipated.

## Docker image design

**Builder stage** (`ubuntu:24.04`, matching `.devcontainer` and `build_linux.sh -g`):
- Install system deps via `vendor/orcaslicer/scripts/linux.d/debian` (shell out to `./build_linux.sh -u`, don't hand-transcribe).
- Build via the existing script: deps stage (`cmake -S deps -B deps/build -G Ninja && cmake --build deps/build -j<N>`) then main build (`cmake -S . -B build -G "Ninja Multi-Config" -DSLIC3R_PCH=ON -DORCA_TOOLS=ON && cmake --build build --config Release --target OrcaSlicer`).
- Build on the 64GB build server — comfortably clears OrcaSlicer's ~16GB recommendation, full-parallel build should be safe.
- **Layer caching**: `deps/` build (multi-hour, ~15-30GB) as its own layer before the rest of `src/`. BuildKit cache mount for ccache/sccache (auto-detected by `build_linux.sh`).

**Runtime stage** (slim):
- `COPY --from=builder` the built `OrcaSlicer` binary, its `resources/` dir (`resources_dir()`), and required shared libs (`ldd` the binary to get the definitive list; expect GTK3/X11/GL libs plus `dlopen`-loaded GStreamer libs invisible to `ldd`).
- Keep GTK3/X11 runtime libs even though no window is shown — the binary links them regardless of `SLIC3R_GUI` at compile time.
- Add **Xvfb** + **Mesa** (`libgl1-mesa-dri`) as the primary offscreen-rendering path for thumbnails (matches GLFW's actual X11/GLX backend usage, not EGL-surfaceless).
- `docker/entrypoint.sh` wraps commands in `xvfb-run -a`.
- Volumes: `/data/models` (uploads), `/data/output` (per-job `--outputdir`: gcode, `result.json`, thumbnail), `/data/orcaslicer-datadir` (named volume, `--datadir` — writable user presets/cache, distinct from read-only baked-in `resources/profiles/`).

## FastAPI service design

Single process, no external queue (single-user scale).

- `POST /models` — multipart upload (stl/3mf/obj/step) → `model_id`.
- `GET /profiles`, `GET /profiles/{vendor}/{kind}/{name}` — introspects `resources/profiles/*.json` + sibling `<Vendor>/` dirs; cached in memory at startup.
- `GET /settings/schema` — shells out once (cached) to `--help-json` for the overridable-settings list with type/enum/defaults, filtering `nocli` entries; falls back to parsing `--help-fff`/`--help-sla` text if that patch isn't ready.
- `POST /jobs` — model_id + profile selection + setting overrides (validated against `/settings/schema`) → `BackgroundTasks`.
- `GET /jobs/{id}` — status, live progress (`--pipe`), and on completion the parsed `result.json`.
- `GET /jobs/{id}/gcode`, `GET /jobs/{id}/thumbnail` — download artifacts.
- `GET /source` — AGPL source-offer link.

**Job store**: SQLite under a volume (survives API restarts).

**`cli_runner.py` subprocess orchestration** — real race condition to handle: `cli_callback_mgr_t::start()` opens the `--pipe` FIFO with `O_WRONLY|O_NONBLOCK` in a retry loop that gives up after ~1 second if nothing has opened it for reading yet. Create the FIFO (`os.mkfifo`), start a reader, *then* spawn the subprocess. After exit, read `<job_dir>/result.json` as the authoritative result, falling back to raw exit code + stderr only if that file is missing.

## Milestones and verification

**M1 — Vanilla build + Docker + prove headless slicing works**
- Fork upstream, submodule into `vendor/orcaslicer`, build via `build_linux.sh` inside the Docker builder stage (no patches yet).
- Verify: `docker run <image> orca-slicer --help` succeeds; slice bundled `resources/handy_models/OrcaBadge.3mf` end-to-end, inspect `result.json` for `return_code: 0`.
- Fold in the thumbnail feasibility check: re-run under `xvfb-run -a`, grep logs for `"glfwInit Success."` / `"Failed to create GLFW window..."`.

**M2 — Crash-fix + hardening patches**
- Port Snapmaker #839 fixes; guard `wxGetApp()`/modal-dialog call sites reachable from `CLI::run`.
- Land the `--help-json` patch.
- Verify: re-run M1 smoke test; try to reproduce known crash classes to confirm the patch fixes something real.

**M3 — FastAPI wrapper**
- Build endpoints against the patched image.
- Verify: (a) `POST /jobs` against the bundled sample model reproduces M1's `docker run` result; (b) a real uploaded STL slices correctly with a profile from `GET /profiles`; (c) a setting override (e.g. `layer_height`) demonstrably changes output gcode; (d) `--pipe` progress reaches `GET /jobs/{id}` in near-real-time.

**M4 — Thumbnail integration**
- If M1 showed it already works under `xvfb-run`: wire the output file into `GET /jobs/{id}/thumbnail`.
- If not: scoped as getting GLFW's X11/GLX backend to succeed against Xvfb+llvmpipe — bounded systems/config problem.
- Verify: downloaded thumbnail PNG visually renders the sliced model, across at least two models/profiles.

## Critical files

- `vendor/orcaslicer/src/OrcaSlicer.cpp` — CLI entry point, `CLI::run`, `--pipe`/`result.json` protocol, GLFW thumbnail path (~lines 6887-6922).
- `vendor/orcaslicer/src/libslic3r/PrintConfig.cpp` — `nocli`-blocked settings list and option definitions; source for `--help-json`.
- `vendor/orcaslicer/src/libslic3r/Config.hpp` — `ConfigDef::print_cli_help`, extend for `--help-json`.
- `vendor/orcaslicer/src/libslic3r/Format/bbs_3mf.cpp` — where thumbnail data is embedded on export.
- `vendor/orcaslicer/build_linux.sh` + `vendor/orcaslicer/scripts/linux.d/debian` — authoritative build recipe/deps list.
- `docker/Dockerfile`, `docker/entrypoint.sh` — multi-stage build + Xvfb-wrapped entrypoint.
- `api/app/cli_runner.py` — subprocess/FIFO/`result.json` orchestration.
