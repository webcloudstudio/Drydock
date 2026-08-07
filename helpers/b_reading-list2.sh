set -x
export PROJECT=ReadingList
export PROJECT_DIR=/mnt/c/Users/barlo/projects
export DRYDOCK_DIR=/mnt/c/Users/barlo/projects/drydock
export SOURCE=$DRYDOCK_DIR/helpers/reading-list.md

export OPTS="--llm-provider codex --model gpt-5.6-luna"

cp $DRYDOCK_DIR/helpers/reading-list-upd.md $SOURCE
drydock import $PROJECT --format markdown $OPTS --update
read
drydock refit $PROJECT $OPTS --sources
read
drydock build $PROJECT $OPTS
read
