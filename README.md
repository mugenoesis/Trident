# headless-orca

A Docker container that runs [OrcaSlicer](https://github.com/OrcaSlicer/OrcaSlicer)'s slicing engine headlessly (no display), with source patches to harden its existing CLI mode, fronted by a FastAPI service that exposes slicing over HTTP.

Status: FastAPI service + Docker/entrypoint/smoke-test scaffolding is in place and unit-tested against a stubbed CLI (see `api/tests/`). **Not yet buildable end-to-end**: `vendor/orcaslicer` isn't wired up yet — that needs a public fork of `OrcaSlicer/OrcaSlicer` under a GitHub account plus a `headless-cli` branch (see M1/M2 in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)), after which it's added here as a git submodule and `docker/Dockerfile` will actually compile. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full implementation plan and milestones.

## Running the API locally (without OrcaSlicer)

```bash
cd api
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                       # 24 tests, all mocked/stubbed — no OrcaSlicer binary needed
.venv/bin/uvicorn app.main:app --reload  # http://localhost:8000/docs
```

Every slicing-related endpoint degrades gracefully without a real `orca-slicer` binary on `PATH` (`GET /profiles` returns empty, `GET /settings/schema` falls back, `POST /jobs` fails the job with a clear error) — useful for iterating on the API surface before M1's build is done.

## License / AGPL-3.0 notice

OrcaSlicer is licensed under AGPL-3.0. This project vendors a patched fork of it (see `vendor/orcaslicer`, tracked as a git submodule pointing at a public fork). If you interact with a hosted instance of this service over a network, you are entitled to the corresponding source code:

- Patched OrcaSlicer fork: _link added once the fork exists_
- This wrapper repository: _link added once pushed_

The exact commit SHA the running container was built from is exposed via the API's `/source` and `/version` endpoints.

## Layout

```
headless-orca/
├── vendor/orcaslicer/   # git submodule -> patched OrcaSlicer fork
├── docker/              # multi-stage Dockerfile + entrypoint
├── api/                 # FastAPI service
├── docs/                # architecture notes, AGPL compliance notes
└── scripts/             # smoke tests, helper scripts
```
