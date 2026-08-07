#!/usr/bin/env bash
#
# Unattended release regression build for the ReadingList Target.
#
# Clears the Target and its build directory, then drives the full pipeline with no prompts.
# Any non-zero exit from any drydock command aborts the run. Analyze questionnaire gates are
# waived with --override; a blocked analysis is not waivable and stops the run, because on a
# fixture source we control that verdict is a regression signal.
#
# Paths come from `drydock config env` so this script carries no hardcoded workspace layout and
# can be copied for another Target by changing PROJECT and SOURCE.

set -euo pipefail

PROJECT=ReadingList
HELPERS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$HELPERS_DIR/reading-list.md"
SOURCE_MASTER="$HELPERS_DIR/reading-list-orig.md"
OPTS=(--llm-provider codex --model gpt-5.6-luna)

# A build that cannot advance already exits non-zero, so this only bounds a loop that keeps
# making progress far past any plausible Manifest size.
MAX_BUILD_PASSES=${MAX_BUILD_PASSES:-25}

fail() {
    echo "FAIL: $PROJECT — $*" >&2
    exit 1
}

eval "$(drydock config env "$PROJECT")"

echo "== $PROJECT regression build =="
echo "   target dir : $DRYDOCK_TARGET_DIR"
echo "   build dir  : $DRYDOCK_TARGET_BUILD_DIR"
echo "   source     : $SOURCE"

# On WSL/DrvFs, a directory can enter a zombie state where stat returns ENOENT
# but mkdir returns EEXIST. cmd.exe rmdir resolves it when plain rm cannot.
rm -rf "$DRYDOCK_TARGET_DIR"
rm -rf "$DRYDOCK_TARGET_BUILD_DIR"

# Restore the pristine source; a prior run's refit may have rewritten the working copy.
cp "$SOURCE_MASTER" "$SOURCE"

drydock init    "$PROJECT" "${OPTS[@]}"
drydock import  "$PROJECT" "$SOURCE" --format markdown "${OPTS[@]}"
drydock analyze "$PROJECT" "${OPTS[@]}"
drydock plan    "$PROJECT" --override "${OPTS[@]}"

passes=0
while drydock status "$PROJECT" --ready; do
    passes=$((passes + 1))
    if [ "$passes" -gt "$MAX_BUILD_PASSES" ]; then
        fail "exceeded $MAX_BUILD_PASSES build passes without completing"
    fi
    echo "== build pass $passes =="
    drydock build "$PROJECT" --override "${OPTS[@]}"
done

# The real assertion. --ready going false only means the loop stopped; --check proves the Target
# actually finished (0 complete, 1 work remains, 2 blocked).
drydock status "$PROJECT" --check

echo "PASS: $PROJECT regression build complete in $passes build pass(es)"
