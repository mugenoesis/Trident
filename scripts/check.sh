#!/usr/bin/env bash
# The full pre-commit gate for the web app and the API.
#   web: Biome (format, lint, cognitive complexity), unused code (knip), typecheck, build
#   api: black, ruff, pyright, cognitive complexity (complexipy), dead code (vulture), unit tests with a coverage floor
# Python runs through scripts/py.sh (a throwaway container) when the host has no Python 3.12+.
#
# Usage: scripts/check.sh            # everything
#        scripts/check.sh web        # only the web app
#        scripts/check.sh api        # only the API
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

step() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

if command -v ruff >/dev/null 2>&1 && command -v pyright >/dev/null 2>&1; then
  py() { (cd api && "$@"); }
else
  py() { "$ROOT/scripts/py.sh" "$@"; }
fi

check_web() {
  cd "$ROOT/web"
  step "web: biome (format, lint, complexity)"; npm run --silent lint
  step "web: unused code and dependencies (knip)"; npm run --silent knip
  step "web: typecheck and build"; npm run --silent build
  step "web: G-code parser (layers, heights, support, per slicer)"; npm run --silent test:parser
  cd "$ROOT"
}

check_api() {
  step "api: black"; py black --check app tests tests_slicer
  step "api: ruff"; py ruff check app tests tests_slicer
  step "api: pyright"; py pyright
  step "api: cognitive complexity (complexipy)"; py complexipy
  step "api: dead code (vulture)"; py vulture
  step "api: tests + coverage floor"; py pytest -q --cov --cov-fail-under=80
}

case "${1:-all}" in
  web) check_web ;;
  api) check_api ;;
  all) check_web; check_api ;;
  *) echo "usage: scripts/check.sh [web|api]" >&2; exit 2 ;;
esac

step "all checks passed"
