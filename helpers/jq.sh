# jq.sh — the `drydock uat jq` command sequence, by hand.  ENTER runs the next step.
set -ux
export PROJECT=jq
export PROJECT_DIR=/mnt/c/Users/barlo/projects
export KIT=$PROJECT_DIR/drydock/uat/$PROJECT
export DRYDOCK_WORKSPACE=$PROJECT_DIR/drydock
export DRYDOCK_BUILD_DIRECTORY=$PROJECT_DIR
export TARGET=$DRYDOCK_WORKSPACE/targets/$PROJECT

export OPTS="--llm-provider codex --model gpt-5.6-luna"
#export OPTS="--llm-provider claude --model sonnet"

cd $DRYDOCK_WORKSPACE
date
rm -rf $TARGET $PROJECT_DIR/$PROJECT
read
drydock init $PROJECT $OPTS

# METADATA and COMPASS go on before analyze; analyze only fills fields it finds blank.
cp $KIT/inputs/METADATA.md $TARGET/METADATA.md
drydock import $PROJECT $KIT/inputs/COMPASS.md --format compass --force $OPTS
echo '{"full": ["sh", "sources/full_test.sh"]}' > $TARGET/ACCEPTANCE.json
echo '{"stories": []}'                          > $TARGET/STORY_GUIDANCE.json
read
drydock import $PROJECT $KIT/sources --format markdown $OPTS
drydock analyze $PROJECT $OPTS

# analyze writes these two itself, so the kit copies go on after it.
cp $KIT/inputs/TECHNOLOGY_STACK.md $TARGET/TECHNOLOGY_STACK.md
cp $KIT/inputs/SEA_TRIALS.md       $TARGET/SEA_TRIALS.md
drydock status $PROJECT
read
drydock plan $PROJECT --override $OPTS
if ! drydock plan verify $PROJECT; then
  drydock plan repair $PROJECT $OPTS
  if ! drydock plan verify $PROJECT; then
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
  if ! drydock build $PROJECT --override --repair-attempts 3 $OPTS; then
    echo "build failed with work left — aborting"
    exit 1
  fi
  n=$((n+1))
  if [ "$n" -ge "$max" ]; then
    echo "hit $max build iterations — aborting"
    exit 1
  fi
done

drydock status $PROJECT --check
drydock build status $PROJECT
read
( cd $PROJECT_DIR/$PROJECT && sh sources/full_test.sh )
drydock score ac $PROJECT $OPTS
drydock score release $PROJECT $OPTS
date
