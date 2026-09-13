#!/usr/bin/env bash
# End-to-end check for M1 (docs/ARCHITECTURE.md): build the image, run
# `orca-slicer --help`, then slice the bundled sample model and inspect
# result.json for return_code: 0.
#
# Usage: scripts/smoke_test.sh [image-tag]
set -euo pipefail

IMAGE="${1:-headless-orca:local}"
SAMPLE_MODEL="resources/handy_models/OrcaBadge.3mf"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

echo "== 1/3: orca-slicer --help =="
docker run --rm "$IMAGE" orca-slicer --help

echo "== 2/3: slice bundled sample model =="
mkdir -p "$WORKDIR/output"
docker run --rm \
    -v "$WORKDIR/output:/data/output" \
    "$IMAGE" \
    orca-slicer \
    --slice 0 \
    --outputdir /data/output \
    "/opt/orcaslicer/${SAMPLE_MODEL}"

echo "== 3/3: check result.json =="
RESULT_JSON="$WORKDIR/output/result.json"
if [[ ! -f "$RESULT_JSON" ]]; then
    echo "FAIL: result.json not written to $WORKDIR/output" >&2
    exit 1
fi

RETURN_CODE="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['return_code'])" "$RESULT_JSON")"
if [[ "$RETURN_CODE" != "0" ]]; then
    echo "FAIL: result.json return_code=$RETURN_CODE" >&2
    cat "$RESULT_JSON" >&2
    exit 1
fi

echo "PASS: sliced ${SAMPLE_MODEL}, return_code=0"

echo "== bonus: grep logs for GLFW thumbnail backend status =="
docker run --rm "$IMAGE" \
    orca-slicer --slice 0 --outputdir /tmp/thumb-check "/opt/orcaslicer/${SAMPLE_MODEL}" 2>&1 \
    | grep -E "glfwInit Success|Failed to create GLFW window" || true
