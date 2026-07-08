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

VERSION="$(python3 - <<'PY'
import re, pathlib
text = pathlib.Path("src/drydock/__init__.py").read_text()
print(re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1))
PY
)"
TAG="v$VERSION"
echo "Publishing Drydock $VERSION (tag $TAG)"

if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  echo "error: tag $TAG already exists; bump __version__ in src/drydock/__init__.py" >&2
  exit 2
fi

rm -rf dist/
uv build
unzip -l dist/drydock_sdd-*.whl
python3 scripts/check_wheel_rigging.py
uv publish --skip-existing --token "$PYPI_TOKEN" dist/*

git tag -a "$TAG" -m "Drydock $VERSION alpha"
git push origin main
git push origin "$TAG"
