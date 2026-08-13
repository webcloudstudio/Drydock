#!/bin/sh
# full_test.sh — scoring entry point. Do not filter, skip, or reinterpret.
set -eu
# The version setup_harness.sh installs. run_conformance.sh refuses a different one, so a
# passing verdict names a specific exam rather than whichever harness was on PATH.
TOML_TEST_VERSION="${TOML_TEST_VERSION:-v2.2.0}"
export TOML_TEST_VERSION
go build -o toml-decoder ./cmd/toml-decoder
DECODER="$PWD/toml-decoder" exec sh sources/run_conformance.sh
