set -Eeuo pipefail
set -x

export PROJECT=Marina_Haiku
export PROJECT_DIR=/mnt/c/Users/barlo/projects
OPTS=(--llm-provider claude --model haiku)

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

drydock init "$PROJECT" "${OPTS[@]}"
drydock status "$PROJECT" "${OPTS[@]}"
./b_Import_Marina.sh
drydock analyze "$PROJECT" "${OPTS[@]}"
drydock status "$PROJECT" "${OPTS[@]}"
echo "REBUILDING COMPLETED"

drydock plan "$PROJECT" "${OPTS[@]}"
n=1; max=5
while drydock status "$PROJECT" --ready; do
  echo "************************"
  echo "* RUNNING BUILD ATTEMPT $n"
  echo "************************"
  if drydock build "$PROJECT" "${OPTS[@]}"; then
    n=$((n + 1))
  else
    rc=$?
    echo "Build failed (rc=$rc); aborting without automatic diagnose or retry."
    exit "$rc"
  fi
  if [ "$n" -gt "$max" ]; then
    echo "hit $max build iterations — aborting"
    exit 1
  fi
done
