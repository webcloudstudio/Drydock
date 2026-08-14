#!/usr/bin/env bash
# Run from the Drydock repo root, after `drydock init jq`.

cp uat/jq/inputs/TECHNOLOGY_STACK.md targets/jq/TECHNOLOGY_STACK.md
cp uat/jq/inputs/SEA_TRIALS.md       targets/jq/SEA_TRIALS.md
echo '{"full": ["sh", "sources/full_test.sh"]}' > targets/jq/ACCEPTANCE.json

drydock import jq uat/jq/sources/INSTRUCTIONS.md    	--format compass
drydock import jq uat/jq/sources/jq-manual.txt      	--format markdown
drydock import jq uat/jq/sources/jq.test           	--format markdown
drydock import jq uat/jq/sources/exclusions.txt    	--format markdown
drydock import jq uat/jq/sources/parser.y          	--format markdown
drydock import jq uat/jq/sources/lexer.l           	--format markdown
drydock import jq uat/jq/sources/builtin.jq        	--format markdown
drydock import jq uat/jq/sources/run_conformance.py 	--format markdown
drydock import jq uat/jq/sources/full_test.sh      	--format markdown

# One call instead of the nine above imports the whole bundle in a single pass:
# drydock import jq uat/jq/sources --format markdown
