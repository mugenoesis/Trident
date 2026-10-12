#!/usr/bin/env bash
# Checks the Docker image's recipe in throwaway containers (nothing running is touched):
#   1. hadolint reads docker/Dockerfile for mistakes and bad practice;
#   2. trivy scans the Dockerfile for risky configuration (HIGH and CRITICAL fail).
# The image itself is not built or scanned here: a full build compiles OrcaSlicer and takes a long time.
#
# Usage: scripts/docker-lint.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

step() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

step "hadolint: docker/Dockerfile"
docker run --rm -i hadolint/hadolint hadolint --failure-threshold warning - < docker/Dockerfile
echo "Dockerfile is clean"

step "trivy: Dockerfile configuration"
docker run --rm -v "$ROOT/docker:/scan:ro" -v trident-trivy-cache:/root/.cache aquasec/trivy:latest \
  config --severity HIGH,CRITICAL --exit-code 1 /scan

printf '\nDocker checks passed\n'
