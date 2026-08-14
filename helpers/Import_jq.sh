#!/usr/bin/env bash
# Run from the Drydock repo root, after `drydock init jq`.

cp uat/jq/inputs/TECHNOLOGY_STACK.md targets/jq/TECHNOLOGY_STACK.md
cp uat/jq/inputs/SEA_TRIALS.md       targets/jq/SEA_TRIALS.md
echo '{"full": ["sh", "sources/full_test.sh"]}' > targets/jq/ACCEPTANCE.json

drydock import jq uat/jq/sources/INSTRUCTIONS.md    $OPTS
drydock import jq uat/jq/sources/jq-manual.txt      $OPTS
drydock import jq uat/jq/sources/jq.test           $OPTS
drydock import jq uat/jq/sources/exclusions.txt    $OPTS
drydock import jq uat/jq/sources/parser.y          $OPTS
drydock import jq uat/jq/sources/lexer.l           $OPTS
drydock import jq uat/jq/sources/builtin.jq        $OPTS
drydock import jq uat/jq/sources/run_conformance.py $OPTS
drydock import jq uat/jq/sources/full_test.sh      $OPTS

# One call instead of the nine above imports the whole bundle in a single pass:
# drydock import jq uat/jq/sources --format markdown $OPTS
