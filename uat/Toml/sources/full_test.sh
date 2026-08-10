#!/bin/sh
# full_test.sh — scoring entry point. Do not filter, skip, or reinterpret.
set -eu
go build -o toml-decoder ./cmd/toml-decoder
DECODER="$PWD/toml-decoder" exec sh sources/run_conformance.sh
