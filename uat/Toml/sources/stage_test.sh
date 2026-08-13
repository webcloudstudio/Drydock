#!/bin/sh
# stage_test.sh — governed stage gate. Runs one slice of the authoritative suite.
#
# Same contract as full_test.sh, scoped to the cases a single story owns: build the decoder,
# then run the installed toml-test suite over the pattern given as $1. Exit status is the
# verdict and the whole verdict. Do not filter, skip, or reinterpret.
set -eu
if [ $# -ne 1 ]; then
  echo "usage: stage_test.sh <toml-test -run pattern>" >&2
  exit 2
fi
TOML_TEST_VERSION="${TOML_TEST_VERSION:-v2.2.0}"
export TOML_TEST_VERSION
go build -o toml-decoder ./cmd/toml-decoder
DECODER="$PWD/toml-decoder" exec sh sources/run_conformance.sh -run "$1"
