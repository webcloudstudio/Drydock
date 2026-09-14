
set -Eeuo pipefail
set -x

export PROJECT=Marina_Haiku
export PROJECT_DIR=/mnt/c/Users/barlo/projects
OPTS=(--llm-provider claude --model haiku)

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
