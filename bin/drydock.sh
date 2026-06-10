#!/usr/bin/env bash
# Source-tree convenience launcher — no business logic.
# Locates the repository root and runs: python -m drydock
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python -m drydock "$@"
