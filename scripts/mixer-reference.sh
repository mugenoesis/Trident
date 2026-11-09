#!/usr/bin/env bash
# Regenerates what the Python colour mixer (api/app/colour_mixer.py) is built from and checked against, by compiling the
# engine's own header (vendor/orcaslicer/src/libslic3r/FilamentMixerModel.hpp, MIT, Justin Hayes) in a throwaway container:
#   api/app/mixer_model/filament_mixer_model.json         the polynomial's powers, coefficients and intercepts
#   api/tests/fixtures/colour_mixer_reference.json  what the header computes for a fixed set of inputs
# Run it again after the engine submodule moves; a changed model shows up as a diff in those two files.
#
# Usage: scripts/mixer-reference.sh [builder-image]     (default: any image with g++, python:3.12 works: apt installs it)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${1:-${MIXER_BUILDER_IMAGE:-trident:builder-fresh}}"

docker run --rm -v "$ROOT:/work" -w /tmp "$IMAGE" bash -c '
  set -e
  command -v g++ >/dev/null || { apt-get update -qq && apt-get install -y -qq g++ >/dev/null; }
  g++ -std=c++17 -O1 -I/work/vendor/orcaslicer/src/libslic3r -o mixer_reference /work/scripts/mixer_reference.cpp
  ./mixer_reference model > /work/api/app/mixer_model/filament_mixer_model.json
  ./mixer_reference reference > /work/api/tests/fixtures/colour_mixer_reference.json
'
echo "wrote api/app/mixer_model/filament_mixer_model.json and api/tests/fixtures/colour_mixer_reference.json"
