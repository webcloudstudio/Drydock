#!/usr/bin/env bash
# Diagnose the latest failed Drydock UAT run with two subscription-authenticated CLI agents.
#
# This helper is read-only with respect to the Target, Blueprint, build tree, and source tree.
# It writes only a diagnosis transcript under the selected immutable UAT run.

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: helpers/diagnose.sh <Target> [--max-rounds N]

Diagnoses the latest failed UAT run for <Target>.  Two independent agents inspect the run, then
cross-critique each other until both emit VERDICT: AGREED or the bounded review budget ends.

Environment overrides:
  CODEX_MODEL     default: gpt-5.6-sol
  CODEX_EFFORT    default: xhigh
  CLAUDE_MODEL    default: opus
  CLAUDE_EFFORT   default: max

The helper invokes subscription-authenticated codex and claude CLIs.  It never edits the Blueprint,
Target, build tree, or repository source.  It writes transcripts only to uat/<Target>/runs/<run>/diagnosis/.
EOF
}

die() {
  echo "diagnose: $*" >&2
  exit 2
}

[[ $# -ge 1 ]] || { usage >&2; exit 2; }
[[ ${1:-} != "-h" && ${1:-} != "--help" ]] || { usage; exit 0; }

target=$1
shift
max_rounds=2
while [[ $# -gt 0 ]]; do
  case $1 in
    --max-rounds)
      [[ $# -ge 2 && $2 =~ ^[1-9][0-9]*$ ]] || die "--max-rounds requires a positive integer"
      max_rounds=$2
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *) die "unknown argument: $1" ;;
  esac
done

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || die "run from a Drydock Git worktree"
runs_dir="$repo_root/uat/$target/runs"
[[ -d $runs_dir ]] || die "UAT runs directory not found: $runs_dir"
command -v codex >/dev/null || die "codex CLI is not installed or not on PATH"
command -v claude >/dev/null || die "claude CLI is not installed or not on PATH"

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
) || die "no failed UAT run found for $target"

diagnosis_dir="$run_dir/diagnosis"
mkdir -p "$diagnosis_dir"

codex_model=${CODEX_MODEL:-gpt-5.6-sol}
codex_effort=${CODEX_EFFORT:-xhigh}
claude_model=${CLAUDE_MODEL:-opus}
claude_effort=${CLAUDE_EFFORT:-max}

evidence_index="$diagnosis_dir/evidence-index.md"
cat >"$evidence_index" <<EOF
# UAT Diagnosis Evidence Index

- Target: $target
- Run: ${run_dir##*/}
- Run directory: $run_dir
- Repository: $repo_root

The run directory is immutable evidence. Inspect it directly. Do not edit it, the Target, the
Blueprint, the build tree, or repository source. Prefer exact file paths and line references.

Primary evidence:

- result.json — overall UAT outcome and command ledger.
- evidence/commands/ — command stdout, stderr, and provider logs.
- workspace/targets/$target/ — Blueprint, Manifest, evidence, and generated state from this run.
- build/$target/ — built product at the run's stopping point, when present.
- sources/ — imported source kit used by the run.

Required conclusion policy:

- Separate product defects, Blueprint defects, harness defects, and Drydock defects.
- Do not recommend modifying a historical Blueprint merely to make this completed UAT pass.
- Do not propose code changes without cited evidence.
EOF

base_prompt="$diagnosis_dir/base-prompt.md"
cat >"$base_prompt" <<EOF
You are performing a read-only adversarial diagnosis of a failed Drydock UAT run.

Read $evidence_index and inspect only files under $run_dir and the repository source needed to
understand Drydock control flow. Do not edit files and do not run a build, test, UAT, or network
operation. Your task is diagnosis, not implementation.

Return concise Markdown using exactly these headings:

## Root Cause
Classify each cause as PRODUCT, BLUEPRINT, HARNESS, or DRYDOCK. Cite exact paths and lines.

## Evidence
State the observed facts that establish or refute each proposed cause.

## Corrective Action
Give the smallest structural correction. Historical UAT Blueprint files are evidence and must not
be rewritten to make the completed run pass.

## Rejected Actions
Name tempting but invalid actions, especially post-hoc Blueprint edits.

## Review Verdict
Write exactly one final line: VERDICT: PROVISIONAL, VERDICT: AGREED, VERDICT: REVISE, or
VERDICT: BLOCKED. AGREED is allowed only after reviewing another agent's analysis and finding no
material contradiction.
EOF

run_codex() {
  local prompt=$1 output=$2
  codex exec --ignore-user-config --ignore-rules --ephemeral --sandbox read-only \
    --cd "$repo_root" --json --output-last-message "$output" --model "$codex_model" \
    -c "model_reasoning_effort=$codex_effort" - <"$prompt" \
    >"${output%.md}.events.jsonl" 2>"${output%.md}.stderr.log"
}

run_claude() {
  local prompt=$1 output=$2
  (
    cd "$repo_root"
    claude -p --safe-mode --output-format text --tools "Read,Glob,Grep" --strict-mcp-config \
      --model "$claude_model" --effort "$claude_effort" <"$prompt"
  ) >"$output" 2>"${output%.md}.stderr.log"
}

echo "diagnose: target=$target run=${run_dir##*/}"
echo "diagnose: codex/$codex_model effort=$codex_effort"
echo "diagnose: claude/$claude_model effort=$claude_effort"

analyst_0="$diagnosis_dir/analyst-round-0.md"
critic_0="$diagnosis_dir/critic-round-0.md"
run_codex "$base_prompt" "$analyst_0" || die "Codex independent diagnosis failed; see ${analyst_0%.md}.stderr.log"
run_claude "$base_prompt" "$critic_0" || die "Claude independent diagnosis failed; see ${critic_0%.md}.stderr.log"

final_analyst=$analyst_0
final_critic=$critic_0
for round in $(seq 1 "$max_rounds"); do
  analyst_prompt="$diagnosis_dir/analyst-round-$round.prompt.md"
  critic_prompt="$diagnosis_dir/critic-round-$round.prompt.md"
  analyst_output="$diagnosis_dir/analyst-round-$round.md"
  critic_output="$diagnosis_dir/critic-round-$round.md"

  cat "$base_prompt" >"$analyst_prompt"
  cat >>"$analyst_prompt" <<EOF

## Other Agent's Analysis

$(cat "$final_critic")

Review it adversarially. Preserve only claims supported by the UAT evidence. Identify every
material disagreement and revise your own diagnosis if the other analysis is better supported.
EOF
  run_codex "$analyst_prompt" "$analyst_output" || die "Codex review round $round failed"

  cat "$base_prompt" >"$critic_prompt"
  cat >>"$critic_prompt" <<EOF

## Other Agent's Revised Analysis

$(cat "$analyst_output")

Review it adversarially. Preserve only claims supported by the UAT evidence. Identify every
material disagreement and revise your own diagnosis if the other analysis is better supported.
EOF
  run_claude "$critic_prompt" "$critic_output" || die "Claude review round $round failed"

  final_analyst=$analyst_output
  final_critic=$critic_output
  if grep -qx 'VERDICT: AGREED' "$final_analyst" && grep -qx 'VERDICT: AGREED' "$final_critic"; then
    break
  fi
done

report="$diagnosis_dir/DIAGNOSIS.md"
{
  echo "# UAT Diagnosis: $target (${run_dir##*/})"
  echo
  echo "- Codex: $codex_model; effort=$codex_effort"
  echo "- Claude: $claude_model; effort=$claude_effort"
  echo "- Maximum review rounds: $max_rounds"
  echo
  if grep -qx 'VERDICT: AGREED' "$final_analyst" && grep -qx 'VERDICT: AGREED' "$final_critic"; then
    echo "## Convergence"
    echo
    echo "Both agents reported AGREED after adversarial review."
    status=0
  else
    echo "## Convergence"
    echo
    echo "No verified consensus within the configured review budget. Review the final analyses; no conclusion is promoted automatically."
    status=1
  fi
  echo
  echo "## Codex Final Analysis"
  echo
  cat "$final_analyst"
  echo
  echo "## Claude Final Analysis"
  echo
  cat "$final_critic"
} >"$report"

echo "diagnose: report written to $report"
exit "$status"
