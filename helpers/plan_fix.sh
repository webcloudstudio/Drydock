#!/usr/bin/env bash
# Repair a failed `drydock plan <Target>` run, then replan, until the plan succeeds. Each pass hands
# ERRORS.md and the latest plan output to a headless Claude Code session that fixes Drydock's code
# (never the Target), tests, and commits; the plan is then rerun with --overwrite. The first pass
# works from the run that already failed. Stops on success, on a question for Ed, on a pass that
# commits nothing, or at MAX_PASSES.
#
# Usage: helpers/plan_fix.sh <Target> [extra drydock plan options...]
#   MAX_PASSES   fix passes before giving up (default 5)
#   FIX_MODEL    model for the fixing session (default: Claude Code's configured model)
set -uo pipefail

if [ $# -lt 1 ]; then
	echo "usage: $0 <Target> [drydock plan options...]" >&2
	exit 2
fi
TARGET=$1
shift
MAX_PASSES=${MAX_PASSES:-5}
REPO=$(cd "$(dirname "$0")/.." && pwd)
WORKSPACE=${DRYDOCK_WORKSPACE:-$REPO}
ERRORS="$WORKSPACE/targets/$TARGET/ERRORS.md"
RUN_DIR="$REPO/logs/plan_fix"
mkdir -p "$RUN_DIR"
cd "$REPO" || exit 1

# The run that brought Ed here already failed: its evidence is ERRORS.md and the newest plan log.
evidence=$ERRORS
plan_log=$(ls -t "$REPO"/logs/*_"${TARGET,,}"_plan_*.log 2>/dev/null | grep -Ev '\.(llm|stderr)\.log$' | head -1)
rc="nonzero"
if [ -s "$ERRORS" ]; then
	cat "$ERRORS"
elif [ -n "$plan_log" ]; then
	# A failure that wrote no ERRORS.md entry: the run's own output is the evidence.
	evidence=$plan_log
	echo "=== plan_fix: no $ERRORS; using $plan_log"
else
	echo "=== plan_fix: no $ERRORS or plan log to fix from; run drydock plan $TARGET first" >&2
	exit 1
fi

for pass in $(seq 1 "$MAX_PASSES"); do
	stamp=$(date +%Y%m%d.%H%M%S)
	head_before=$(git rev-parse HEAD)
	questions="$RUN_DIR/${stamp}_${TARGET}_questions.md"
	fix_log="$RUN_DIR/${stamp}_${TARGET}_fix.log"
	prompt="drydock plan $TARGET --overwrite failed (exit $rc). Evidence: $evidence (read it in full), \
the run output in ${plan_log:-the newest *_plan_*.log in $REPO/logs/}, and the per-call prompts and outputs in $REPO/logs/ for this run.

Diagnose the root cause and fix it in Drydock's code under src/drydock/ (and prompts/ or Rigging/ \
when the contract text is the defect), so the rerun passes. Never edit targets/, and never run \
drydock uat or touch uat/. Prefer a deterministic fix in code over asking the LLM to repair \
output that code can derive or normalize. Add a regression test, run \
'ruff check src/ tests/' and 'python -m pytest -p no:randomly -q', and commit the change with a \
descriptive message and no attribution lines. Do not rerun drydock plan; the caller does.

If a fix needs a decision from Ed, commit nothing and write the questions to $questions. \
End with a three-line summary: root cause, fix, commit id."
	echo "=== plan_fix: fixing (log $fix_log)"
	claude -p "$prompt" ${FIX_MODEL:+--model "$FIX_MODEL"} \
		--permission-mode acceptEdits \
		--allowedTools "Read" "Edit" "Write" "Grep" "Glob" "Bash" \
		--disallowedTools "Bash(drydock uat:*)" 2>&1 | tee "$fix_log"

	if [ -s "$questions" ]; then
		echo "=== plan_fix: stopped — questions for Ed in $questions"
		cat "$questions"
		exit 1
	fi
	if [ "$(git rev-parse HEAD)" = "$head_before" ]; then
		echo "=== plan_fix: stopped — the fix pass committed nothing; see $fix_log"
		exit 1
	fi
	git log --oneline "$head_before..HEAD"

	plan_log="$RUN_DIR/${stamp}_${TARGET}_plan.log"
	echo "=== plan_fix pass $pass/$MAX_PASSES · drydock plan $TARGET --overwrite $* · $plan_log"
	before=$(stat -c %Y "$ERRORS" 2>/dev/null || echo 0)
	drydock plan "$TARGET" --overwrite "$@" 2>&1 | tee "$plan_log"
	rc=${PIPESTATUS[0]}
	if [ "$rc" -eq 0 ]; then
		echo "=== plan_fix: drydock plan $TARGET succeeded after fix pass $pass"
		exit 0
	fi
	echo "=== plan_fix: drydock plan exited $rc"
	after=$(stat -c %Y "$ERRORS" 2>/dev/null || echo 0)
	if [ "$after" != "$before" ]; then
		evidence=$ERRORS
		cat "$ERRORS"
	else
		# The failure wrote no ERRORS.md entry; the run's own output is the evidence.
		evidence=$plan_log
		echo "(ERRORS.md unchanged; using $plan_log)"
	fi
done

echo "=== plan_fix: drydock plan $TARGET still failing after $MAX_PASSES fix passes"
exit 1
