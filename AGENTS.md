# AGENTS.md: instructions for AI coding sessions

Read this first, then `README.md` (what Trident does, how it is built and checked) and `docs/ARCHITECTURE.md` (the design).
`web/README.md` explains how the web app's main screen is put together.

## What this project is

Trident (Trident Studio, repo `headless-orca`) is a **self-hosted slicer for a server**: OrcaSlicer's engine run headless in Docker, a
FastAPI API (`api/`) and a React web UI (`web/`), shipped as one container. License: AGPL-3.0-only.

- The slicing engine is a **submodule**, `vendor/orcaslicer` = the `headless-orca` branch of `mugenoesis/Pseudorca` (our OrcaSlicer fork,
  which also holds the resin/MSLA engine). Engine changes are made and merged **there**, then Trident moves to them in a small
  pin-only PR (change the submodule commit, nothing else).
- FDM and resin share the job API: `POST /jobs` takes `technology` (`fdm` default, `resin`). Resin code is in `api/app/resin.py`,
  `resin_runner.py`, `routers/resin.py` and, in the web app, `hooks/useResin.ts`, `resinSettings.ts` and `components/ResinPanel.tsx`.

## Workflow rules (from the user)

1. **Test-driven development, UI included.** For every feature or bug fix:
   1. Write or extend a failing test first.
   2. Run it and confirm it fails for the expected reason.
   3. Implement until it passes, then refactor.
   4. A test written after the code is mutation-checked: break the code and see the test fail.
   API tests are in `api/tests` (fast, no engine; `api/tests_slicer` runs the real binary). `scripts/slicer-tests.sh <image>` runs the real-slicer ones in an image that has the engine. Browser behaviour is tested by the Playwright
   scripts in `web/` (`smoke-test.mjs`, `keys-test.mjs`, `resin-test.mjs`, `viewer-test.mjs`), each run against a *running* container.
2. **Every change is a new branch and a new PR** off up-to-date `origin/master`, for the user to merge. Never push to `master`, never
   force-push it, never merge for the user. Follow-up work after a merged PR gets a fresh branch and a fresh PR. Say so when a PR
   contains another PR's merge, and avoid stacking PRs on unmerged branches.
3. **UI changes need a mockup the user approves first**, unless it is a plain addition to an existing list. Show screenshots or a
   mockup, then build.
4. **Run the whole gate before pushing: `scripts/check.sh`** (web: biome, knip, typecheck, build; api: black, ruff, pyright, complexity,
   vulture, tests with a coverage floor). Not a hand-picked subset: the gate catches what pieces miss. A host with no Python runs the Python
   tools through `scripts/py.sh`. Biome holds every function to a cognitive complexity of 15, so a new feature goes in its own small
   hook, component or function.
5. **Never test against the live `Trident` container.** Tests that touch jobs or printers wipe real data. Use an ephemeral container
   (for example the engine image with `api/app` and `web/dist` mounted over it, on a spare port) and remove it afterwards.
6. **Save repeatable tasks as scripts** in `scripts/` with a usage header, and list them in the README.
7. **Keep docs current.** Update `README.md` when user-facing behaviour changes (its feature list), `web/README.md` when the main
   screen's structure changes, and this file when conventions change.
8. **Don't change FDM output by accident.** Anything that changes what the FDM slicer produces is reported to the user, not merged.
9. Release notes and PR text describe the behaviour, never the specific test model used to find it.
10. Don't import data whose licence or terms are unknown (the user asks the owner first). Resin material rows carry a source and date.

## Commands

```bash
scripts/check.sh [web|api]                 # the gate
scripts/py.sh pytest -q tests/test_resin.py   # Python tools in a throwaway container (the first run installs the venv: slow)
cd web && npm run dev                      # Vite on :5173, talking to an API on :8000
```

## Environment gotchas
- The dev host (Unraid) has **no Python and no browsers**. Python goes through `scripts/py.sh`; Playwright runs in
  `mcr.microsoft.com/playwright:v<version>-noble` (the tag matches the `playwright` version in `web/package.json`), with
  `--network host -e SMOKE_BASE_URL=http://localhost:<port>`.
- **Run biome from `web/`**, not from the repository root's parent or a bare mount: its config is `biome.json` at the repository root, and
  running it where it is not found reformats every file with the defaults.
- A fresh container is on the first-run screen (choose "Just me (no login)"); `keys-test.mjs` needs a container that has just started.
- The full API test run takes about 12 minutes; run it in the background.
- Engine images for testing are built by layering a fresh engine build over a Trident image (see Pseudorca's `scripts/pseudorca/build-candidate.sh`);
  a full Dockerfile build takes about an hour.

## The Printers page (live Klipper state)
- Server: `klipper_status.status_from_klipper` (pure) turns Moonraker's objects-query `status` into what the page shows; `printhost.read_status` (asks the objects list, then only the print objects and the heaters and sensors), `print_control` (**only pause, resume and cancel**, checked before anything is sent), `webcam_list` and `webcam_snapshot` (the printer's key goes only to the printer's own address, never to a camera elsewhere) are the Moonraker side; routes are in routers/printers.py (all need a saved printer with host_type moonraker). Tests use `tests/fixtures/klipper_u1_status.json` (trimmed from a real response).
- Web: `PrintersButton` (header) opens `PrintersPanel`, one `PrinterCard` per saved Klipper printer; `usePrinterStatus` polls every 3 s only while a card is mounted, `PrinterCam` renews a webcam picture about once a second (each picture loads out of sight and is swapped in), `printerStatus.ts` holds the pure labels and text. `web/printers-test.mjs` runs it against a fake Moonraker.

## Bambu printers (LAN / Developer mode)
- A saved printer with `host_type` bambu keeps the IP address in `print_host` (it may carry `:port` for the MQTT port, `split_host`), the **serial number in `device_id`** and the **LAN access code in `printhost_apikey`** (never sent back). `bambu_link.py` is the MQTT link (TLS on 8883, user bblp; `PahoTransport` is behind a small interface so tests use a fake; links are kept per printer and reaped after a minute idle; a P1/A1 sends only changed values, so the report is merged), `bambu_status.py` turns a report into the same status shape as `klipper_status.py`, `bambu_send.py` uploads the sliced 3MF by implicit FTPS (990, `ImplicitFtps`: wrapped before the greeting, TLS session reused for data) and builds the `project_file` start command, and `bambu_camera.py` takes one picture (an A1/P1: the TLS JPEG socket on 6000; an X1/H2: one frame of the RTSPS stream on 322 through PyAV). Only pause/resume/cancel and the start command can be sent (`BambuLink.control`, `start_print`).
- A slice for a Bambu machine (`cli_runner.is_bambu_machine`) also writes `sliced.gcode.3mf` (`--export-3mf`), which is what `/printers/{id}/send/{job}` uploads. **None of the Bambu code has met a real printer: the protocol is documented by Bambu's users, not by Bambu** (OpenBambuAPI has no stated licence, so nothing is copied from it). `web/bambu-test.mjs` runs everything against a fake printer (MQTT broker, FTPS and camera servers; it needs openssl and free ports 990 and 6000); a raw view (`GET /printers/{id}/raw-status`, identifying fields removed) is how to find out what a printer really reports.

## API and web conventions
- Jobs are stored as free-form records (`jobstore`, SQLite); new job kinds go in the existing `result` and `setting_overrides`, not new columns.
- The web app's state lives in `hooks/useAppState.ts`; each hook next to it does one job and `useAppController.ts` calls them in order.
  Pure logic that needs no React goes in plain modules (`appHelpers.ts`, `sliceRequest.ts`, `resinSettings.ts`).
- Model preview materials are double-sided on purpose: a mesh with faces wound inward (which the slicer repairs) must not show holes.
- The resin row choice (printer match, layer height) is duplicated in Python (`resin.choose_row`) and in the engine; both run the same cases.
