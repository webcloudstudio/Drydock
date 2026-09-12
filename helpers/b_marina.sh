export PROJECT=Marina
export PROJECT_DIR=/mnt/c/Users/barlo/projects
export OPTS="--llm-provider codex --model gpt-5.6-luna"

set -x

# export OPTS2="--llm-provider codex --model gpt-5.6-sol"
# export OPTS="--llm-provider codex --model gpt-5.4"
# export OPTS2="--llm-provider claude --model opus"
# export OPTS="--llm-provider claude --model sonnet"

# On WSL/DrvFs, a directory can enter a zombie state where stat returns ENOENT
# but mkdir returns EEXIST.  cmd.exe rmdir resolves it when plain rm cannot.

if [ -z "NO_REBUILD" ]
then
	echo "REBUILDING"
	read
	if [ -d "$PROJECT_DIR/drydock/targets/$PROJECT" ]
	then
		echo "Remove the $PROJECT_DIR/drydock/targets/$PROJECT"
		rm -rf $PROJECT_DIR/drydock/targets/$PROJECT 2>/dev/null || cmd.exe /c "rmdir /s /q targets" 2>/dev/null || true
	fi

	if [ -d $PROJECT_DIR/$PROJECT ]
	then
		echo "Remove $PROJECT_DIR/$PROJECT"
		rm -rf $PROJECT_DIR/$PROJECT 2>/dev/null
	fi
	read

	drydock init $PROJECT $OPTS
	drydock status $PROJECT $OPTS
	./b_Import_Marina.sh
	drydock status $PROJECT $OPTS
	drydock analyze $PROJECT $OPTS
	drydock status $PROJECT $OPTS
	echo "REBUILDING COMPLETED"
fi

drydock plan $PROJECT $OPTS

# drydock config show
# drydock validate $PROJECT $OPTS
# drydock build 	 $PROJECT $OPTS

n=1; max=5
while drydock status "$PROJECT" --ready; do
  echo "************************"
  echo "* RUNNING BUILD ATTEMPT $n"
  echo "************************"
  drydock build $PROJECT $OPTS || drydock diagnose "$PROJECT" --apply || true
  n=$((n+1)); [ "$n" -ge "$max" ] && { echo "hit $max build iterations — aborting"; exit 1; }
done
