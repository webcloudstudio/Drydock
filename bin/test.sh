#!/usr/bin/env bash
# Test runner — activates the project venv and runs pytest.
# No business logic.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -d "$REPO_DIR/.venv" ]; then
    source "$REPO_DIR/.venv/bin/activate"
fi
exec python -m pytest "$@"
