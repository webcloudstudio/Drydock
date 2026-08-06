set -x
export PROJECT=Reading-List

export PROJECT_DIR=/mnt/c/Users/barlo/projects
export SOURCE=$PROJECT_DIR/Specifications/Marina

#export OPTS="--llm-provider codex --model gpt-5.4"
export OPTS="--llm-provider codex --model gpt-5.6-luna"
#export OPTS2="--llm-provider claude --model opus"
export OPTS2="--llm-provider codex --model gpt-5.6-sol"
#export OPTS="--llm-provider claude --model sonnet"

# On WSL/DrvFs, a directory can enter a zombie state where stat returns ENOENT
# but mkdir returns EEXIST.  cmd.exe rmdir resolves it when plain rm cannot.
rm -rf targets/$PROJECT 2>/dev/null || cmd.exe /c "rmdir /s /q targets" 2>/dev/null || true
rm -rf ../$PROJECT 2>/dev/null
read
drydock init $PROJECT $OPTS

drydock status $PROJECT $OPTS

./Import_Marina.sh
# drydock import Marina3 $SOURCE/INTENT.md --format compass --force
# drydock import $PROJECT $SOURCE --format markdown $OPTS

drydock status $PROJECT $OPTS
drydock analyze $PROJECT $OPTS
read

drydock status $PROJECT $OPTS
drydock plan $PROJECT $OPTS
read

# drydock config show
# drydock validate $PROJECT $OPTS
# drydock build 	 $PROJECT $OPTS

n=1; max=5
while drydock status "$PROJECT" --ready; do
  echo "************************"
  echo "* RUNNING BUILD ATTEMPT $n"
  echo "************************"
  drydock build $PROJECT $OPTS
  n=$((n+1)); [ "$n" -ge "$max" ] && { echo "hit $max build iterations — aborting"; exit 1; }
done
