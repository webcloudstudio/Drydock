#!/usr/bin/env bash
set -euo pipefail

TEST_BED="$(mktemp -d "${TMPDIR:-/tmp}/drydock-test.XXXXXX")"
trap 'rm -rf "$TEST_BED"' EXIT

EXISTING_DRYDOCK="$(command -v drydock || true)"

export UV_TOOL_DIR="$TEST_BED/tools"
export UV_TOOL_BIN_DIR="$TEST_BED/bin"
export XDG_CONFIG_HOME="$TEST_BED/config"
export PATH="$UV_TOOL_BIN_DIR:$PATH"

mkdir -p "$UV_TOOL_BIN_DIR" "$XDG_CONFIG_HOME" "$TEST_BED/drydock"
cd "$TEST_BED"

echo "== Drydock published-build smoke test =="
echo "Test bed:       $TEST_BED"
echo "Existing drydock: ${EXISTING_DRYDOCK:-not found}"

if [[ -n "${DRYDOCK_WORKSPACE:-}" ]]; then
    echo "DRYDOCK_WORKSPACE is already set: $DRYDOCK_WORKSPACE"
    exit 1
fi

if [[ -n "${DRYDOCK_BUILD_DIRECTORY:-}" ]]; then
    echo "DRYDOCK_BUILD_DIRECTORY is already set: $DRYDOCK_BUILD_DIRECTORY"
    exit 1
fi

uv tool install --force drydock-sdd

echo
echo "Executable:     $(command -v drydock)"
echo "Version:"
drydock --version

echo
echo "Help:"
drydock --help >/dev/null
echo "drydock --help: PASS"

drydock config set drydock_workspace "$TEST_BED/drydock"
drydock config set drydock_build_directory "$TEST_BED"

echo
echo "Configuration:"
drydock config show

echo
echo "Empty workspace status:"
drydock status
echo "drydock status: PASS"

echo
echo "Initialize temporary Target:"
drydock init SmokeTest
drydock status
echo "drydock init/status: PASS"

echo
echo "Smoke test: PASS"
echo "Test bed will be removed: $TEST_BED"
