#!/usr/bin/env bash
set -euo pipefail

TEST_BED="$(mktemp -d "${TMPDIR:-/tmp}/drydock-test.XXXXXX")"
trap 'rm -rf "$TEST_BED"' EXIT

EXISTING_DRYDOCK="$(command -v drydock || true)"

export UV_TOOL_DIR="$TEST_BED/tools"
export UV_TOOL_BIN_DIR="$TEST_BED/bin"
export XDG_CONFIG_HOME="$TEST_BED/config"
export PATH="$UV_TOOL_BIN_DIR:$PATH"

mkdir -p "$UV_TOOL_BIN_DIR" "$XDG_CONFIG_HOME"
cd "$TEST_BED"

echo "== Drydock published-build smoke test =="
echo "Test bed:       $TEST_BED"
echo "Test executable directory: $UV_TOOL_BIN_DIR"
echo "Existing drydock: ${EXISTING_DRYDOCK:-not found}"

uv tool install --force drydock-sdd

echo
echo "Executable:     $(command -v drydock)"
echo "Version:"
drydock --version
echo
echo "Configuration:"
drydock config show
echo
echo "Help:"
drydock --help >/dev/null
echo "drydock --help: PASS"

echo
echo "Workspace status (expected configuration error):"
if drydock status; then
    echo "drydock status: unexpected success"
    exit 1
else
    echo "drydock status: expected failure in the empty test workspace"
fi

echo
echo "Smoke test: PASS"
echo "Test bed will be removed: $TEST_BED"
