#!/usr/bin/env bash
# Diagnose the latest failed archived UAT run for a Target.

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: helpers/diagnose-uat.sh <Target> [--max-rounds N]

Diagnoses the latest failed archived UAT run under uat/<Target>/runs/. It does not select from
logs/history.jsonl and never examines a normal Target run in place.
EOF
}

[[ $# -ge 1 ]] || { usage >&2; exit 2; }
[[ ${1:-} != "-h" && ${1:-} != "--help" ]] || { usage; exit 0; }

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "diagnose-uat: run from a Drydock Git worktree" >&2
  exit 2
}
target=$1
runs_dir="$repo_root/uat/$target/runs"
[[ -d $runs_dir ]] || {
  echo "diagnose-uat: UAT runs directory not found: $runs_dir" >&2
  exit 2
}

run_dir=$(python3 - "$runs_dir" <<'PY'
import json
import sys
from pathlib import Path

runs = Path(sys.argv[1])
candidates = []
for path in runs.iterdir():
    result = path / "result.json"
    if not path.is_dir() or not result.is_file():
        continue
    try:
        data = json.loads(result.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        continue
    assertions = data.get("assertions", {})
    commands = data.get("commands", [])
    failed = int(assertions.get("failed", 0) or 0) > 0 or any(
        int(command.get("returncode", 0) or 0) != 0 for command in commands
    )
    if failed:
        candidates.append(path)
if not candidates:
    raise SystemExit("no failed UAT run with result.json found")
print(max(candidates, key=lambda path: path.name))
PY
) || {
  echo "diagnose-uat: no failed UAT run found for $target" >&2
  exit 2
}

exec env \
  DIAGNOSE_EVIDENCE_ROOT="$run_dir" \
  DIAGNOSE_OUTPUT_DIR="$run_dir/diagnosis" \
  DIAGNOSE_TITLE="UAT Diagnosis" \
  "${BASH_SOURCE[0]%/*}/diagnose.sh" --uat-run "$target" "${@:2}"
