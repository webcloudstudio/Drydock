#!/bin/sh
# Run the upstream toml-test conformance suite against the built decoder.
#
# Imported sources land in sources/ inside the application directory, so this is
# normally invoked as `sh sources/run_conformance.sh` from that directory.
#
# Usage:
#   DECODER=./toml-decoder sh sources/run_conformance.sh                        # full suite
#   DECODER=./toml-decoder sh sources/run_conformance.sh -run 'valid/string/*'  # one group
#   DECODER=./toml-decoder sh sources/run_conformance.sh -json                  # machine-readable
#
# Environment:
#   DECODER    decoder command. Required — this harness is language-neutral and
#              deliberately has no default implementation language.
#   TOML_TEST  absolute path to the toml-test binary (default: found on PATH)
#
# Exit code is the harness exit code: 0 only when every test passes.

set -u

if [ -z "${DECODER:-}" ]; then
    echo "error: DECODER is not set; give the command that runs your decoder." >&2
    exit 2
fi

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

# The suite's identity is part of the verdict. Without this, "the authoritative suite passed"
# names no particular suite: whichever toml-test happened to be on PATH decided the run, and a
# different version on a different machine is a different exam. Recorded always, and enforced
# when the caller states which version it expects.
HARNESS_VERSION="$("${HARNESS}" -version 2>/dev/null | head -n 1 || true)"
echo "harness: ${HARNESS} ${HARNESS_VERSION:-(version unknown)}" >&2
if [ -n "${TOML_TEST_VERSION:-}" ] && [ -n "${HARNESS_VERSION}" ]; then
    case "${HARNESS_VERSION}" in
        *"${TOML_TEST_VERSION}"*) ;;
        *)
            echo "error: harness is ${HARNESS_VERSION}, expected ${TOML_TEST_VERSION}." >&2
            echo "Run: sh sources/setup_harness.sh" >&2
            exit 2
            ;;
    esac
fi

NO_COLOR=1 exec "${HARNESS}" test -toml 1.0 -decoder "${DECODER}" "$@"
