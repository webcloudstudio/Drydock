#!/usr/bin/env bash
set -euo pipefail

BDIR=/mnt/c/Users/barlo/projects/Drydock

source "$BDIR/.venv/bin/activate"

PYPI_TOKEN="${PYPI_TOKEN:-}"
if [[ -z "$PYPI_TOKEN" && -f "$HOME/.pypirc" ]]; then
  PYPI_TOKEN="$(awk '
    $0=="[pypi]" {in_pypi=1; next}
    /^\[/ && $0!="[pypi]" {in_pypi=0}
    in_pypi && $1=="password" {print $3; exit}
  ' "$HOME/.pypirc")"
fi

if [[ -z "$PYPI_TOKEN" ]]; then
  echo "error: PYPI_TOKEN is not set and no [pypi] password was found in ~/.pypirc" >&2
  exit 2
fi

cd "$BDIR"
rm -rf dist/
uv build
unzip -l dist/drydock_sdd-*.whl
python3 scripts/check_wheel_rigging.py
uv publish --token "$PYPI_TOKEN" dist/*
