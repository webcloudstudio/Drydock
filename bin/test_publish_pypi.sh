#!/usr/bin/env bash
set -euo pipefail

BDIR=/mnt/c/Users/barlo/projects/Drydock

source "$BDIR/.venv/bin/activate"

TESTPYPI_TOKEN="${TESTPYPI_TOKEN:-}"
if [[ -z "$TESTPYPI_TOKEN" && -f "$HOME/.pypirc" ]]; then
  TESTPYPI_TOKEN="$(awk '
    $0=="[testpypi]" {in_pypi=1; next}
    /^\[/ && $0!="[testpypi]" {in_pypi=0}
    in_pypi && $1=="password" {print $3; exit}
  ' "$HOME/.pypirc")"
fi

if [[ -z "$TESTPYPI_TOKEN" ]]; then
  echo "error: TESTPYPI_TOKEN is not set and no [testpypi] password was found in ~/.pypirc" >&2
  exit 2
fi

cd "$BDIR"
rm -rf dist/
uv build
unzip -l dist/drydock_sdd-*.whl
python3 scripts/check_wheel_rigging.py
uv publish --publish-url https://test.pypi.org/legacy/ --token "$TESTPYPI_TOKEN" dist/*
