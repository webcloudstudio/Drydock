# MEMORY: UAT jq

| Field | Value |
|---|---|
| Version | 2026-10-28 V1 |
| Description | jq UAT diagnosis and repair evidence. |
| Target | jq |
| Evidence root | `uat/jq` |

## Intent

Preserve jq UAT findings and verification across runs.

## Guardrails

- Published UAT evidence is read-only; only Ed runs UAT.

## Details

### Current contract

Source-derived acceptance and non-empty selection proof remain authoritative; see [acceptance criteria](../../../topics/acceptance_criteria.md) and [plan](../../../commands/plan.md). Diagnosis does not change assertions or the selected corpus.

### Findings

- **jq-probe-01 — unverified** · Run `20261028.145919`, plan verify/repair; provider `codex`, models `gpt-6-luna, gpt-6.1-terra` (receipt). Plan generated 15 missing or invalid probe declarations. Repair supplied entire shell commands as `Probe:` for all 15; the flag-only parser rejected them and persisted no edits. `FEATURE-GeneratorControl.md` was originally missing its probe; repair supplied a command ending in `--list`. `acceptance.py:2372-2400` requires literal flags and constructs the original runner argv itself. In a temporary copy of the preserved sources, the original criterion with `Probe: --list` and `Probe Count: summary` passes `selection_probe_reason`; the runner lists cases before requiring a product and reports `0 cases, 0 excluded` for a nonexistent selector. Temporary-copy validation with the same declaration passes for all 15 selectors; this proves nonempty selections under the runner, not their semantic correctness. The listing flag is specific to this supplied runner, while Probe metadata belongs to Drydock; no general package interface is required. The plan and repair prompts do not explicitly distinguish flag-only declarations from complete commands; the provider repeated the malformed form despite feedback. Fix: plan repair normalizes matching full listing commands into flag-only probes, selects summary when supported, and rechecks selection; planning and repair prompts clarify the format. The actual preserved repair response passes all 15 probes against temporary copies. Local fix remains unverified until Ed resumes the affected stage. Regression: copied generator criterion succeeds with summary and a zero-selection neighbor fails; full commands remain rejected. A compatible existing plan requires declaration repair and verification; a fresh plan is required to evaluate changed authoring guidance. Outcome remains open.

### Run evidence

- `20261028.145919`: receipt `failed`; acceptance `NOT_RUN`; plan produced a draft and plan repair left 15 criteria outstanding. The prior August run does not prove this newly generated plan or current framework is equivalent.

## Decisions

- None.

## Questions

- None.

## Actions

- `2026-10-28` · jq-probe-01: Ed resumes the affected stage and verifies clean plan repair and subsequent build; semantic selection coverage remains unproved. No jq UAT rerun has verified this finding.

## Working Notes

- Full upstream warning and source coverage audit remains incomplete; no inference is made about other independent issues.
