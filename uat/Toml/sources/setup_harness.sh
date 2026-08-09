#!/bin/sh
# One-time installation of the upstream toml-test conformance harness.
#
# Requires network access and a Go toolchain of at least 1.22 — the same floor
# stack/go.md sets for the deliverable. The Go shipped by apt on Debian and
# Ubuntu is frequently older and will fail; install the official tarball instead:
#
#     curl -sL https://go.dev/dl/go1.24.6.linux-amd64.tar.gz -o go.tgz
#     sudo tar -C /usr/local -xzf go.tgz
#     export PATH=/usr/local/go/bin:$PATH
#
# Usage:
#   sh sources/setup_harness.sh              # install to $HOME/.local/bin
#   GOBIN=/usr/local/bin sh sources/setup_harness.sh

set -eu

TOML_TEST_VERSION=v2.2.0
GOBIN="${GOBIN:-$HOME/.local/bin}"

if ! command -v go >/dev/null 2>&1; then
    echo "error: no go toolchain on PATH; see the header of this script" >&2
    exit 1
fi

echo "go:      $(go version)"
echo "target:  ${GOBIN}/toml-test"
echo "version: ${TOML_TEST_VERSION}"

mkdir -p "${GOBIN}"
GOBIN="${GOBIN}" go install \
    "github.com/toml-lang/toml-test/v2/cmd/toml-test@${TOML_TEST_VERSION}"

echo
"${GOBIN}/toml-test" version

case ":${PATH}:" in
    *":${GOBIN}:"*) ;;
    *) echo
       echo "warning: ${GOBIN} is not on PATH. Add it, or export"
       echo "         TOML_TEST=${GOBIN}/toml-test before running the suite." ;;
esac
