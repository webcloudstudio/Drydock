#!/bin/bash
# Common functions — sourced by all bin/ scripts. Never run directly.
# Provides: SCRIPT_NAME, PROJECT_DIR, PROJECT_NAME, PORT, DISPLAY_NAME,
#           venv activation, env loading, timestamped logging, SIGTERM trap.

SCRIPT_NAME="$(basename "$0" .sh)"
# Keep BASH_SOURCE[0] — nested ":-${BASH_SOURCE[0]}" expansion inside $() breaks bash parser
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

get_metadata() { grep "^${1}:" "$PROJECT_DIR/METADATA.md" 2>/dev/null | head -1 | sed "s/^${1}:[[:space:]]*//"; }
PROJECT_NAME="$(get_metadata "name")"
PORT="$(get_metadata "port")"
DISPLAY_NAME="$(get_metadata "display_name")"

if [ -d "$PROJECT_DIR/.venv" ]; then source "$PROJECT_DIR/.venv/bin/activate" 2>/dev/null
elif [ -d "$PROJECT_DIR/venv" ]; then source "$PROJECT_DIR/venv/bin/activate" 2>/dev/null; fi
PROJECTS_DIR="$(dirname "$PROJECT_DIR")"
[ -f "$PROJECTS_DIR/.secrets" ] && set -a && source "$PROJECTS_DIR/.secrets" && set +a
[ -f "$PROJECT_DIR/.env" ] && set -a && source "$PROJECT_DIR/.env" && set +a

mkdir -p logs
LOG_FILE="logs/${SCRIPT_NAME}_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

_on_exit() { local c=$?; [ $c -eq 0 ] && echo "[$PROJECT_NAME] EXIT - OK" || echo "[$PROJECT_NAME] EXIT - ERROR (code=$c)"; }
trap '_on_exit' EXIT
trap 'exit 0' SIGTERM SIGINT
echo "[$PROJECT_NAME] Starting: $SCRIPT_NAME"

# Resolve GAME port: $GAME_PORT env → ~/.game_port file → 5000
_game_port() { echo "${GAME_PORT:-$(cat ~/.game_port 2>/dev/null || echo 5000)}"; }

# heartbeat <state> [message]  — report script health to GAME (silent on failure)
heartbeat() {
    local state="${1:-OK}" message="${2:-}"
    curl -sf -X POST "http://localhost:$(_game_port)/api/heartbeat" \
        -H "Content-Type: application/json" \
        -d "{\"program\":\"$SCRIPT_NAME\",\"system\":\"$PROJECT_NAME\",\"state\":\"$state\",\"message\":\"$message\"}" \
        >/dev/null 2>&1 || true
}

# run_llm_agent [claude -p args...]  — wrapper that logs token usage to stderr + LOG_FILE
# Text result → stdout; usage summary → stderr. Drop-in for: claude -p "$PROMPT" --model ...
run_llm_agent() {
    local _json _exit
    _json=$(claude -p --output-format json "$@")
    _exit=$?
    printf '%s\n' "$_json" | python3 -c "
import sys, json, os
try:
    d = json.load(sys.stdin)
    u = d.get('usage', {})
    cost = d.get('total_cost_usd', 0)
    inp = u.get('input_tokens', 0)
    cached = u.get('cache_read_input_tokens', 0)
    wrote = u.get('cache_creation_input_tokens', 0)
    out = u.get('output_tokens', 0)
    usage_line = f'[tokens] in:{inp} cached:{cached} wrote:{wrote} out:{out} | \${cost:.4f}'
    print(usage_line, file=sys.stderr)
    log_file = os.environ.get('LOG_FILE', '')
    if log_file:
        with open(log_file, 'a') as f:
            f.write(usage_line + '\n')
    print(d.get('result', ''), end='')
except Exception as e:
    print(f'[run_llm_agent] parse error: {e}', file=sys.stderr)
"
    return $_exit
}

# log_event <severity> <message>  — append event to GAME (silent on failure)
log_event() {
    local severity="${1:-INFORMATION}" message="${2:-}"
    curl -sf -X POST "http://localhost:$(_game_port)/api/events" \
        -H "Content-Type: application/json" \
        -d "{\"program\":\"$SCRIPT_NAME\",\"system\":\"$PROJECT_NAME\",\"severity\":\"$severity\",\"message\":\"$message\"}" \
        >/dev/null 2>&1 || true
}
