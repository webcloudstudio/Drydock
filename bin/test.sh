#!/usr/bin/env bash
# Test runner — activates the project venv, gates on lint and format, runs pytest.
# Mirrors the CI verification order so failures surface locally before push.
# No business logic.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -d "$REPO_DIR/.venv" ]; then
    source "$REPO_DIR/.venv/bin/activate"
fi
ruff check .
ruff format --check .
exec python -m pytest "$@"
