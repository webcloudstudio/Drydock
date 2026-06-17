#!/usr/bin/env bash
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPORT_ROOT="${VALIDATION_REPORT_ROOT:-$REPO_ROOT/validation/reports}"
RUN_ID="${VALIDATION_RUN_ID:-$(date +%Y%m%dT%H%M%S)}"
mkdir -p "$REPORT_ROOT/$RUN_ID"

cases=("$@")
if [ "${#cases[@]}" -eq 0 ]; then
    cases=("hello-cli" "file-transform" "todo-cli")
fi

overall_rc=0
for case_slug in "${cases[@]}"; do
    script_name="test_${case_slug//-/_}.sh"
    script_path="$REPO_ROOT/validation/bin/$script_name"
    if [ ! -x "$script_path" ]; then
        echo "missing executable validation script: $script_path" >&2
        overall_rc=1
        continue
    fi
    VALIDATION_REPORT_ROOT="$REPORT_ROOT" VALIDATION_RUN_ID="$RUN_ID" "$script_path" || overall_rc=1
done

python3 "$REPO_ROOT/validation/bin/score_all.py" \
    "$REPORT_ROOT/$RUN_ID" \
    --output-json "$REPORT_ROOT/$RUN_ID/summary.json" \
    --output-md "$REPORT_ROOT/$RUN_ID/SUMMARY.md" \
    >"$REPORT_ROOT/$RUN_ID/summary.stdout.log" || overall_rc=1

echo "validation reports: $REPORT_ROOT/$RUN_ID"
exit "$overall_rc"
