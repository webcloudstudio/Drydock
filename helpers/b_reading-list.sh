set -x
export PROJECT=ReadingList
export PROJECT_DIR=/mnt/c/Users/barlo/projects
export DRYDOCK_DIR=/mnt/c/Users/barlo/projects/drydock
export SOURCE=./reading-list.md

export OPTS="--llm-provider codex --model gpt-5.6-luna"

# On WSL/DrvFs, a directory can enter a zombie state where stat returns ENOENT
# but mkdir returns EEXIST.  cmd.exe rmdir resolves it when plain rm cannot.
rm -rf $DRYDOCK_DIR/targets/$PROJECT
rm -rf $PROJECT_DIR/$PROJECT

cp $DRYDOCK_DIR/helpers/reading-list-orig.md $DRYDOCK_DIR/helpers/reading-list.md

drydock init $PROJECT $OPTS
drydock import $PROJECT $SOURCE --format markdown $OPTS
read
drydock analyze $PROJECT $OPTS
read
drydock plan $PROJECT $OPTS
read
drydock build $PROJECT $OPTS
read
