#!/usr/bin/env bash
# Alternate a UAT run with a headless Claude repair session until the kit passes.
#
# Usage: scripts/uat_repair_loop.sh [<Target>] [<model>] [<max-iterations>]
#   defaults: LayersTesting gpt-5.6-luna 5
#
# Stops when the UAT exits 0, when the run declared a BLOCKERS.md halt, when an iteration's repair
# session commits nothing, or after <max-iterations> runs. Each iteration's console output is kept
# under logs/uat_loop/<stamp>/.
set -uo pipefail

target="${1:-LayersTesting}"
model="${2:-gpt-5.6-luna}"
max_iterations="${3:-5}"

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
log_dir="$repo/logs/uat_loop/$(date +%Y%m%d.%H%M%S)"
mkdir -p "$log_dir"

repair_prompt="Run /ddk-uat $target to diagnose the latest UAT run, then implement every \
Recommended Action it marks to fix now. Fix defects in src/drydock/ and prompts/ with a \
regression test; never patch generated Target data. Verify with ruff check src/ tests/ and \
python -m pytest -p no:randomly -q on only the test modules you changed or that import the \
modules you changed; do not run the full suite. Commit your files by pathspec with no \
attribution lines. Do not run drydock uat and do not write under uat/. If the diagnosis names \
no Drydock defect to fix, commit nothing and say so."

for iteration in $(seq 1 "$max_iterations"); do
    echo "=== iteration $iteration/$max_iterations: drydock uat $target --model $model ==="
    drydock uat "$target" --model "$model" 2>&1 | tee "$log_dir/$iteration-uat.log"
    uat_exit="${PIPESTATUS[0]}"
    echo "=== iteration $iteration: drydock uat exited $uat_exit ==="
    if [ "$uat_exit" -eq 0 ]; then
        echo "PASSED: $target on iteration $iteration"
        exit 0
    fi
    if [ "$uat_exit" -eq 2 ]; then
        echo "STOPPED: drydock uat usage error"
        exit 2
    fi
    # A run that declared a halt ends the loop: its BLOCKERS.md names a cause a repair session is
    # not asked to judge. The file sits in the run's sealed workspace and never gates a new run.
    if grep -q ": stopped at " "$log_dir/$iteration-uat.log"; then
        build_target="$(sed -n 's/^- Build target: `\(.*\)`$/\1/p' "$log_dir/$iteration-uat.log" | tail -1)"
        stop_file="$build_target/BLOCKERS.md"
        echo
        echo "========================================================================"
        echo "LOOP ABORTED: drydock uat $target declared a halt on iteration $iteration"
        echo "========================================================================"
        grep -m1 "^- Failure: " "$log_dir/$iteration-uat.log"
        if [ -n "$build_target" ] && [ -f "$stop_file" ]; then
            echo
            echo "Contents of $stop_file:"
            echo
            sed 's/^/  /' "$stop_file"
        fi
        echo
        echo "No repair session was started. The halt is part of that run's sealed evidence;"
        echo "do not delete it. Fix the cause, then start a new loop, which begins a fresh run:"
        echo "  scripts/uat_repair_loop.sh $target $model $max_iterations"
        grep -m1 "^- Failure: " "$log_dir/$iteration-uat.log"
        exit 1
    fi

    head_before="$(git -C "$repo" rev-parse HEAD)"
    echo "=== iteration $iteration: Claude repair session ==="
    (cd "$repo" && claude -p --permission-mode auto "$repair_prompt") \
        2>&1 | tee "$log_dir/$iteration-repair.log"
    if [ "$(git -C "$repo" rev-parse HEAD)" = "$head_before" ]; then
        echo "STOPPED: repair session on iteration $iteration committed nothing"
        exit 1
    fi
    git -C "$repo" log --oneline "$head_before..HEAD"
done

echo "STOPPED: $target still failing after $max_iterations iterations"
exit 1
