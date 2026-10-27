# MEMORY: UAT CommonMark

| Field | Value |
|---|---|
| Version | 2026-10-26 V1 |
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
- Outcome: unverified.

### Authorized draft-revision change

- Ed selected reuse and extension of the existing output, superseding the earlier envelope-only recommendation. No byte-preservation gate is added: content corrections are allowed.
- Generation adds one short instruction to finish and close TOPOLOGY.md before DECISIONS.json and check both pairs. Retry uses the complete prior response as its draft, preserving valid content while completing or correcting bodies and returning both complete artifacts.
- Prompt context remains unchanged: initial 396,281 bytes (387 KiB), retry 404,663 bytes (395 KiB) in the diagnosed run. Provider-reported input usage was 125,039 and 126,863 tokens. Largest initial parts: spec.txt 206,382 bytes, BLUEPRINTS_CONTRACT.md 68,140, task body 58,440, MANIFEST_CONTRACT.md 17,103, ANALYSIS.md 12,142. Context size is measured; causal attribution remains unproved.
- Existing strict parsing, semantic validation, retry exhaustion and provider session behavior remain authoritative. This small instruction change cannot guarantee model compliance.
- Local verification: 473 focused planning/reliability/prompt/header/memory tests passed; full suite 4,620 passed and 2 skipped; repository lint, changed-code formatting and diff checks passed. The added contract checks first failed against the old behavior. No provider call or UAT run was made for verification.

## Decisions

- None.

## Questions

- None.

## Actions

- `2026-10-26` · CM-ENVELOPE-001: Ed authorized a small generation-contract change and draft-based repair, explicitly permitting content completion and revision rather than closing markers alone. Implementation retains source context and the one-retry budget; local verification is recorded in Details. Ed's later clean Plan-stage UAT is required to verify model compliance.

## Working Notes

- None.
