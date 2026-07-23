# echo commands to the screen
# https://github.com/commonmark/commonmark-spec
# https://spec.commonmark.org/0.31.2/

set -x
set -euo pipefail

export PROJECT=commonmark
export SOURCE=/mnt/c/Users/barlo/projects/commonmark-spec
export OPTS="--llm-provider codex --model gpt-5.6-luna"
#export OPTS="--llm-provider claude --model gpt-5.4"  # DEPRICATED
#export OPTS="--llm-provider claude --model sonnet"

drydock config show

rm -rf /mnt/c/Users/barlo/projects/$PROJECT
cd /mnt/c/Users/barlo/projects/drydock
rm -rf targets/$PROJECT 2>/dev/null || cmd.exe /c "rmdir /s /q targets" 2>/dev/null || true

drydock init $PROJECT $OPTS

cd $SOURCE
drydock import $PROJECT --format markdown INSTRUCTIONS.md
drydock import $PROJECT --format markdown spec.txt
drydock import $PROJECT --format markdown test/spec_tests.py
drydock import $PROJECT --format markdown test/cmark.py
drydock import $PROJECT --format markdown test/normalize.py

cd /mnt/c/Users/barlo/projects/drydock
drydock analyze $PROJECT $OPTS
drydock status 	$PROJECT $OPTS
drydock plan 	$PROJECT $OPTS
drydock build 	$PROJECT $OPTS
echo "$PROJECT Complete"
