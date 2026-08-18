RUN=/mnt/c/Users/barlo/projects/drydock/uat/jq/runs/20260818.001639
export DRYDOCK_WORKSPACE=$RUN/workspace
export DRYDOCK_BUILD_DIRECTORY=$RUN/build

drydock init jq
# harness then copies inputs into $DRYDOCK_WORKSPACE/targets/jq:
#   SEA_TRIALS.md  TECHNOLOGY_STACK.md  COMPASS.md  ACCEPTANCE.json  STORY_GUIDANCE.json
drydock import jq $RUN/sources --format markdown
drydock analyze jq
drydock plan jq --override
drydock plan verify jq                       # if nonzero: drydock plan repair jq; drydock plan verify jq
drydock build status jq
drydock status jq
drydock status

# build loop, repeat until --ready exits nonzero:
drydock status jq --ready
drydock build jq --override --repair-attempts 3

drydock status jq --check
drydock build status jq
drydock status jq
drydock status

cd $RUN/build/jq && sh sources/full_test.sh   # this is where it crashed
drydock score ac jq
drydock score release jq
