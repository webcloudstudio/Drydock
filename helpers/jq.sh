#!/usr/bin/env bash
# jq.sh — drive the jq UAT fixture interactively, one milestone at a time.
#
# Reproduces the command sequence `drydock uat jq` runs, with the same inputs and
# the same order, so a failure here is the failure the harness would have hit.
# Press ENTER at each pause; Ctrl-C to stop.

set -u

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
export PROJECT=jq
export PROJECT_DIR=/mnt/c/Users/barlo/projects
export DRYDOCK_DIR=$PROJECT_DIR/drydock
export KIT=$DRYDOCK_DIR/uat/$PROJECT

# Where the fixture's files come from.
export SOURCE_DIR=$KIT/sources          # imported User Sources, read-only
export INPUT_DIR=$KIT/inputs            # lifecycle overrides copied over the Target

# Where Drydock works.
export DRYDOCK_WORKSPACE=$DRYDOCK_DIR                    # Targets live in $WORKSPACE/targets
export DRYDOCK_BUILD_DIRECTORY=$PROJECT_DIR              # application root is $BUILD_DIR/$PROJECT
export TARGET_DIR=$DRYDOCK_WORKSPACE/targets/$PROJECT
export BUILD_DIR=$DRYDOCK_BUILD_DIRECTORY/$PROJECT

export OPTS="--llm-provider codex --model gpt-5.6-luna"
#export OPTS="--llm-provider claude --model sonnet"

export REPAIR_ATTEMPTS=3
export MAX_BUILD_PASSES=20

cd "$DRYDOCK_DIR" || exit 1

pause() { echo; echo "===== $* ====="; read -r; }
run() { echo "+ $*"; "$@"; }

# ---------------------------------------------------------------------------
# 0. Clean slate
# ---------------------------------------------------------------------------
date
pause "0. remove $TARGET_DIR and $BUILD_DIR"
rm -rf "$TARGET_DIR" "$BUILD_DIR"

# ---------------------------------------------------------------------------
# 1. init
# ---------------------------------------------------------------------------
pause "1. drydock init"
run drydock init $PROJECT $OPTS

# ---------------------------------------------------------------------------
# 2. Seed the lifecycle inputs
#
# These are copied over the Target, not imported. The Compass comes from
# inputs/COMPASS.md — it is an input, not a source, and is never derived from
# INSTRUCTIONS.md. ACCEPTANCE.json is the governed release gate; STORY_GUIDANCE
# is empty for this fixture but the file must exist.
# ---------------------------------------------------------------------------
pause "2. seed inputs into $TARGET_DIR"
run cp "$INPUT_DIR/COMPASS.md"           "$TARGET_DIR/COMPASS.md"
run cp "$INPUT_DIR/TECHNOLOGY_STACK.md"  "$TARGET_DIR/TECHNOLOGY_STACK.md"
run cp "$INPUT_DIR/SEA_TRIALS.md"        "$TARGET_DIR/SEA_TRIALS.md"
echo '{"full": ["sh", "sources/full_test.sh"]}' > "$TARGET_DIR/ACCEPTANCE.json"
echo '{"stories": []}'                          > "$TARGET_DIR/STORY_GUIDANCE.json"
ls -l "$TARGET_DIR"

# ---------------------------------------------------------------------------
# 3. import — the whole source bundle in one pass
#
# INSTRUCTIONS.md jq-manual.txt jq.test exclusions.txt parser.y lexer.l
# builtin.jq run_conformance.py full_test.sh
# ---------------------------------------------------------------------------
pause "3. drydock import from $SOURCE_DIR"
run drydock import $PROJECT "$SOURCE_DIR" --format markdown $OPTS
run drydock status $PROJECT

# ---------------------------------------------------------------------------
# 4. analyze
# ---------------------------------------------------------------------------
pause "4. drydock analyze"
run drydock analyze $PROJECT $OPTS
run drydock status $PROJECT

# ---------------------------------------------------------------------------
# 5. plan, then verify the acceptance criteria can actually run
#
# plan verify is deterministic and free. Pay for plan repair only when it fails.
# A second failure means the criteria still cannot run: stop, do not build.
# ---------------------------------------------------------------------------
pause "5. drydock plan"
run drydock plan $PROJECT --override $OPTS

pause "5a. drydock plan verify"
if ! drydock plan verify $PROJECT; then
    echo "!! criteria cannot run — one repair pass"
    run drydock plan repair $PROJECT $OPTS
    if ! drydock plan verify $PROJECT; then
        echo "!! STOP: acceptance criteria still cannot run after one repair pass"
        exit 1
    fi
fi

pause "5b. status after plan"
run drydock build status $PROJECT
run drydock status $PROJECT
run drydock status

# ---------------------------------------------------------------------------
# 6. build loop
#
# `status --ready` exits 0 while a pass can advance the Target and 1 once it
# cannot. Non-zero BEFORE the first pass means the Manifest was never buildable
# — a story parked at blocked/questions behind a blocking DECISIONS.json record
# — which is a halt, not a finished build.
# ---------------------------------------------------------------------------
pause "6. build loop (up to $MAX_BUILD_PASSES passes)"
passes=0
while true; do
    if ! drydock status $PROJECT --ready; then
        if [ "$passes" -eq 0 ]; then
            echo "!! nothing buildable before the first pass"
            drydock status $PROJECT --check
            case $? in
                0) echo "   Target is already complete." ;;
                2) echo "!! STOP: blocked. Answer the blocking records:"
                   cat "$TARGET_DIR/DECISIONS.json"; exit 1 ;;
                *) echo "!! STOP: no buildable frontier. Open DECISIONS.json and MANIFEST.md."
                   cat "$TARGET_DIR/DECISIONS.json"; exit 1 ;;
            esac
        fi
        break
    fi
    passes=$((passes + 1))
    if [ "$passes" -gt "$MAX_BUILD_PASSES" ]; then
        echo "!! STOP: $MAX_BUILD_PASSES passes without emptying the frontier"
        exit 1
    fi
    pause "6.$passes drydock build"
    run drydock build $PROJECT --override --repair-attempts $REPAIR_ATTEMPTS $OPTS || {
        echo "!! build exited non-zero with work still on the frontier"
        exit 1
    }
done

pause "6z. status after build"
run drydock status $PROJECT --check
run drydock build status $PROJECT
run drydock status $PROJECT
run drydock status

# ---------------------------------------------------------------------------
# 7. the governed scoring run
#
# Runs from the application root. full_test.sh sets JQ itself.
# ---------------------------------------------------------------------------
pause "7. sh sources/full_test.sh in $BUILD_DIR"
if [ -d "$BUILD_DIR" ]; then
    ( cd "$BUILD_DIR" && run sh sources/full_test.sh )
    echo "test exit: $?"
else
    echo "!! no application root at $BUILD_DIR — the build produced nothing"
fi

# ---------------------------------------------------------------------------
# 8. scores
# ---------------------------------------------------------------------------
pause "8. drydock score"
run drydock score ac $PROJECT $OPTS
run drydock score release $PROJECT $OPTS

date
echo "done."
