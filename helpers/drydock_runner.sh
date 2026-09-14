#!/usr/bin/env bash
# Resume one imported Drydock Target without deleting or regenerating prior work.
set -Eeuo pipefail

usage() {
  echo "Usage: drydock_runner.sh <target> <model>" >&2
  echo "  <model> selects the provider: Claude names (haiku, sonnet, opus) or Codex names (gpt-*)." >&2
}

if [ "$#" -ne 2 ]; then
  usage
  exit 2
fi

TARGET=$1
MODEL=$2
case "$MODEL" in
  haiku|sonnet|opus|fable|claude-*) LLM_PROVIDER=claude ;;
  gpt-*|codex-*|*luna*|*terra*|*sol*) LLM_PROVIDER=codex ;;
  *)
    echo "Cannot infer an LLM provider from model: $MODEL" >&2
    usage
    exit 2
    ;;
esac

OPTS=(--llm-provider "$LLM_PROVIDER" --model "$MODEL")
ANALYZE_OPTS=("${OPTS[@]}")
PLAN_OPTS=("${OPTS[@]}")
if [ "$MODEL" = "haiku" ]; then
  ANALYZE_OPTS=(--llm-provider "$LLM_PROVIDER" --model sonnet)
  PLAN_OPTS=(--llm-provider "$LLM_PROVIDER" --model sonnet --lineage-model "$MODEL")
fi

eval "$(drydock config env "$TARGET")"

if [ ! -d "$DRYDOCK_TARGET_DIR" ]; then
  drydock init "$TARGET" "${OPTS[@]}"
  echo "Initialized $TARGET. Import its source material, then rerun this command." >&2
  exit 2
fi

if [ ! -d "$DRYDOCK_TARGET_DIR/blueprint/sources" ] || \
   [ -z "$(find "$DRYDOCK_TARGET_DIR/blueprint/sources" -type f -print -quit)" ]; then
  echo "No imported source material for $TARGET." >&2
  echo "Run: drydock import $TARGET <source>, then rerun this command." >&2
  exit 2
fi

if [ ! -f "$DRYDOCK_TARGET_DIR/ANALYSIS.md" ]; then
  drydock analyze "$TARGET" "${ANALYZE_OPTS[@]}"
fi

if [ ! -f "$DRYDOCK_TARGET_DIR/MANIFEST.md" ]; then
  drydock plan "$TARGET" "${PLAN_OPTS[@]}"
fi

MAX_BUILDS=${DRYDOCK_RUNNER_MAX_BUILDS:-5}
case "$MAX_BUILDS" in
  ''|*[!0-9]*)
    echo "DRYDOCK_RUNNER_MAX_BUILDS must be a positive integer: $MAX_BUILDS" >&2
    exit 2
    ;;
esac
if [ "$MAX_BUILDS" -eq 0 ]; then
  echo "DRYDOCK_RUNNER_MAX_BUILDS must be greater than zero." >&2
  exit 2
fi

attempt=1
while drydock status "$TARGET" --ready; do
  echo "Running build attempt $attempt/$MAX_BUILDS"
  if ! drydock build "$TARGET" "${OPTS[@]}"; then
    echo "Build failed; state is preserved. Rerun this command to resume." >&2
    exit 1
  fi
  attempt=$((attempt + 1))
  if [ "$attempt" -gt "$MAX_BUILDS" ]; then
    echo "Reached DRYDOCK_RUNNER_MAX_BUILDS=$MAX_BUILDS; state is preserved." >&2
    exit 1
  fi
done

drydock status "$TARGET"
