#!/usr/bin/env bash
# DEPRECATED: Use 'drydock document assemble [--source <path>] [--output <path>]' instead.
# Build Drydock's authoritative Blueprint into docs/index.html.
# No business logic.
set -euo pipefail
echo "WARNING: build_documentation.sh is deprecated. Use: drydock document assemble [--source <path>] [--output <path>]" >&2
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -d "$REPO_DIR/.venv" ]; then
    source "$REPO_DIR/.venv/bin/activate"
fi
exec python -m drydock.build_documentation "$@"
