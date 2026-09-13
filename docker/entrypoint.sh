#!/usr/bin/env bash
# Entrypoint for the headless-orca runtime image.
#
# Everything — the API server and any ad-hoc `orca-slicer` invocation
# (e.g. scripts/smoke_test.sh's `docker run <image> orca-slicer ...`) —
# runs under xvfb-run so GLFW's X11/GLX backend has a display to attach
# to for thumbnail rendering (docs/ARCHITECTURE.md).
set -euo pipefail

mkdir -p "${ORCA_API_MODELS_DIR:-/data/models}" \
         "${ORCA_API_OUTPUT_DIR:-/data/output}" \
         "${ORCA_API_ORCASLICER_DATADIR:-/data/orcaslicer-datadir}"

if [[ "${1:-}" == "serve" ]]; then
    shift
    exec xvfb-run -a --server-args="-screen 0 640x480x24" \
        /opt/api/.venv/bin/uvicorn app.main:app \
        --app-dir /opt/api \
        --host 0.0.0.0 \
        --port 8000 \
        "$@"
fi

# Anything else (e.g. `orca-slicer --help`, `--slice ...` for the smoke
# test) is run directly, still under xvfb-run.
exec xvfb-run -a --server-args="-screen 0 640x480x24" "$@"
