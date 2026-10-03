# Trident slicer

A Docker container that runs [OrcaSlicer](https://github.com/OrcaSlicer/OrcaSlicer)'s slicing engine headlessly (no display), with source patches to harden its existing CLI mode, fronted by a FastAPI service (+ a web UI) that exposes slicing over HTTP.

Status: builds end-to-end and runs, including a real upload → preview → slice → download flow through the web UI. `docker build -f docker/Dockerfile -t headless-orca .` compiles the patched `vendor/orcaslicer` fork, builds the frontend, and assembles the runtime image; `docker run -p 8000:8000 headless-orca` serves both the API and the UI at `http://<host>:8000/` (Swagger at `/docs`). It's a responsive single page app, installable as a PWA on Android via "Add to Home Screen". See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design and remaining milestones (thumbnail rendering verification, direct-to-printer upload, etc.).

## Running the API locally (without OrcaSlicer)

```bash
cd api
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                       # all mocked/stubbed — no OrcaSlicer binary needed
.venv/bin/uvicorn app.main:app --reload  # http://localhost:8000/docs
```

Every slicing-related endpoint degrades gracefully without a real `orca-slicer` binary on `PATH` (`GET /profiles` returns empty, `GET /settings/schema` falls back, `POST /jobs` fails the job with a clear error) — useful for iterating on the API surface without building OrcaSlicer.

## License / AGPL-3.0 notice

OrcaSlicer is licensed under AGPL-3.0. This project vendors a patched fork of it (see `vendor/orcaslicer`, tracked as a git submodule pointing at a public fork). If you interact with a hosted instance of this service over a network, you are entitled to the corresponding source code:

- Patched OrcaSlicer fork: https://github.com/mugenoesis/OrcaSlicer/tree/headless-orca
- This wrapper repository: _link added once pushed_

The exact commit SHA the running container was built from is exposed via the API's `/source` and `/version` endpoints.

## Layout

```
headless-orca/
├── vendor/orcaslicer/   # git submodule -> patched OrcaSlicer fork
├── docker/              # multi-stage Dockerfile + entrypoint
├── api/                 # FastAPI service
├── web/                 # React/Vite frontend (see web/README.md)
├── docs/                # architecture notes, AGPL compliance notes
└── scripts/             # smoke tests, helper scripts
```
