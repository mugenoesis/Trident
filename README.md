# headless-orca

A Docker container that runs [OrcaSlicer](https://github.com/OrcaSlicer/OrcaSlicer)'s slicing engine headlessly (no display), with source patches to harden its existing CLI mode, fronted by a FastAPI service that exposes slicing over HTTP.

Status: early scaffolding, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the implementation plan and milestones.

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
