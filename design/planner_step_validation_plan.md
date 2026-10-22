# Complete and validate the planner one step at a time

Date: 2026-10-21
Status: Implementation committed as `48764ad`; deterministic whole-plan cases pass; live validation awaits
explicit approval to transmit the saved inputs to Anthropic through the subscription CLI.
Baseline: `9b83447`, with diagnosis bookkeeping through `ba3d7be`.

## Outcome

Deliver one coherent change: a consistent persistence planning contract, validated through the
complete `plan` command before advancing to `plan verify` and `build`. Reuse validated inputs
instead of rerunning import and analyze after every planner fix. A Blueprint batch is an internal
implementation detail, not the operator's unit of acceptance.

## Conversation record

This is the durable decision record for the conversation, not a verbatim tool transcript.

Ed initially requested confirmation that Codex has `/ddk-uat`, synchronization from Claude,
and a review of recent main-branch changes after the language and database encapsulation work.
Repeated `drydock uat LayersTesting --model claude-haiku-5-5` runs were not an effective
development loop.

The review established:

- Claude and Codex skill directories are identical; both load diagnostic prompt V4 and its ledger.
- Sixteen completed receipts through `20261021.231950` record 15 failures and 4.42 hours.
- Three runs stopped in analyze, six in plan, six in build, and one Luna run passed.
- Different revisions and generated plans prevent a controlled model comparison.
- Encapsulation and early validation are useful progress. Repeated local fixes have not yet
  demonstrated that the whole planning contract converges.
- The old continuation contract conflicted over database additions, full repairs, and emitting
  only the Current batch. Its final single-Feature request was 220,735 bytes.
- Scripted model replies test control flow; they do not establish live model compliance.
- Review follow-ups were committed in `5f790e9`; no UAT or model calls were executed.

Ed's follow-up, verbatim:

> ok do that with this feedback - i want clear and simple comments such that you can continue and i want this conversation persisted - it looks like we have been making steady progress - but its awful to do it this way - i would prefer to test 1 step at a time as opposed to 1 batch at a time.  i do want you to synthesize one completed change ... make a plan

Working interpretation: a step is a complete lifecycle command, beginning with `plan`, rather
than one model batch. Preserve steady progress and synthesize the fixes into one completed
capability. This turn produces the plan; it does not claim implementation is complete.

## Current implementation

Another session committed `9b83447` during the review. It replaces cumulative database additions
with a dedicated database batch, freezes the accepted declaration, and supplies
`DATABASE_compact.md` to later batches. Its tests cover batch placement, rejection, retries,
seed merging, compact injection, and refusal of later changes. These are existing changes to
review and complete, not work to duplicate. The diagnosis remains `unverified`.

## Implementation plan

1. **Review the complete contract.** Read `design/commands/plan.md`, foundations and acceptance
   guidance, then review `9b83447` across prompts, assembly, database merge, validation, and tests.
   Check that database authoring receives every requirement needed by later Features. Parsing
   alone does not prove operation coverage. Check that seed merge preserves required columns
   and constraints, and compaction preserves the entire callable interface.
2. **Complete one implementation.** Resolve demonstrated gaps in that contract together. Keep
   one declared output set per phase, one database acceptance rule, and explicit refusal reasons.
   Revise obsolete retry wording rather than adding another retry layer. Reduce context only
   where its irrelevance is established; preserve source requirements and consumed interfaces.
3. **Prove the complete plan step deterministically.** Use a synthetic temporary Target and fake
   runner to exercise topology, database authoring, dependent Features, final Manifest, and
   verification through the application entry point. Include CRUD operations, invalid database
   repair, omitted required seed fields, undeclared Feature operations, and frozen database edits.
   Assert final artifacts and failure behavior, not only prompt substrings or call counts.
4. **Exercise the complete plan step with the configured model.** Prepare a disposable development
   Target outside `uat/` and outside generated production Targets. Preserve its pre-plan inputs.
   Run the normal `plan` command through the subscription-authenticated CLI adapter, with a
   bounded existing retry budget and recorded model, revision, prompts, outputs, and timings.
   Stop at the command boundary. A failure is diagnosed and retested at this step; it does not
   trigger another import/analyze/UAT cycle. Start each planner retest from the same saved inputs.
5. **Advance one command at a time.** After plan passes, retain that output and run `plan verify`.
   Advance to build only after verification is clean. Inspect build's own budget and stopping
   behavior before executing it. A planner change invalidates downstream validation; a build-only
   fix reuses the validated plan. Do not quietly repair acceptance criteria to fit delivered code.
6. **Close the capability.** Run relevant regression tests and required lint/full-suite checks
   after inspecting that they cannot access published `uat/`. Update behavior documentation,
   README where applicable, changelog, and the diagnosis ledger with the actual fix commit.
   Keep unit, live-step, and UAT verification claims separate. Ed performs the final clean UAT.

## Step evidence

Each development step records: input snapshot identifier, repository revision, requested and
executed model, exact command, exit code, output artifacts, elapsed time, and next permitted step.
Use existing Drydock evidence wherever possible; do not introduce a new workflow engine or
public command unless inspection establishes that the existing commands cannot support this.

Existing UAT `--from-step` / `--to-step` controls are operator tools. An agent does not invoke
them, modify a published run, or treat a resumed run as a clean benchmark. Development fixtures
and evidence stay in a separate disposable workspace under the session directory.

## Comments and continuation

Use short comments that explain the invariant or reason, for example:

- "Freeze the database before authoring Features that consume it."
- "Keep source-declared columns when merging the authored schema."
- "Reject this batch before accepting any dependent Feature."

Do not narrate obvious code or copy run histories into implementation comments. Keep historical
evidence in `design/uat_diagnoses.md`. After each work session, update the checklist below with
the result, verification command, commit, and next action. Record failures as failures.

## Completion checklist

- [x] Persist conversation decisions and this implementation plan.
- [x] Review and complete the contract introduced by `9b83447`.
- [x] Pass deterministic integration tests for the whole plan command.
- [ ] Pass the live plan step from preserved inputs outside `uat/`.
- [ ] Pass plan verification against that output.
- [ ] Validate build separately against the accepted plan.
- [x] Complete required checks, documentation, and local commits.
- [ ] Ed runs clean UAT; record its result without overstating earlier evidence.

## Execution record

2026-10-21:

- Reviewed `9b83447`. Found that authored column types could override seeded types and composite
  source constraints could disappear. Added parsed-column comparison and restoration of omitted
  composite constraints before the database freezes; rejection enters the existing retry path.
- Added whole-command CRUD integration cases through Manifest creation and `plan verify`, with
  a valid response and a changed-column response followed by repair. Both pass.
- Also found that topology text order could put a Feature before database authoring. The
  database is now the first authoring batch; a regression test lists a Feature first and verifies
  that database acceptance still precedes it.
- Repository lint and formatting pass. Full regression suite is in progress.
- Saved LayersTesting inputs and their hashes under `logs/planner-step-validation/inputs/`.
  The development workspace is separate from published UAT. No published evidence was changed.
- Live attempt 01 encountered sandbox transport retries and was interrupted before model output.
  Auto-review rejected network escalation because transmission of these files to Anthropic
  requires explicit consent. Asked Ed that precise question; do not retry until answered.
- Local receipts, prompts, and test output live under `logs/planner-step-validation/` (untracked).

Next action: after transmission approval, run the complete plan step on the saved inputs,
then verify and build separately. Do not rerun import, analyze, or UAT.

2026-10-22 continuation:

- Ed authorized execution: "yes please - execute the plan", then asked "continue - did the
  last command finish?" The live transmission approval remains unanswered.
- Final focused regression run: 385 passed in 310.67 seconds across database schema, planning,
  plan verification, and persistence generation tests.
- Full suite stopped after 2,107 passed, one skipped, and three adapter-test failures. Those tests
  attempted to copy real user authentication into the persistent Codex home. Added a private
  temporary provider home to `tests/test_llm.py`; all 96 adapter tests pass. The full suite is
  rerunning with that isolation fix.
- No runtime adapter behavior was changed. No live plan, verify, or build success is claimed.

- Implementation committed as `48764ad` (`Freeze source-faithful database contracts before
  authoring Features`). The latest UAT ledger row includes this follow-up and remains `unverified`.

- Final full-suite result: `PYTEST_XDIST_AUTO_NUM_WORKERS=8 python -u -m pytest -n auto`:
  **3,892 passed, 2 skipped in 533.22 seconds**. Output: `logs/planner-step-validation/pytest-final.log`.
- `ruff check src/ tests/`, `ruff format --check src/ tests/`, and `git diff --check` pass.
- Local implementation and deterministic verification are complete. Live plan, separate verify,
  and build remain pending explicit transmission approval. Do not infer model convergence from
  these local results. The UAT ledger outcome remains `unverified`.
