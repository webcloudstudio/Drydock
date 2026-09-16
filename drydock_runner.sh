#!/usr/bin/env bash
# Resume one imported Drydock Target without deleting or regenerating prior work.
set -Eeuo pipefail

# Every model this runner will accept. A model selects its own provider, so naming one here is
# the whole configuration. Gemini models are metered and bill per token; the rate is the input
# price per million tokens, quoted so a long run is a deliberate choice rather than a surprise.
VALID_MODELS=(
  # Claude — subscription
  haiku
  sonnet
  opus
  # Codex — subscription
  gpt-5.4
  gpt-5.6-luna
  gpt-5.6-sol
  gpt-5.6-terra
  # Gemini — metered, billed per token
  gemini-2.5-flash-lite
  gemini-3.1-flash-lite
  gemini-3.5-flash-lite
)

model_cost() {
  case "$1" in
    gemini-2.5-flash-lite) echo '$0.10/1M input, metered' ;;
    gemini-3.1-flash-lite) echo '$0.25/1M input, metered' ;;
    gemini-3.5-flash-lite) echo 'price unconfirmed, metered' ;;
    *) echo 'subscription' ;;
  esac
}

list_models() {
  echo "Valid models:" >&2
  for candidate in "${VALID_MODELS[@]}"; do
    printf '  %-24s %s\n' "$candidate" "$(model_cost "$candidate")" >&2
  done
}

usage() {
  echo "Usage: drydock_runner.sh <target> <model>" >&2
  echo "  <model> selects the provider; no --llm-provider is needed." >&2
}

if [ "$#" -ne 2 ]; then
  usage
  list_models
  exit 2
fi

TARGET=$1
MODEL=$2

valid=0
for candidate in "${VALID_MODELS[@]}"; do
  if [ "$MODEL" = "$candidate" ]; then
    valid=1
    break
  fi
done
if [ "$valid" -ne 1 ]; then
  echo "Unsupported model: $MODEL" >&2
  list_models
  exit 2
fi

# The model names its own provider, so the provider is never passed explicitly.
OPTS=(--model "$MODEL")
ANALYZE_OPTS=("${OPTS[@]}")
PLAN_OPTS=("${OPTS[@]}")
if [ "$MODEL" = "haiku" ]; then
  # Haiku plans poorly; analysis and synthesis run on sonnet, and haiku attributes lineage.
  ANALYZE_OPTS=(--model sonnet)
  PLAN_OPTS=(--model sonnet --lineage-model "$MODEL")
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

bash "$(dirname -- "${BASH_SOURCE[0]}")/drydock_build_loop.sh" "$TARGET" "${OPTS[@]}"

drydock status "$TARGET"
