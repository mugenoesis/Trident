#!/usr/bin/env bash
# Entrypoint for the headless-orca runtime image.
#
# Everything — the API server and any ad-hoc `orca-slicer` invocation
# (e.g. scripts/smoke_test.sh's `docker run <image> orca-slicer ...`) —
# runs with an Xvfb display so GLFW's X11/GLX backend has one to attach to
# for thumbnail rendering (docs/ARCHITECTURE.md).
#
# Not using `xvfb-run`: it signals readiness by having Xvfb send SIGUSR1 to
# its parent shell, which this image's Xvfb build never delivers as PID 1 in
# a container (observed hanging indefinitely with Xvfb itself running fine),
# and this xvfb-run version's `--wait` flag is a no-op with no polling
# fallback. Start Xvfb directly and poll for its socket instead.
set -euo pipefail

mkdir -p "${ORCA_API_MODELS_DIR:-/data/models}" \
         "${ORCA_API_OUTPUT_DIR:-/data/output}" \
         "${ORCA_API_ORCASLICER_DATADIR:-/data/orcaslicer-datadir}"

DISPLAY_NUM=99
export DISPLAY=":${DISPLAY_NUM}"

Xvfb "${DISPLAY}" -screen 0 640x480x24 -nolisten tcp -ac &
XVFB_PID=$!
trap 'kill "$XVFB_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 50); do
    [[ -e "/tmp/.X11-unix/X${DISPLAY_NUM}" ]] && break
    kill -0 "$XVFB_PID" 2>/dev/null || { echo "entrypoint: Xvfb exited before becoming ready" >&2; exit 1; }
    sleep 0.1
done
if [[ ! -e "/tmp/.X11-unix/X${DISPLAY_NUM}" ]]; then
    echo "entrypoint: Xvfb did not become ready within 5s" >&2
    exit 1
fi

if [[ "${1:-}" == "serve" ]]; then
    shift
    exec /opt/api/.venv/bin/uvicorn app.main:app \
        --app-dir /opt/api \
        --host 0.0.0.0 \
        --port 8000 \
        "$@"
fi

# Anything else (e.g. `orca-slicer --help`, `--slice ...` for the smoke test)
exec "$@"
