# echo commands to the screen
set -x

# auto commit the latest code
git add --all;git commit -m auto-commit-by-driver;

export PROJECT=commonmark
[ -n "$1" ] && PROJECT=$1

export SOURCE=/mnt/c/Users/barlo/projects/commonmark-spec
export OPTS="--llm-provider codex --model gpt-5.6-luna"
#export OPTS="--llm-provider claude --model sonnet"

echo "Step 1: Showing Drydock Config"
drydock config
read

echo "Step 2: Clearing Workspace and Target - Restart Project From Scratch"
rm -rf /mnt/c/Users/barlo/projects/$PROJECT
cd /mnt/c/Users/barlo/projects/drydock
rm -rf targets/$PROJECT 2>/dev/null || cmd.exe /c "rmdir /s /q targets" 2>/dev/null || true

echo  "Init"
drydock init $PROJECT $OPTS

echo  "Import Specifications"
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
echo  "Analyze Completed - QUARTERDECK REVIEW"
read

echo  "Running Plan"
drydock plan $PROJECT $OPTS
echo  "Plan Completed - QUARTERDECK REVIEW"
read

echo  "Running Plan"
drydock build $PROJECT $OPTS
echo  "Plan Completed - QUARTERDECK REVIEW"

echo "$PROJECT Complete"
