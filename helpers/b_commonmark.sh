# https://github.com/commonmark/commonmark-spec
# https://spec.commonmark.org/0.31.2/
export PROJECT=commonmark
export PROJECT_DIR=/mnt/c/Users/barlo/projects
export SOURCE=$PROJECT_DIR/commonmark-spec
export OPTS="--llm-provider codex --model gpt-5.6-luna"
#export OPTS="--llm-provider claude --model sonnet"

drydock config show
drydock init 	 $PROJECT $OPTS
drydock import 	 $PROJECT --format markdown $SOURCE/INSTRUCTIONS.md
drydock import 	 $PROJECT --format markdown $SOURCE/spec.txt
drydock import 	 $PROJECT --format markdown $SOURCE/test/spec_tests.py
drydock import 	 $PROJECT --format markdown $SOURCE/test/cmark.py
drydock import 	 $PROJECT --format markdown $SOURCE/test/normalize.py

drydock analyze  $PROJECT $OPTS
drydock status 	 $PROJECT $OPTS
drydock plan 	 $PROJECT $OPTS
drydock validate $PROJECT $OPTS
drydock build 	 $PROJECT $OPTS

n=1; max=5
while drydock status "$PROJECT" --ready; do
  echo "************************"
  echo "* RUNNING BUILD ATTEMPT $n"
  echo "************************"
  drydock build $PROJECT $OPTS
  n=$((n+1)); [ "$n" -ge "$max" ] && { echo "hit $max build iterations — aborting"; exit 1; }
done
