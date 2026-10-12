#!/usr/bin/env bash
# Runs a command in the API's Python environment inside a throwaway container, for hosts with no Python
# (the dev host is one). The virtualenv and pip cache live in Docker volumes, so only the first run is slow.
# CI does not use this: it installs the same tools straight onto the runner.
#
# Usage: scripts/py.sh black --check app tests
#        scripts/py.sh pytest -q
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${PY_IMAGE:-python:3.12-slim}"

docker volume create trident-pyvenv >/dev/null
docker volume create trident-pipcache >/dev/null
exec docker run --rm -i \
  -v "$ROOT:/work" -v trident-pyvenv:/venv -v trident-pipcache:/root/.cache \
  -w /work/api -e PATH=/venv/bin:/usr/local/bin:/usr/bin:/bin -e PYTHONDONTWRITEBYTECODE=1 \
  "$IMAGE" bash -c '
    # Reinstall only when pyproject.toml changed since the venv was built.
    stamp=$(md5sum pyproject.toml | cut -d" " -f1)
    if [ ! -x /venv/bin/python ] || [ "$(cat /venv/.stamp 2>/dev/null)" != "$stamp" ]; then
      python -m venv /venv >&2
      /venv/bin/pip install -q --disable-pip-version-check -e ".[dev]" >&2
      echo "$stamp" > /venv/.stamp
    fi
    exec "$@"' -- "$@"
