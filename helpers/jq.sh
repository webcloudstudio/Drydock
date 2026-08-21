#
# jq.sh
#
set -ux
export PROJECT=jq_2
export PROJECT_DIR=/mnt/c/Users/barlo/projects
export KIT=$PROJECT_DIR/drydock/uat/$PROJECT
export KIT=$PROJECT_DIR/drydock/uat/jq
export DRYDOCK_WORKSPACE=$PROJECT_DIR/drydock
export DRYDOCK_BUILD_DIRECTORY=$PROJECT_DIR
export TARGET=$DRYDOCK_WORKSPACE/targets/$PROJECT

# current price differences for Claude:  Sonnet costing exactly 2x Haiku and Opus costing 5x Haiku (or 2.5x Sonnet)
# current price differences for Codex:   gpt-5.6-luna=1, gpt-5.6-terra=10, gpt-5.6-sol=25
export OPTS="--llm-provider codex --model gpt-5.6-luna"
#export OPTS="--llm-provider claude --model sonnet"
export OPTS="--llm-provider claude --model haiku"

# The eleven workflow states, in ladder order, and what records each. A `*` marks a mutating
# state: reaching it voids every state above it
#
#    1  INITIALIZED                drydock init
#    2  IMPORTED                   drydock import
#    3  ANALYZED               *   drydock analyze
#    4  PLAN CREATED           *   drydock plan
#    5  PLAN REPAIRED          *   drydock plan repair
#    6  BUILDING               *   drydock build          (on entry, every pass)
#    7  BUILT                  *   drydock build          (on exit, pass or fail)
#    8  LLM ACCEPTANCE CHECKS OK   drydock score ac
#    9  SCORE BUILD                drydock score build
#   10  SCORE RELEASE              drydock score release
#   11  FINALIZED                  drydock score report
#

cd $DRYDOCK_WORKSPACE
date
rm -rf $TARGET $PROJECT_DIR/$PROJECT
read
drydock init $PROJECT $OPTS
# project status = INITIALIZED, OK

# METADATA and COMPASS go on before analyze; analyze only fills fields it finds blank.
# The Compass is copied, never imported. `--format compass` is the one import format that runs an
# LLM: it rewrites the document and drops sections. `state: authored` is what `drydock uat` writes
# for a kit-supplied Compass; it stops analyze appending an imported source to the author's rules.
cp $KIT/inputs/METADATA.md $TARGET/METADATA.md
cp $KIT/inputs/COMPASS.md  $TARGET/COMPASS.md
printf 'state: authored\n' > $TARGET/.drydock-compass
echo '{"full": ["sh", "sources/full_test.sh"]}' > $TARGET/ACCEPTANCE.json
echo '{"stories": []}'                          > $TARGET/STORY_GUIDANCE.json
read
drydock import $PROJECT $KIT/sources --format markdown $OPTS
# project status = IMPORTED, OK

drydock analyze $PROJECT $OPTS
# project status = ANALYZED, OK

# analyze writes these two itself, so the kit copies go on after it.
cp $KIT/inputs/TECHNOLOGY_STACK.md $TARGET/TECHNOLOGY_STACK.md
cp $KIT/inputs/SEA_TRIALS.md       $TARGET/SEA_TRIALS.md
drydock status $PROJECT

read
drydock plan $PROJECT --override $OPTS
# project status = PLAN CREATED, OK

if ! drydock plan verify $PROJECT; then
  # project status = PLAN CREATED, ERROR  detail: "N criteria cannot run"

  drydock plan repair $PROJECT $OPTS
  # project status = PLAN REPAIRED, OK  (a repair that exits nonzero records it as ERROR)

  if ! drydock plan verify $PROJECT; then
    # project status = PLAN REPAIRED, ERROR  detail: "N criteria cannot run"
    echo "criteria still cannot run — aborting"
    exit 1
  fi
fi
drydock status $PROJECT
read

n=1; max=20
while drydock status $PROJECT --ready; do
  echo "************************"
  echo "* RUNNING BUILD ATTEMPT $n"
  echo "************************"

  # Every pass records BUILDING on entry, then BUILT on exit whatever the outcome.
  # BUILDING voids BUILT and every score above it: a new pass is new evidence.
  if ! drydock build $PROJECT --override $OPTS; then
    # project status = BUILT, ERROR
    #   detail: "N step(s) failed" | "N block(s) stalled" | "build did not complete"
    echo "build failed with work left — aborting"
    exit 1
  fi

  # project status = BUILT, OK  (this pass finished; the loop re-enters if work remains)
  n=$((n+1))
  if [ "$n" -ge "$max" ]; then
    # project status = BUILT, OK — the iteration cap is this script's, not the machine's.
    echo "hit $max build iterations — aborting"
    exit 1
  fi
done
# project status = BUILT, OK  (recorded by the final pass above, not by leaving the loop)

drydock status $PROJECT --check
drydock build status $PROJECT
read
( cd $PROJECT_DIR/$PROJECT && sh sources/full_test.sh )
drydock score ac $PROJECT $OPTS
# project status = LLM ACCEPTANCE CHECKS OK, OK
drydock score build $PROJECT $OPTS
# project status = SCORE BUILD, OK
drydock score release $PROJECT $OPTS
# project status = SCORE RELEASE, OK

# Create Report
drydock score report $PROJECT $OPTS

# project status = FINALIZED, OK — earned only when no rung failed and SCORE BUILD is held.
# Publishing over an unfinished project still exits 0; the state is what says otherwise.
# `drydock score` displays this state as PROJECT COMPLETE.

# The whole ladder, and where every score's artifact went.
drydock score $PROJECT
date
