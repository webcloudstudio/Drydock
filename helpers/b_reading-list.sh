set -x
export PROJECT=ReadingList
export PROJECT_DIR=/mnt/c/Users/barlo/projects
export SOURCE=./reading-list.md

export OPTS="--llm-provider codex --model gpt-5.6-luna"

# On WSL/DrvFs, a directory can enter a zombie state where stat returns ENOENT
# but mkdir returns EEXIST.  cmd.exe rmdir resolves it when plain rm cannot.
rm -rf targets/$PROJECT 2>/dev/null || cmd.exe /c "rmdir /s /q targets" 2>/dev/null || true
rm -rf ../$PROJECT 2>/dev/null

drydock init $PROJECT $OPTS
drydock import $PROJECT $SOURCE --format markdown $OPTS
drydock analyze $PROJECT $OPTS
read
drydock plan $PROJECT $OPTS
read
drydock build $PROJECT $OPTS
read
