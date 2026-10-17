#!/usr/bin/env bash
# Runs the real-slicer API tests (api/tests_slicer) inside an image that has the engine, using the Python packages of
# scripts/py.sh's virtualenv (the image itself carries no pytest). The checkout's api/ is mounted, so the code under test
# is the checkout's, not the image's.
#
# Usage: scripts/slicer-tests.sh <image> [pytest args...]
#   scripts/slicer-tests.sh trident:cand-mat tests_slicer/test_resin_slice.py
# Run scripts/py.sh once first (it builds the virtualenv volume).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${1:?image with the engine}"
shift
exec docker run --rm -v trident-pyvenv:/venv:ro \
  -e PYTHONPATH=/venv/lib/python3.12/site-packages -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$ROOT/api:/work" -w /work "$IMAGE" python3 -m pytest -q -p no:cacheprovider "${@:-tests_slicer}"
