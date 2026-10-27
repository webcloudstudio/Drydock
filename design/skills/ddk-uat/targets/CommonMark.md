# MEMORY: UAT CommonMark

| Field | Value |
|---|---|
| Version | 2026-10-27 V2 |
| Description | CommonMark UAT diagnosis and verification history. |
| Target | CommonMark (kit); commonmark (generated Target) |
| Evidence root | /mnt/c/Users/barlo/projects/drydock/uat/CommonMark |

## Intent

Preserve evidence-backed causes and verification status across CommonMark runs.

## Guardrails

- `2026-10-26` · Ed owns UAT execution and published evidence. Diagnosis does not mutate evidence or generated Targets.
- `2026-10-26` · Implementation repairs require explicit authorization. Ed authorized this memory, its central index link and their local commit.

## Details

### Current contract

- Authority: [ddk-uat](../../ddk-uat.md), [plan](../../../commands/plan.md), and supplied CommonMark sources.
- Scope: read preserved evidence; write this memory and its index. No UAT execution.
- Invariants: provider success does not establish artifact validity; each artifact requires its explicit closing marker. Boundary recovery does not prove body completeness or semantic validity.
- Proof: deterministic delimiter replay, then later clean affected-stage evidence after any repair. Local fixes remain unverified until that evidence exists.

### CM-ENVELOPE-001 — repeated missing Stage 1 closing markers

- Run/stage: `20261027.013501`, `04-plan`, initial topology and topology retry.
- Framework: Drydock 0.8.0, receipt commit `1b234d7695897805c50309266b81bffd6f862e31`.
- Source revision: source Git revision unknown; preserved `sources/INSTRUCTIONS.md` SHA256 `10b172786a92ad4dc012e88358cf96fcead95bcd919f2677df3a03405782fb0a`.
- Provider/model: `codex` / `gpt-6-luna`.
- Verdict: execution ERROR, acceptance NOT_RUN, not clean; Plan exits 1 before build.
- Cause: model output violates the explicit artifact envelope contract. Initial output opens TOPOLOGY.md at line 1 and DECISIONS.json at line 98, with neither close. Retry opens TOPOLOGY.md at line 1 and DECISIONS.json at line 347, then closes only DECISIONS.json at line 364.
- Evidence: run-relative `evidence/prompt_outputs/20261027.013551.484Z_commonmark_plan_codex.output.txt` and `20261027.013608.189Z_commonmark_plan_codex.output.txt`; matching `evidence/prompts/`, `evidence/provider_raw/`, `evidence/llm.jsonl`, and `evidence/commands/04-plan.stderr.log`.
- Both raw turns complete successfully; return codes are 0, truncation is null, and the adapter records `nested artifact opener` for both. Analyze records no envelope defect or repair. Provider completion and parser failure are consistent.
- Enforcement: `artifact_blocks.pair_artifact_delimiters`; `planning_session._stage_one_envelope_defect` and the one-correction Stage 1 budget. Regression coverage includes `test_malformed_stage_one_is_resubmitted_once_with_exact_defects` and `test_stage_one_correction_budget_is_shared_across_response_faults`.
- Deterministic reproduction: read preserved output into memory and call `pair_artifact_delimiters`. Initial unclosed tuple is `(TOPOLOGY.md, DECISIONS.json)`; retry unclosed tuple is `(TOPOLOGY.md,)`. Insert missing closes in memory only: both have two closed artifacts and no unclosed artifacts. No test suite or model call was run; evidence was not modified.
- Contract review: initial prompt already contains a complete two-artifact example and mandatory per-file close rule. Retry names both defects, repeats the emission contract and asks for a complete replacement. The failure is not explained by an absent instruction. Source/acceptance content does not cause delimiter rejection; topology semantics were not established by the boundary-only replay.
- Contributing mechanism: for Codex, `_artifact_retry_assembly` retains the full planning context and asks for a complete replacement. The retry prompt is 404,663 bytes; output grows from 6,941 to 16,057 bytes. This permits broad reauthoring during a framing correction. Context size causing the omission remains unproved.
- Initial recommendation (superseded by Ed’s draft-revision instruction below): separate envelope correction from semantic planning. A compact correction request should preserve bodies and change only boundary lines, with deterministic body-preservation and envelope validation plus existing semantic validation afterward. Keep a bounded failure path; do not infer completeness solely from an inserted close. Prompt wording can reduce errors but cannot guarantee them away.
- Prior history: the central ledger records recovered CommonMark envelope defects in `20261026.173709`; that row remains open with no fix commit. This run repeats the defect family and exhausts recovery; it does not prove regression of a repaired envelope mechanism.
- Fix commit: `981de1b` — Revise existing planning drafts during artifact retries.
- Diagnosis verification: read-only deterministic replay above. Subsequent repair verification is recorded below; no UAT rerun.
- Outcome: fixed for observed Plan stage in `20261027.022726` (Terra); see dated evidence below.

### Authorized draft-revision change

- Ed selected reuse and extension of the existing output, superseding the earlier envelope-only recommendation. No byte-preservation gate is added: content corrections are allowed.
- Generation adds one short instruction to finish and close TOPOLOGY.md before DECISIONS.json and check both pairs. Retry uses the complete prior response as its draft, preserving valid content while completing or correcting bodies and returning both complete artifacts.
- Prompt context remains unchanged: initial 396,281 bytes (387 KiB), retry 404,663 bytes (395 KiB) in the diagnosed run. Provider-reported input usage was 125,039 and 126,863 tokens. Largest initial parts: spec.txt 206,382 bytes, BLUEPRINTS_CONTRACT.md 68,140, task body 58,440, MANIFEST_CONTRACT.md 17,103, ANALYSIS.md 12,142. Context size is measured; causal attribution remains unproved.
- Existing strict parsing, semantic validation, retry exhaustion and provider session behavior remain authoritative. This small instruction change cannot guarantee model compliance.
- Local verification: 473 focused planning/reliability/prompt/header/memory tests passed; full suite 4,620 passed and 2 skipped; repository lint, changed-code formatting and diff checks passed. The added contract checks first failed against the old behavior. No provider call or UAT run was made for verification.

### 20261027.022726 — links repair stall

- Receipt: failed, execution ERROR, acceptance NOT_RUN (release acceptance not reached);
  terminal `10-initial-build-1` rc=1. Build's programmatic acceptance did run: links failed
  at 110/117. Cleanliness: not clean. Framework 0.8.0, receipt
  `c0fdece828331c229d3e7fa0780816d6d04eba83`. Provider Codex, planning Terra,
  build `gpt-6-luna`. Source INSTRUCTIONS SHA256 unchanged:
  `10b172786a92ad4dc012e88358cf96fcead95bcd919f2677df3a03405782fb0a`.
- Plan/verify pass with zero warnings; all six analyze/plan provider artifact records have
  no framing defect or recovery. Receipt commit descends from `981de1b`; the old
  CM-ENVELOPE-001 failure is absent in this affected-stage run. This is later clean planning
  evidence under a different planning model, not proof that every model always frames correctly.

### CM-SCOPE-001 — Stage 2 broadens an early gate beyond frozen topology obligations

- First causal authoring defect: Manifest links instructions (`MANIFEST.md:370-374`) explicitly
  assign image-dependent Links examples to image integration. Images is pending block 11 and
  depends on links; autolinks/raw HTML is pending block 12 and depends on images (`:379-424`).
  FEATURE-Links nevertheless selects the entire Links + Link reference definitions sections.
- Cases 519/533 require images (implemented early during repair); remaining case 522 needs
  nested image descriptions, 528/540 autolink URL encoding, and 495/496 raw-HTML precedence.
  The remaining reference cases 212/218 are current-story defects as well. This is a premature
  acceptance gate, not evidence that expected HTML should change or that all failures are merely
  missing dependencies. Fixing the two stalled edits alone would leave the schedule defect.
- Planning already receives the full frozen topology and generic availability instructions.
  Its old bounded ledger repeats artifact filenames but not their exact coverage obligations;
  Stage 2 emits a coarse section selector despite the topology's explicit later-integration
  assignment. Existing probes establish nonempty selection, not semantic prerequisite coverage.
- Fix: `33fb18b`. The bounded ledger now repeats only current-batch exact
  instructions and depends/provides/consumes interfaces at its recency anchor. Stage 2 and the
  Blueprint contract explicitly distinguish section titles from capability boundaries. Supported
  filters select available cases; if the runner cannot express the boundary, early acceptance
  tests the owned API without restating corpus examples and the whole mixed section runs on a
  later integration after all providers exist, before terminal verification. No case is dropped.
- Deterministic regression proves current-batch instructions/interfaces survive the handoff and
  deferred-story instructions are not injected into the bounded ledger. This does not statically
  validate semantic coverage or prove provider compliance. A fresh Plan is required; resuming
  this published build retains its old premature gate. Outcome: unverified.

### CM-REPAIR-001 — ineffective edits without regression-driven confirmation

- Stage: block-10, links. Governing FEATURE-Links and source corpus require the same HTML;
  expected HTML remains authoritative; the scope/schedule contradiction is CM-SCOPE-001 below.
  Dependency-frontier decomposition is present
  (18 blocks), unlike earlier merged parser runs. The scoped gate selects 117 authoritative
  Links + Link reference definitions cases and includes real image/autolink interactions.
- Measured calls: 87, 95, 100, 103, 110, 110, 110 passing. Call 7 correctly stops at two flat
  passes; rc=0 only means the provider completed. This is not a broken stall counter.
- Exact evidence: `evidence/prompts/`, `prompt_outputs/` and `provider_raw/` artifacts prefixed
  `20261027.031617.935Z`, `20261027.032014.335Z`, `20261027.032209.085Z`;
  `evidence/commands/10-initial-build-1.stdout.log:174-233`; source files under
  `build/commonmark/commonmark_parser/` (read only).
- Both flat prompts contain the seven failing IDs, criterion intent, prior note and full diff
  log path. Both agents read that log; this rules out absent feedback/log access as the cause.
  Prompts are about 29.6 KiB, not the earlier 395 KiB topology retry. Corpus/spec assets remain
  staged, but the final passes do not read the normative spec sections or algorithm appendix.
- Call 6 (`032014`) changes only ordinary-link destination quoting in inline.py. The two
  URL failures (528, 540) execute the separate autolink branch, which still only replaces a
  backtick and never percent-encodes brackets. Its transcript has reads/patches and empty shell
  commands, no conformance execution; the final claimed partial suite is unsupported by that
  transcript. No new test is added.
- Call 7 (`032209`) changes a definition-only setext case from dropping `===` to emitting a
  separate paragraph. Example 218 requires `===` and the following link in one paragraph;
  its targeted run explicitly remains red. It also runs 212, 495, 522, 528 and reads parser
  sources, but makes no further edit and adds no regression. No harness information shortage
  explains leaving that demonstrated ineffective edit as the final repair.
- Fix: `33fb18b`. Feedback includes a bounded complete counterexample,
  explicit unchanged-case notice, and instructions to reproduce before editing, trace the
  actual branch/governing source, add a red regression and run it plus a passing neighbor;
  revise a failed hypothesis within the call and label unrun checks accurately. The original
  inventory/full log, deterministic acceptance, stall limit and model selection remain.
- Verification: new feedback regression fails before the change; affected suite passes.
  This is improved prompting, not deterministic enforcement of agent tests or a guarantee of
  model convergence. Generated parser code and conformance assets were not patched.
- Outcome: unverified pending Ed's next affected build run.

### CM-DISPUTE-001 — product-description prose falsely routes recovery to Plan

- Stage: call 4 and terminal reporting. The model reports scoped links still fail and mentions
  "malformed reference definitions". `_defective_acceptance_claim` normalizes all failure
  fields into one word list, combines that adjective with "links conformance" in another
  field, and records links-conformance as disputed without an AC_BROKEN claim.
- Evidence: call-4 `20261027.031259.938Z` output, command log `:205`, terminal `:261-278`,
  and `build_run.py` prose classifier / cumulative reported_defective_ids recovery branch.
  A later ordinary product failure therefore recommends `plan verify`/`plan repair`.
  The false claim does not cause the stall; it corrupts recovery ownership.
- Deterministic reproduction: feed the preserved two report fields and failing criterion to
  the old classifier; it returns links-conformance. New regression returns no claim, while
  "the links-conformance check is malformed" still records the advisory dispute.
- Fix: `33fb18b`. Prose inference requires check name, defect vocabulary
  and criterion noun within the same sentence and report field. Explicit AC_BROKEN is retained.
- Outcome: unverified pending clean terminal recovery evidence from a later build failure.

### Local verification — 2026-10-27

- New regressions first failed against the previous implementation. Affected acceptance/build/
  repair/parser checks: 568 passed. Planning/parser/memory checks: 489 passed; final planning/
  handoff/prompt/memory checks: 484 passed. Final repair/isolation/ledger selection: 21 passed;
  the final complete new regression file passes all 11 tests after helper lint alignment.
- Full suite: 4,629 passed, 2 skipped, one shell smoke failure because its child selected system
  Python 3.10 (`datetime.UTC` unavailable). That exact smoke passes with the project's Python
  3.12 venv first on PATH. No product change or assertion weakening was needed for that failure.
- Repository lint, changed-file formatting and diff checks pass. Wheel build and isolated
  extracted-wheel execution pass; changed prompt/source/helper bytes match the wheel exactly.
- Published UAT files and generated products remain unchanged. Framework/prompt findings stay
  unverified until Ed's fresh affected-stage evidence; prompt compliance is not statically proved.

## Decisions

- None.

## Questions

- None.

## Actions

- `2026-10-26` · CM-ENVELOPE-001: clean Plan evidence in `20261027.022726` after `981de1b`
  verifies the affected-stage correction for the observed Terra run; model compliance remains
  bounded, not guaranteed. Historical diagnosis/implementation details above are retained.
- `2026-10-27` · CM-SCOPE-001 / CM-REPAIR-001 / CM-DISPUTE-001: code/prompt repairs implemented;
  Ed runs a fresh Plan/build and checks scope prerequisites, case progress and correct recovery. Local tests do
  not establish live model convergence. No UAT rerun was performed by this session.


## Working Notes

- None.
