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
  gemini-3.5-flash-lite
)

model_cost() {
  case "$1" in
    gemini-3.5-flash-lite) echo 'metered, billed per token' ;;
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
  echo "Usage: drydock_runner.sh <target> <model> [<import-script>]" >&2
  echo "  <model>         selects the provider; no --llm-provider is needed." >&2
  echo "  <import-script> names the source material to import when the Target has none." >&2
  echo "                  See Import_Marina.sh for the contract." >&2
}

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  usage
  list_models
  exit 2
fi

TARGET=$1
MODEL=$2
IMPORT_SCRIPT=${3:-}

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

# Import helpers offered to an import script. The script supplies only the list of source
# material; these run it against the Target and model this invocation already selected. A
# relative path resolves against SOURCE_DIR, which the import script sets; absolute paths pass
# through untouched. SOURCE_DIR may itself be relative, because the script runs from its own
# directory.
source_path() {
  case "$1" in
    /*) printf '%s' "$1" ;;
    *) printf '%s' "${SOURCE_DIR:?import script must set SOURCE_DIR}/$1" ;;
  esac
}

# Every import runs through here, so the exact command is always shown before it runs.
run_import() {
  echo "Running: drydock import $*"
  drydock import "$@"
}

# <file> — project intent, normalized into COMPASS.md. Import this first.
import_compass() {
  run_import "$TARGET" "$(source_path "$1")" --format compass "${OPTS[@]}"
}

# <file> [format] — one specification document.
import_spec() {
  run_import "$TARGET" "$(source_path "$1")" --format "${2:-markdown}" "${OPTS[@]}"
}

# <dir> [format] — every file under a directory, in one import.
import_directory() {
  run_import "$TARGET" "$(source_path "$1")" --format "${2:-markdown}" "${OPTS[@]}"
}

# <dir> — an existing source tree, imported as code rather than specification.
import_code() {
  import_directory "$1" source
}

# True only when real source material has been imported. Hidden entries are never authored
# specification — they are Drydock's own bookkeeping, version-control skeletons such as the
# .gitkeep that init seeds, or tool droppings. This mirrors is_hidden() in source_files.py, so
# the runner and the commands agree on what counts as imported. The find runs from inside the
# directory so a dot in an ancestor path cannot exclude everything.
has_sources() {
  local dir=$DRYDOCK_TARGET_DIR/blueprint/sources
  [ -d "$dir" ] || return 1
  [ -n "$(cd -- "$dir" && find . -type f -not -path '*/.*' -print -quit)" ]
}

# The script is sourced only at the point an import is wanted, so its imports run here and
# nowhere else. It runs from its own directory, so it may sit beside the project it describes
# and name source material relatively.
run_import_script() {
  if [ ! -f "$IMPORT_SCRIPT" ]; then
    echo "Import script not found: $IMPORT_SCRIPT" >&2
    exit 2
  fi
  local dir base prev
  dir=$(cd -- "$(dirname -- "$IMPORT_SCRIPT")" && pwd)
  base=$(basename -- "$IMPORT_SCRIPT")
  echo "Importing source material for $TARGET from $dir/$base"
  prev=$PWD
  cd -- "$dir"
  # shellcheck source=/dev/null
  source "./$base"
  cd -- "$prev"
}

eval "$(drydock config env "$TARGET")"

if [ ! -d "$DRYDOCK_TARGET_DIR" ]; then
  drydock init "$TARGET" "${OPTS[@]}"
  if [ -z "$IMPORT_SCRIPT" ]; then
    echo "Initialized $TARGET. Import its source material, then rerun this command." >&2
    exit 2
  fi
fi

if ! has_sources; then
  if [ -z "$IMPORT_SCRIPT" ]; then
    echo "No imported source material for $TARGET." >&2
    echo "Run: drydock import $TARGET <source>, then rerun this command." >&2
    echo "Or pass an import script: drydock_runner.sh $TARGET $MODEL <import-script>" >&2
    exit 2
  fi
  run_import_script
  if ! has_sources; then
    echo "$IMPORT_SCRIPT imported no source material for $TARGET." >&2
    exit 1
  fi
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
