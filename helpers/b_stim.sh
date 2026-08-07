set -x
PROJECT=stim
SOURCE=/mnt/c/Users/barlo/projects/Specifications/STIM.md
#OPTS="--llm-provider codex --model gpt-5.4"

# On WSL/DrvFs, a directory can enter a zombie state where stat returns ENOENT
# but mkdir returns EEXIST.  cmd.exe rmdir resolves it when plain rm cannot.
rm -rf targets/$PROJECT 2>/dev/null || cmd.exe /c "rmdir /s /q targets" 2>/dev/null || true
read
drydock init $PROJECT $OPTS
read
drydock import $PROJECT $SOURCE --format markdown $OPTS
read
drydock status $PROJECT $OPTS
read
drydock analyze $PROJECT $OPTS
read
drydock status $PROJECT $OPTS
read
drydock plan $PROJECT $OPTS
read
