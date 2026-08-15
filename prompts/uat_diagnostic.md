---
name: uat_diagnostic
description: Diagnose the latest Drydock UAT run without changing the repository or generated run evidence.
version: 20260815 V3
intent: Find the latest requested UAT run, establish its actual failure chain from preserved evidence, separate the root cause from its consequences, and recommend bounded corrective work in a form an operator can read at a glance.
command: operator diagnostic prompt
output: A five-section diagnosis of about 250 words in single-line bullets, ending in a prioritized action list.
---

# Diagnose the Latest Drydock UAT Run

Act as Drydock's Principal Developer. Diagnose the latest completed UAT run for the Target named by
the operator. This is working software: investigate only. Do not edit code, specifications, prompts,
tests, generated Target data, or UAT evidence, and do not rerun the UAT. Recommend changes only after
the evidence establishes a cause. Preserve the distinction between a product defect, a Drydock
defect, a UAT-kit defect, a provider/model failure, and an expected control-flow exit.

## Start Here

1. Read the repository `AGENTS.md`. Never edit `docs/Drydock_Specification.md` without separate,
   block-specific authorization.
2. Resolve the kit as `uat/<Target>/`. Resolve its latest completed run from
   `uat/<Target>/runs/<run-id>/`, preferring the run named by the operator; otherwise use the newest
   run with `result.json`. Do not assume the latest directory entry is complete.
3. Read these small indexes first:
   - `result.json` for the recorded verdict, terminal error, commands, exit codes, and usage totals.
   - `evidence/manifest.json` for the preserved command and LLM artifacts.
   - `index.html` only to verify what the report presented and linked.
4. For each non-zero command, read its exact files under `evidence/commands/`. Determine whether the
   exit is a lifecycle failure or an expected state signal such as `status --ready` returning 1 when
   no work remains. Treat stderr content as diagnostics, not as proof that stderr caused the exit.
5. For each implicated LLM call, find its row in `evidence/llm.jsonl`, then inspect only its linked
   assembled prompt, output, raw provider transcript, stderr artifact, and `.llm.log` when present.
   Compare provider success with downstream parse/validation success; they are separate outcomes.
6. Trace the failing message into `src/drydock/` with `rg`, then read the narrow parser, validator,
   caller, and relevant tests. Compare the emitted model text with the accepted output grammar.
7. For import/refit failures, also inspect `LINEAGE.json`, the pending source version, the initial and
   updated kit sources, the injected diff, the existing Manifest story graph, and the Blueprints.
   Establish whether the update was already implemented, whether a real delta was available, and
   whether the output contract represents a valid no-op/already-satisfied result.
8. Use Git history only to identify a regression or changed contract. Do not infer causation from a
   commit subject; verify it against the run evidence and current code.

## Audit Specification Integrity First

Treat incorrect Sea Trials and acceptance criteria as specification contamination, not ordinary
test failures. They are governed inputs that planning can turn into Blueprints, Manifest stories,
implementation, and acceptance gates. Before blaming implementation or the model:

1. Compare every Sea Trial and acceptance criterion with the imported source, Compass, declared
   update sequence, and intended project boundary.
2. Identify behavior introduced only by Sea Trials and determine whether it verifies source intent
   or adds an unauthorized requirement.
3. Check whether a later update requirement entered the initial plan through a Sea Trial.
4. Trace each suspect criterion through `ANALYSIS.md`, Blueprints, `MANIFEST.md`, generated acceptance
   code, delivered code, and scoring evidence. State the contamination path explicitly.
5. If a governed criterion is wrong, classify the run as specification-contaminated. Recommend
   correcting the governed input and starting a clean UAT; do not repair generated code to satisfy it.

## Required Analysis

- Identify the first causal defect and the terminal failure separately from preceding incidental or
  expected non-zero exits.
- Explain apparent contradictions explicitly: successful provider return followed by parser failure,
  success text on stderr, missing report links despite files in the workspace, or a requirement that
  produced no stories.
- State whether each suspected issue actually failed the run.
- Identify missing evidence and avoid filling it with assumptions.
- Prefer deterministic validation and explicit protocol states over relying on a model to infer an
  undocumented response.
- Recommend the smallest change that repairs the cause, plus regression tests. Do not recommend a
  broad rewrite or another expensive UAT until narrow tests pass.

## Output Contract

Return exactly five sections, in this order, under these headings. Every bullet is one short
sentence on one line. No paragraphs, no run-on sentences, no restated analysis. The whole report
targets 250 words: a reader who can diagnose the run themselves needs the facts and the file
paths, not the reasoning that produced them.

### Verdict

One line: the run id, its status, and the terminal stage with its exit code.

### Root Cause

One-line bullets tracing the first causal defect to the stage that stopped. Name the exact file and
line where the defect lives. Stop when the cause is stated; do not continue into effects.

### Consequences (not separate defects)

One-line bullets for every other non-zero exit, failed criterion, or anomaly that followed from the
root cause. State plainly which of these are not independent defects. Any failure that is genuinely
independent is stated here as such, or belongs under Root Cause.

### Reporting Defects

One-line bullets naming each place the run's own evidence failed to explain itself: discarded
output, truncated diagnostics, an unlinked or empty artifact, a verdict that contradicts the state
it reports. Cite the source location that drops the information. Omit the section when the evidence
was sufficient.

### Recommended Actions

A numbered list, most important first. Each item is a bold one-line change plus the source location,
with at most two indented sub-bullets: how it is verified, and its risk when the risk is not low.
Close with one line stating what to fix now and what to defer, and one line stating any condition
that must hold before the UAT is rerun. Do not make changes as part of this diagnostic.
