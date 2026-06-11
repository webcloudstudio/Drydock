#!/usr/bin/env bash
# CommandCenter Operation
# Name: Start Service
# Category: Operations
# Port: 8080
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8080}"

PROJECT_NAME="$(basename "$SCRIPT_DIR")"
echo "[$PROJECT_NAME] $(date +%H:%M) Starting"

if [[ -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  PYTHON=("$PROJECT_DIR/.venv/bin/python")
elif command -v python >/dev/null 2>&1; then
  PYTHON=(python)
elif command -v python3 >/dev/null 2>&1; then
  PYTHON=(python3)
elif command -v py >/dev/null 2>&1; then
  PYTHON=(py -3)
else
  echo "No Python launcher found. Install Python or put python/python3/py on PATH." >&2
  exit 1
fi

cd "$PROJECT_DIR"
echo "[$PROJECT_NAME] $(date +%H:%M) http://$HOST:$PORT"
exec "${PYTHON[@]}" -m uvicorn QuarterDeck.app:app --host "$HOST" --port "$PORT"
