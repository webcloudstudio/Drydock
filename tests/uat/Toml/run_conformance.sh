#!/bin/sh
# Run the upstream toml-test conformance suite against the built decoder.
#
# Imported sources land in sources/ inside the application directory, so this is
# normally invoked as `sh sources/run_conformance.sh` from that directory.
#
# Usage:
#   sh sources/run_conformance.sh                        # full TOML 1.0 suite
#   sh sources/run_conformance.sh -run 'valid/string/*'  # one feature group
#   sh sources/run_conformance.sh -json                  # machine-readable report
#
# Environment:
#   DECODER    decoder command (default: "python3 mytoml.py")
#   TOML_TEST  absolute path to the toml-test binary (default: found on PATH)
#
# Exit code is the harness exit code: 0 only when every test passes.

set -u

DECODER="${DECODER:-python3 mytoml.py}"

if [ -n "${TOML_TEST:-}" ] && [ -x "${TOML_TEST}" ]; then
    HARNESS="${TOML_TEST}"
elif command -v toml-test >/dev/null 2>&1; then
    HARNESS="$(command -v toml-test)"
else
    cat >&2 <<'EOF'
error: toml-test not found.

Install the harness once:

    sh sources/setup_harness.sh

or set TOML_TEST to an existing binary:

    TOML_TEST=/path/to/toml-test sh sources/run_conformance.sh
EOF
    exit 127
fi

NO_COLOR=1 exec "${HARNESS}" test -toml 1.0 -decoder "${DECODER}" "$@"
