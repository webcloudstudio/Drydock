#!/usr/bin/env bash
# jq.sh — run the `drydock uat jq` command sequence by hand, one step at a time.
set -u

PROJECT=jq
PROJECT_DIR=/mnt/c/Users/barlo/projects
DRYDOCK_DIR=$PROJECT_DIR/drydock
KIT=$DRYDOCK_DIR/uat/$PROJECT
SOURCE_DIR=$KIT/sources
INPUT_DIR=$KIT/inputs

export DRYDOCK_WORKSPACE=$DRYDOCK_DIR
export DRYDOCK_BUILD_DIRECTORY=$PROJECT_DIR
TARGET_DIR=$DRYDOCK_WORKSPACE/targets/$PROJECT
BUILD_DIR=$DRYDOCK_BUILD_DIRECTORY/$PROJECT

OPTS="--llm-provider codex --model gpt-5.6-luna"
#OPTS="--llm-provider claude --model sonnet"
REPAIR_ATTEMPTS=3
MAX_BUILD_PASSES=20

cd "$DRYDOCK_DIR" || exit 1

p() { echo; echo "=== NEXT: $*  — ENTER to run, Ctrl-C to stop"; read -r; echo "=== RUN $(date +%T): $*"; }
d() { echo "=== DONE $(date +%T)"; }

p "0. wipe $TARGET_DIR and $BUILD_DIR"
rm -rf "$TARGET_DIR" "$BUILD_DIR"; d

p "1. init"
drydock init $PROJECT $OPTS; d

p "2. seed METADATA, Compass, and the governed JSON inputs"
cp "$INPUT_DIR/METADATA.md" "$TARGET_DIR/METADATA.md"
drydock import $PROJECT "$INPUT_DIR/COMPASS.md" --format compass --force $OPTS
echo '{"full": ["sh", "sources/full_test.sh"]}' > "$TARGET_DIR/ACCEPTANCE.json"
echo '{"stories": []}'                          > "$TARGET_DIR/STORY_GUIDANCE.json"
ls -l "$TARGET_DIR"; d

p "3. import sources"
drydock import $PROJECT "$SOURCE_DIR" --format markdown $OPTS; d

p "4. analyze"
drydock analyze $PROJECT $OPTS; d

# analyze writes both of these itself, so the kit's copies go on after it, not before.
p "4a. copy the stack and Sea Trials over the analyze output"
cp "$INPUT_DIR/TECHNOLOGY_STACK.md" "$TARGET_DIR/TECHNOLOGY_STACK.md"
cp "$INPUT_DIR/SEA_TRIALS.md"       "$TARGET_DIR/SEA_TRIALS.md"
drydock status $PROJECT; d

p "5. plan"
drydock plan $PROJECT --override $OPTS; d

p "5a. plan verify (repair once, then stop)"
if ! drydock plan verify $PROJECT; then
    drydock plan repair $PROJECT $OPTS
    drydock plan verify $PROJECT || { echo "!! STOP: criteria still cannot run"; exit 1; }
fi
drydock status $PROJECT; d

# status --ready exits 0 while a pass can advance the Target. Non-zero before the first pass
# means the Manifest was never buildable — a halt, not a finished build.
passes=0
while drydock status $PROJECT --ready; do
    passes=$((passes + 1))
    [ "$passes" -gt "$MAX_BUILD_PASSES" ] && { echo "!! STOP: $MAX_BUILD_PASSES passes"; exit 1; }
    p "6.$passes build"
    drydock build $PROJECT --override --repair-attempts $REPAIR_ATTEMPTS $OPTS || {
        echo "!! STOP: build failed with work still on the frontier"; exit 1; }
    d
done
if [ "$passes" -eq 0 ]; then
    drydock status $PROJECT --check
    [ $? -eq 0 ] || { echo "!! STOP: nothing buildable"; cat "$TARGET_DIR/DECISIONS.json"; exit 1; }
fi

p "6z. status after build"
drydock status $PROJECT --check
drydock build status $PROJECT
drydock status $PROJECT; d

p "7. sh sources/full_test.sh in $BUILD_DIR"
( cd "$BUILD_DIR" && sh sources/full_test.sh ); echo "test exit: $?"; d

p "8. score"
drydock score ac $PROJECT $OPTS
drydock score release $PROJECT $OPTS; d
