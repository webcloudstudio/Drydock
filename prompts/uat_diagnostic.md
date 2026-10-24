---
name: uat_diagnostic
description: Investigate warnings, errors, recovered defects, and downstream failures in a running or completed Drydock UAT run, including a successful run.
version: 20261024 V7
intent: Assess operational success and clean execution separately, trace upstream warnings and errors through later artifacts and failures, and recommend the earliest corrective work supported by preserved evidence.
command: operator diagnostic prompt
output: A five-section diagnosis of about 250 words in single-line bullets, ending in a prioritized action list.
---

# Diagnose the Latest Drydock UAT Run

Act as Drydock's Principal Developer. Diagnose the UAT run requested by the operator, including a
running run or a successful run with warnings. This is working software: investigate only. Do not edit code, specifications, prompts,
tests, generated Target data, or UAT evidence, and do not rerun the UAT. The one write is the
diagnosis ledger described below. Recommend changes only after
the evidence establishes a cause. Preserve the distinction between a product defect, a Drydock
defect, a UAT-kit defect, a provider/model failure, and an expected control-flow exit.

## Start Here

1. Read the repository `AGENTS.md`. Never edit `docs/Drydock_Specification.md` without separate,
   block-specific authorization.
2. Resolve the kit as `uat/<Target>/` and its runs under `uat/<Target>/runs/<run-id>/`. Prefer the
   run named by the operator; when the operator describes a running run, resolve it from the
   supplied timestamps or messages. Otherwise use the newest run with `result.json`. For a
   running run, read available command streams and workspace LLM records without waiting for
   completion; report the missing receipt and final exit as pending, never infer a verdict.
3. Read these small indexes first:
   - `result.json` for the recorded verdict, terminal error, commands, exit codes, and usage totals.
   - `evidence/manifest.json` for the preserved command and LLM artifacts.
   - `index.html` only to verify what the report presented and linked.
4. For each non-zero command, read its exact files under `evidence/commands/`. Determine whether the
   exit is a lifecycle failure or an expected state signal such as `status --ready` returning 1 when
   no work remains. Treat stderr content as diagnostics, not as proof that stderr caused the exit.
   Also inspect zero-exit commands for warnings, rejected artifacts, repairs, and retries caused
   by defective output; a success code does not exempt their diagnostics from investigation.
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

## Clean Execution and Upstream Warnings

Ed's UAT standard is a clean run, not merely a successful run. A warning or error that required
repair, rejection, or recovery is a finding even when a later attempt succeeds or the receipt
says passed. Do not dismiss it as harmless because control flow continued. Recovery describes
what happened to the run; it does not fix or close the generating defect.

1. Inventory every warning, rejected artifact, automatic repair, defective-output retry, and
   source-contract substitution, including those from commands that exited zero. Group repeated
   messages by cause while identifying every affected artifact and stage.
2. Start downstream-failure analysis at the earliest upstream warning or error. Trace its input,
   emitted artifact, accepted or discarded content, and consumers through all later stages, even
   when the terminal failure occurs several steps later. Establish whether recovery actually
   removed the defect or only allowed contaminated or incomplete state to advance.
3. Classify each finding as a root cause, an independent defect, a consequence of an already
   recorded cause, or an expected contractual observation. An intentional red baseline, negative
   test, readiness signal, or product warning required by the fixture is expected only when the
   governed contract and evidence establish it. Continued execution is not that evidence.
4. State whether each upstream-to-downstream link is established, ruled out, or undetermined,
   naming the evidence or the missing evidence. Treat warnings as causal leads to investigate,
   never infer causation solely from their chronological order.
5. Recommend the earliest correction to the governed source, authoring contract, parser,
   validator, or execution adapter that the evidence supports. Do not recommend patching later
   generated code to accommodate a faulty upstream artifact. If no correction is established,
   name the specific missing investigation instead of declaring that no fix is needed because
   the retry succeeded.
6. Report cleanliness separately from the recorded run result: `clean` requires a completed
   successful run with no defective warnings, errors, or recoveries; `not clean` applies whenever
   such a defect is observed; `undetermined` applies when incomplete evidence prevents judgment
   and no defect has yet been established. Preserve the recorded verdict and exit codes.

## Diagnosis Ledger

`design/skills/ddk-uat.md` in the Drydock repository is this diagnostic's memory across runs. Its
header defines the columns and Outcome values.

1. Read it before diagnosing. Collect every row for this Kit, and every row whose Area names a file
   or function the evidence implicates.
2. Update the Outcome of earlier rows from this run: `fixed` when this run, on or after the fix
   commit, passed the affected stage without the same warning, error, or recovery; `recurred`
   when the same cause appears again, including when it recovers and the run succeeds.
3. Before recommending a change, read the fixes already committed in that Area. When one recurred,
   recommend revising or removing it rather than adding a layer beside it, and name its commit.
4. Append one row per root cause of this run, with Fix empty and Outcome `open`. A failed run always
   gets at least one row: when the evidence does not establish a cause, the row's Root cause reads
   `undetermined:` followed by the missing evidence.
5. Append one row for each other defect the diagnosis names: every contributing cause, independent
   defect, and Reporting Defect. Mark it in Stopped, after the stage, as `contributing`,
   `independent`, or `reporting`; give it Fix empty and Outcome `open`. A consequence of a recorded
   cause gets no row. This includes warnings and recovered defects in successful or running runs;
   successful recovery never excuses a defect from the ledger or closes it as fixed.
6. Change nothing else in earlier rows, and write no other file. Commit the ledger alone.

## Audit Specification Integrity First

Treat incorrect Sea Trials and acceptance criteria as specification contamination, not ordinary
test failures. They are governed inputs that planning can turn into Blueprints, Manifest stories,
implementation, and acceptance gates. Before blaming implementation or the model:

1. Compare every Sea Trial and acceptance criterion with the imported source, Compass, declared
   update sequence, and intended project boundary.
2. Identify behavior introduced only by Sea Trials and determine whether it verifies source intent
   or adds an unauthorized requirement.
   Also inspect governed source briefs for implementation choices presented as user requirements:
   distinguish a data invariant such as uniqueness of `(date, currency)` from a physical primary
   key or index choice. When the operator corrects that intent, recommend correcting the governed
   source rather than expanding Drydock to satisfy an accidental implementation prescription.
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
- State whether each issue stopped the run, recovered, or remains latent; recovery does not remove
  the requirement to investigate and correct the issue.
- Identify missing evidence and avoid filling it with assumptions.
- Prefer deterministic validation and explicit protocol states over relying on a model to infer an
  undocumented response.
- Recommend the smallest change that repairs the cause, plus regression tests. Do not recommend a
  broad rewrite or another expensive UAT until narrow tests pass.

## Output Contract

Return exactly five sections, in this order, under these headings. Every bullet is one short
sentence on one line. No paragraphs, no run-on sentences, no restated analysis. The whole report
targets 250 words: a reader who can diagnose the run themselves needs the facts and the file
paths, not the reasoning that produced them. Include every material finding even when the report
must exceed that target.

### Verdict

One line: the run id, recorded status, cleanliness (`clean`, `not clean`, or `undetermined`), and
terminal stage with its exit code, or pending completion when the receipt is absent.

### Root Cause

One-line bullets naming the earliest causal defects and independent warnings or recovered errors,
whether or not they stopped the run. Name the exact file and line where each defect lives and
state the evidence for any downstream causal link. When a ledger row holds the same cause, name
its run, fix commit, and new Outcome. Stop when the cause is stated; do not continue into effects.

### Consequences (not separate defects)

One-line bullets for downstream non-zero exits, failed criteria, and recovery outcomes that follow
from a root cause, linking each to its upstream finding. Independent defects belong under Root
Cause; a recovered warning is not demoted to a consequence merely because it did not stop the run.

### Reporting Defects

One-line bullets naming each place the run's own evidence failed to explain itself: discarded
output, truncated diagnostics, an unlinked or empty artifact, a verdict that contradicts the state
it reports. Cite the source location that drops the information. Omit the section when the evidence
was sufficient.

### Recommended Actions

A numbered list, most important first. Each item is a bold one-line change plus the source location,
with at most two indented sub-bullets: how it is verified, and its risk when the risk is not low.
Name any committed fix the action revises or removes.
Close with one line stating what to fix now and what to defer, one line stating any condition
that must hold before the UAT is rerun, and one line naming the ledger rows appended and the
earlier Outcomes changed. Do not make changes as part of this diagnostic beyond the
ledger.
