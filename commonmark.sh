set -x
export PROJECT=commonmark
export SOURCE=/mnt/c/Users/barlo/projects/commonmark-spec
export OPTS="--llm-provider codex --model gpt-5.6-luna"

echo "Clearing Target"
cd /mnt/c/Users/barlo/projects/drydock
rm -rf targets/$PROJECT 2>/dev/null || cmd.exe /c "rmdir /s /q targets" 2>/dev/null || true

echo  "Init"
drydock init $PROJECT $OPTS

echo  "Importing"
cd $SOURCE
drydock import $PROJECT --format markdown ED_INSTRUCTIONS.md
drydock import $PROJECT --format markdown spec.txt
drydock import $PROJECT --format markdown test/spec_tests.py
drydock import $PROJECT --format markdown test/cmark.py
drydock import $PROJECT --format markdown test/normalize.py

echo  "Running Analyze"
cd /mnt/c/Users/barlo/projects/drydock
drydock analyze commonmark $OPTS
drydock status $PROJECT $OPTS
read

# drydock plan $PROJECT $OPTS_HI
# read
