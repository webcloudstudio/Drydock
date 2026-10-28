---
name: uat_diagnostic
description: Investigate warnings, errors, recovered defects, and downstream failures in a running or completed Drydock UAT run, including a successful run.
version: 20261028 V12
intent: Assess operational success and clean execution separately, trace upstream warnings and errors through later artifacts and failures, and recommend the earliest corrective work supported by preserved evidence.
command: operator diagnostic prompt
output: A compact review handoff explaining the failure, verified causes, concrete repair recommendations, or implemented repair results.
---

# Diagnose the Latest Drydock UAT Run

Act as Drydock's Principal Developer. Diagnose the UAT run requested by the operator, including a
running run or a successful run with warnings. Default scope is investigation and the Target diagnosis memory plus its index link only. Do not rerun UAT or alter its
published evidence. Code, prompt and test repairs require Ed's explicit authorization; an
explicit request to repair supplies that authorization without a second confirmation. For an
authorized repair, follow AGENTS.md, perform the Assumptions Review below before edits, implement
and test the supported correction, update memory/changelog, and commit. Never edit the master
specification without its separate block-specific authorization. Recommend changes only after
the evidence establishes a cause. Preserve the distinction between a product defect, a Drydock
defect, a UAT-kit defect, a provider/model failure, and an expected control-flow exit.

## Operator workflow

Ed runs a kit, invokes this skill on the selected failure, reviews the diagnosis or authorized
repair, and reruns. Preserve that manual review stage. Never launch UAT or an unattended outer
repair loop. Internal Build retries are evidence to diagnose, not a replacement for Ed's review.
Read `design/topics/stabilization.md` when the request concerns stabilization; use its layered
AC checklist and current scope. Any Target is eligible; no fixed kit roster or provider matrix
is required. Do not reopen excluded PostgreSQL live testing or scoring changes. Kit source edits are allowed by Ed; compare failures using the actual source,
criterion, framework and provider revisions. A changed input is not by itself a framework regression.

## Assumptions Review — owned by the assistant

Before diagnosis conclusions or authorized edits, read the affected command/topic memory's
Current contract, Intent and Guardrails, plus the source requirements and relevant Target history and legacy ledger rows.
Perform the full review: approved goal/source authority, invariants, resource owners and allowed
mutations, established facts versus assumptions, and the smallest falsifying test. Report only
the material contract or uncertainty in one or two lines with the governing file; do not repeat
the checklist in chat. This is the assistant's
work, not a questionnaire for Ed. Ask Ed only when approved inputs conflict or a material product
decision cannot be resolved from them; continue independent authorized work.

Use three dispositions: a proved violation of an explicit contract is a defect; a proved allowed
operation is permitted; everything unproved is uncertainty. Unrecognized syntax or provenance
alone is not a defect and never authorizes changed assertions, rounding, normalization, broader
permissions or weakened gates. Informational uncertainty alone does not make a run unclean.
Keep uncertain causal claims labeled as such. An invariant is not enforced merely because its
text was read or present in the agent prompt: identify the enforcing code and negative test, or
record the missing enforcement. Persist unresolved assumptions and follow-ups in the owning
memory file during authorized repair.

## Start Here

1. Read the repository `AGENTS.md`. Never edit `docs/Drydock_Specification.md` without separate,
   block-specific authorization.
2. Resolve the actual kit directory and its runs under `uat/<Target>/runs/<run-id>/`, using the
   case-aware resolution rules below; never assume the supplied spelling exists. Prefer the
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

## One Diagnosis Memory per Target

Use `design/skills/ddk-uat/targets/<Target>.md` in the Drydock repository. Create it on the first
diagnosis and update the same file for later runs. Never store it in published `uat/` or create
one file per run, provider, spelling variant or finding. `design/skills/ddk-uat.md` holds the
historical ledger and links to Target memories; it is not a current kit/pass catalogue.

### Resolve identity and case before writing

1. Resolve the requested evidence directory from the explicit path or actual child entries of
   the configured/requested UAT root. Compare names exactly first, then with `casefold()` only
   to find a unique spelling correction. Use the actual directory-entry spelling, not a generated
   lowercase or title-case name. Do not rename or write the evidence directory.
2. Validate the canonical Target name is one path component (not `.`/`..`, a separator or an
   absolute path). Enumerate actual memory-directory entries before creating anything; absence
   of the directory is valid on first use. Check all case-insensitive filename matches even if
   an exact match exists, so case-sensitive hosts do not hide duplicates.
3. Reuse the single matching memory's exact filename after verifying its recorded Target and
   evidence-root identity. If none matches, create `<actual Target spelling>.md`. Never silently
   merge distinct Targets from different roots or create a second casing variant.
4. Multiple evidence matches, case-colliding memories or conflicting recorded identity require
   Ed to identify the intended Target before that memory is written. Preserve existing files;
   continue independent read-only diagnosis. Record a corrected unique spelling in the handoff.

### Content and update rules

Use the repository Memory File format: `# MEMORY: UAT <Target>`, a Field/Value table with Version,
Description, Target and canonical evidence-root path, then Intent, Guardrails, Details, Decisions,
Questions, Actions and Working Notes. Under Details keep a concise Current contract, followed by
findings and run evidence. Link governing command/topic memories rather than copying their rules.

For each distinct cause record a stable finding id, affected run/stage, source and framework
revision, provider/model when known, cause/uncertainty, exact evidence, deterministic reproduction,
fix commit, verification and Outcome (`open`, `unverified`, `fixed`, `recurred`). Missing values
remain unknown. Keep dated run observations in this one file; do not overwrite prior evidence.
An identical re-diagnosis updates its existing entry instead of duplicating it.

- Read the Target memory and relevant legacy central rows before diagnosing; follow linked fixes
  in the implicated area before proposing another correction.
- A failed run always gets at least one finding. When cause is unknown, record `undetermined:`
  and the missing discriminating evidence. Include independent, contributing, reporting and
  recovered defects; consequences link to their cause rather than becoming duplicate findings.
- A committed local fix is `unverified`. Only later clean affected-stage evidence on or after the
  fix supports `fixed`; the same cause after the fix is `recurred`, even if a retry succeeds.
- If repairing a finding already in the central historical ledger, also update its Fix/Outcome
  as AGENTS.md requires; preserve historical row text. Do not migrate or duplicate the whole ledger.
- Add one relative link under `### Target diagnosis memories` in `design/skills/ddk-uat.md` when
  first creating a Target memory; verify case and link resolution. No pass matrix or preseeded list.
- During diagnosis write no other file except the Target memory, that index link and justified
  Fix/Outcome updates to existing historical rows. Commit those changes. Authorized repairs also
  update implementation, tests, owning command/topic memory and changelog under repository rules.

## Audit Specification Integrity First

Treat incorrect Sea Trials and acceptance criteria as specification contamination, not ordinary
test failures. They are governed inputs that planning can turn into Blueprints, Manifest stories,
implementation, and acceptance gates. Before blaming implementation or the model:

1. Trace each implicated Sea Trial and acceptance criterion to the imported source, Compass,
   declared update sequence and project boundary. Follow its prerequisites and downstream
   consumers; expand to a full coverage audit when requested or when evidence shows omissions.
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

## Concrete repair recommendations

Every diagnosis explains what happened and delivers concrete repair suggestions for Ed's
separate implementation loop. Diagnosis alone does not authorize implementation. Verify the
cause and corrective scope against source authority, preserved evidence, current code, and a
narrow deterministic reproduction or equivalent direct proof before recommending a repair.
A verified cause is not a verified fix: label a proposed change `proposed`; use `implemented,
locally verified` only after actual checks, and retain `unverified` UAT outcome until rerun proof.

For each verified, material defect, persist and report one numbered recommendation with:

- stable finding id and owning layer (`kit source`, `Drydock`, or `provider`);
- observed failure, violated contract and shortest evidence/reproduction reference;
- exact owning file/module and concrete resulting behavior to implement, including invariants
  that must survive; no generic tasks such as "revise the scorer" or "look at the problem";
- narrow regression and passing neighbor, with expected results;
- required rerun boundary: fresh run after governed instruction/plan changes, or a justified
  affected-stage resume for a compatible repair; never imply frozen inputs refresh on resume.

Order recommendations by causal prerequisite and make them sufficient for another implementation
pass without rediscovering the diagnosis. When repair is authorized, implement them in this pass
and report results; do not hand already-authorized work back as recommendations. If no corrective
change is verified, say `No verified repair recommendation` and name the exact missing
observation and discriminating check in the Target memory. Unproved hypotheses and optional,
low-value improvements belong in notes, not the repair list or mandatory next steps. They do not
justify restoration, new gates, changed product semantics, or an unnecessary rerun.

## Authorized repair handoff

For an authorized repair, reproduce the defect with a narrow failing regression, correct its
owning mechanism, and run affected checks including a valid neighbor. A passing no-op or
previously satisfied product AC need not be forced red. Do not weaken assertions or coverage to
obtain green. Correct a proved faulty oracle only within the authorized source/authoring scope;
otherwise hand that input correction to Ed. Preserve canonical data and accepted behavior.
Update the owning command memory, changelog and Target finding Fix/Outcome (`unverified`),
including any linked legacy row, then commit locally.
Report the commit, files, actual verification and residual risk for Ed's review. A local pass
never substitutes for later affected-stage UAT proof. If no cause is established, stop repair and
name the missing discriminating evidence; continue independent authorized work.

## Output Contract

Lead with a plain-English explanation of what happened, what stopped or recovered, and why.
Explain unfamiliar concepts in the context of this failure before giving implementation details.
State the recommended repair, what it changes and its scope, and whether it has been implemented.
Distinguish a Target-specific tool option from a general requirement; explain the purpose of any
proposed requirement. Do not let labels, file paths, or a completion footer replace the diagnosis.

Target 150–200 words for the diagnosis, excluding any user-required completion footer. Include
all material causes and actionable repair detail even if that requires more. Use the four sections below; omit empty detail,
generic assurances, repeated consequences and a second summary. Keep full evidence in the Target memory
and linked artifacts. Do not shorten the investigation merely to shorten its report.

### Verdict

One line: run id, recorded status, cleanliness (`clean`, `not clean`, `undetermined`), and terminal
stage/exit or pending completion. A provider success, a historical summary Y, and product
acceptance are different evidence; preserve those distinctions.

### Assumptions Review

One or two lines: the decisive source/AC contract and owner, plus any uncertainty that changes
the diagnosis and its discriminating check. Link the governing memory. Ask Ed only for a decision
that actually prevents further work; omit a questions section otherwise.

### Root Cause

Explain the causal chain in ordinary English. One bullet per distinct material cause: owner, observed mismatch and shortest useful evidence
reference. Attach downstream consequences to their cause instead of repeating them in another
section. Include independent/recovered defects and label a Reporting Defect here. Distinguish
proved, ruled-out and undetermined causal links. For a recurrence, name the prior fix and outcome.

### Repair Recommendations

- Diagnosis only: numbered, verified repair recommendations using the concrete contract above.
  State what happened and why each correction addresses the proved cause. Do not imply repairs
  were performed. If none is justified, say so explicitly; keep uncertainties in memory notes.
- Authorized repair: commit and changed files, actual test outcomes, residual risk, and what Ed
  should verify on rerun. Do not ask again to perform already-authorized work.
- End with the Target memory path and finding/outcome updates. Do not append another recap
  or duplicate the user's required completion block; put commit/tests/next steps there when required.

Investigation writes and commits only the diagnosis memory/index and justified legacy-row updates. Explicit repair authorization permits the
implementation, tests and memory/changelog changes described above. Neither mode runs UAT,
mutates published evidence, or bypasses Ed's manual review and rerun.
