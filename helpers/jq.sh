set -x
export PROJECT=jq
export PROJECT_DIR=/mnt/c/Users/barlo/projects
export KIT=uat/jq

export OPTS="--llm-provider codex --model gpt-5.6-luna"
#export OPTS="--llm-provider claude --model sonnet"

date
rm -rf targets/$PROJECT
rm -rf ../$PROJECT
read
drydock init $PROJECT $OPTS
drydock status $PROJECT $OPTS
./helpers/Import_$PROJECT.sh
read
drydock status $PROJECT $OPTS
drydock analyze $PROJECT $OPTS
read
drydock status $PROJECT $OPTS
drydock plan $PROJECT $OPTS
read
drydock build    $PROJECT $OPTS
date

# ---------------------------------------------------------------------------
# Checks worth making at each `read`.
#
# after Import_jq.sh
#   targets/jq/TECHNOLOGY_STACK.md   Python 3.11+, stdlib only
#   targets/jq/SEA_TRIALS.md         one trial, st-001, consequence blocks
#   targets/jq/ACCEPTANCE.json       {"full": ["sh", "sources/full_test.sh"]}
#   targets/jq/blueprint/sources/    the nine imported files
#
# after analyze
#   The `## Source Roles` table -- written by the model, and load-bearing.
#   Every file except INSTRUCTIONS.md must have build disposition `stage`.
#   If jq-manual.txt is not staged, the builder cannot read the specification
#   and the run is wasted. Fix it by hand before continuing.
#
# after plan
#   Story granularity. The evaluation model -- filters as generators, with
#   backtracking -- must be settled in an early story, before builtins.
#
# scoring, at any time
#   cd ../jq && sh sources/full_test.sh
#   JQ="$PWD/jq" python3 sources/run_conformance.py --select 'reduce'
#
# calibration reference: jq 1.8.2 scores 537 passed, 0 failed, 0 errored,
# 13 skipped. See uat/jq/NEXT_STEPS.md.
# ---------------------------------------------------------------------------
