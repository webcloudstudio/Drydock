#
# GENERIC DRIVER TO REBUILD A FULL PROJECT
#   - usage $0 <target>
#   - you need to import your own stuff not mine
#

# echo commands to the screen
set -x

# auto commit because we need that to build
git add --all;git commit -m auto-commit-by-driver;

export PROJECT=commonmark
[ -n "$1" ] && PROJECT=$1
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
echo  "Analyze Done - QUARTERDECK REVIEW"
read

drydock plan $PROJECT $OPTS
echo  "Plan Done - QUARTERDECK REVIEW"
read

drydock build $PROJECT $OPTS
