# jq.sh — the `drydock uat jq` command sequence, by hand.  ENTER runs the next step.
set -ux
export PROJECT=jq
export PROJECT_DIR=/mnt/c/Users/barlo/projects
export KIT=$PROJECT_DIR/drydock/uat/$PROJECT
export DRYDOCK_WORKSPACE=$PROJECT_DIR/drydock
export DRYDOCK_BUILD_DIRECTORY=$PROJECT_DIR
export TARGET=$DRYDOCK_WORKSPACE/targets/$PROJECT

# current price differences for Claude:  Sonnet costing exactly 2x Haiku and Opus costing 5x Haiku (or 2.5x Sonnet)
export OPTS="--llm-provider codex --model gpt-5.6-luna"
#export OPTS="--llm-provider claude --model sonnet"
export OPTS="--llm-provider claude --model haiku"

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
  drydock plan repair $PROJECT $OPTS
  # project status = PLAN REPAIRED, OK
  if ! drydock plan verify $PROJECT; then
    # project status = PLAN FAILED VERIFY, ERROR
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
  if ! drydock build $PROJECT --override $OPTS; then
    # project status = BUILD FAIL, ERROR
    echo "build failed with work left — aborting"
    exit 1
  fi
  # project status = BUILDING, OK
  n=$((n+1))
  if [ "$n" -ge "$max" ]; then
    # project status = HIT $max BUILD ITERATIONS, ERROR
    echo "hit $max build iterations — aborting"
    exit 1
  fi
done
# project status = BUILT, OK

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

drydock score report $PROJECT $OPTS
# project status = FINALIZED, OK
date
