set -x
export PROJECT=Marina
export PROJECT_DIR=/mnt/c/Users/barlo/projects
export SOURCE=$PROJECT_DIR/Specifications/Marina

export OPTS="--llm-provider codex --model gpt-5.6-luna"
#export OPTS="--llm-provider claude --model sonnet"

date
rm -rf targets/$PROJECT
rm -rf ../$PROJECT
read
drydock init $PROJECT $OPTS
drydock status $PROJECT $OPTS
./Import_$PROJECT.sh
read
drydock status $PROJECT $OPTS
drydock analyze $PROJECT $OPTS
read
drydock status $PROJECT $OPTS
drydock plan $PROJECT $OPTS
read
drydock build 	 $PROJECT $OPTS
date
