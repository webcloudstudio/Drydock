#!/usr/bin/env bash
# Build Drydock's authoritative Blueprint into docs/index.html.
# No business logic.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -d "$REPO_DIR/.venv" ]; then
    source "$REPO_DIR/.venv/bin/activate"
fi
exec python -m drydock.build_documentation "$@"
