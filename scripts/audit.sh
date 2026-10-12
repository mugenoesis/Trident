#!/usr/bin/env bash
# Dependency vulnerability audit.
#   1. What ships (the web app's runtime dependencies and the API's): must have NO known vulnerabilities.
#   2. Build and development tools: reported for information, never fails.
# Needs network access (npm registry, PyPI).
#
# Usage: scripts/audit.sh
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

printf '\n\033[1m== web: shipped dependencies (must be clean) ==\033[0m\n'
(cd web && npm audit --omit=dev --audit-level=low)
web=$?

printf '\n\033[1m== web: everything, including build tools (for information) ==\033[0m\n'
(cd web && npm audit) || true

printf '\n\033[1m== api: runtime dependencies (must be clean) ==\033[0m\n'
if command -v pip-audit >/dev/null 2>&1; then
  (cd api && pip-audit --skip-editable .)
else
  scripts/py.sh pip-audit --skip-editable .
fi
api=$?

exit $((web | api))
