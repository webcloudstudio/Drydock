# MEMORY: plan_ac_intent_and_tdd

| Field | Value |
|---|---|
| Version | 2026-10-26 V1 |
| Description | Deferred plan for AC intent metadata, authorized fixtures, and TDD repair context. |
| Status | Ready for review or later execution; implementation deferred. |
| Modules | `acceptance.py`, `acceptance_oracle.py`, `plan_verify.py`, `plan_repair.py`, `ac_repair.py`, `planning_session.py`, `build.py` |
| Related | [Acceptance criteria](acceptance_criteria.md), [Plan](../commands/plan.md), [Build](../commands/build.md) |

## Intent

Use TDD: Plan synthesizes the available material into a feature or screen specification,
authors deterministic acceptance criteria for that behavior, and Build implements against
that contract. Every AC has concise intent metadata explaining what it proves and, where
helpful, why its example inputs and expected results exercise the behavior. Repair prompts
receive that metadata verbatim.

Plan is authorized to choose test inputs and calculate expected outputs. Source material
need not contain each example. A division requirement permits Plan to select 6 / 3 == 2.
Unknown provenance of an example decimal is not a useful advisory or a test defect.

## Guardrails

- `2026-10-26` · Documentation only in this session. Ed deferred implementation to avoid
  interfering with an active complex session. Do not change code or generated Target state.
- `2026-10-26` · Preserve dependency verification. An AC importing `persistence` before its
  database owner delivers it must fail Plan admission; otherwise the plan cannot build.
- `2026-10-26` · Preserve specified behavior. An unspecified rounding policy is a specification
  gap; choosing `.005` as a fixture is ordinary test design. Conflating them invents behavior.
- `2026-10-26` · Never change expected results to fit implementation output or silence a
  provenance warning. Doing so defeats TDD.
- `2026-10-26` · Reuse existing intent metadata. A second comment schema or per-value citation
  system adds redundant contracts and is outside this plan.
- `2026-10-26` · No UAT invocation or evidence mutation. Ed owns UAT. The protected master
  specification still requires separate authorization for each edited block.

## Details

### Current contract

This document records approved direction and deferred implementation, not shipped behavior.
Read-only inspection on 2026-10-26 established:

| Concern | Existing mechanism |
|---|---|
| Intent metadata | `acceptance.py` already recognizes `Intent:` and stores `ProgrammaticAcceptance.intent`. |
| Missing intent | `_parse_ac_block` falls back to the criterion ID, so a populated parsed field does not prove an explicit declaration exists. |
| Repeated declarations | The parser joins repeated `Intent:` values with spaces; normalized intent cannot preserve the original lines verbatim. |
| Decimal warnings | `acceptance_oracle.decimal_provenance_advisories` scans decimal-looking string expectations and checks supplied/cited text; `plan_verify.py` emits the advisories. |
| Plan repair | `_block_bodies` and `_defect_part` already transport the original AC body, including metadata. |
| AC repair | `ac_repair.assemble` includes the original block and specification context. |
| Build repair | Audit all current feedback paths after the active session finishes; complete end-to-end preservation where missing. |

The warning is not evidence of a native-language type error. The heuristic specifically
selects strings. Recheck current code before implementation because concurrent work continues.

### Target contract

1. Plan uses all available material to specify the relevant behavior, respecting source
   requirements and authorized design decisions.
2. Plan selects useful fixtures, boundaries, and negative cases. Expected results follow
   the specification; the exact constants need not appear in imported sources.
3. Every newly authored AC declares meaningful, nonempty `Intent:` metadata. One or two
   concise lines describe the behavior, expected relationship, and useful fixture rationale.
   A table of examples can share one explanation; individual constants need no provenance log.
4. Native test code owns types and assertions. `0.005`, `"0.005"`, and `Decimal("0.005")`
   retain their language-defined meanings. Static scanning must not coerce them.
5. Build implements the specified behavior until the tests pass. A failed AC does not grant
   permission to rewrite its expectation. Independent known answers must not be calculated
   by calling the same product operation under test.
6. A demonstrated AC/specification contradiction follows the appropriate existing Plan repair
   route. Mechanical repair fixes mechanics without choosing new product policy. Genuine
   unspecified behavior is resolved during specification authoring, not by literal scanning.
7. Remove unknown-decimal-provenance advisories. Keep dependency, syntax, prerequisites,
   vacuity, actual product binding, declared-order contradictions, source integrity, and
   readiness checks. An ordinary generated fixture must not become non-binding merely because
   its literal is absent from source material.

### Existing metadata is the provenance location

Use the current AC container and its leading metadata declarations. The following excerpts
omit the surrounding AC delimiters; no new container syntax is proposed.

```text
Intent: Return the quotient for supported operands and a nonzero denominator; 6 / 3 must equal 2.

from calculator import divide
assert divide(6, 3) == 2
```

For a specification requiring integer cents formatted as text with two fractional digits:

```text
Intent: Format integer cents as decimal text with exactly two fractional digits.
Intent: Plan-selected cases cover zero, signs, and magnitude; 5 cents must produce "0.05".

from csv_output import format_cents
for cents, expected in [(0, "0.00"), (5, "0.05"), (-5, "-0.05"), (1250, "12.50")]:
    assert format_cents(cents) == expected
```

For exact text preservation:

```text
Intent: Preserve supplied text exactly; ".005" is a Plan-selected example exercising a leading decimal point.

from text_store import round_trip
assert round_trip(".005") == ".005"
```

These illustrate metadata, not new requirements for LayersTesting. Retain `Cite:` where
published text or an authoritative suite warrants it. Do not require citations for ordinary
Plan-selected examples or add a provenance enum to every AC.

### Repair prompt contract

Deterministic prompt assembly supplies each implicated AC's identity, original metadata and
proof body, concrete failure or defect, and relevant specification context. Preserve existing
AC-repair isolation from product source/output so expectations cannot be fitted to the product.
Implementation repair receives its normal implementation evidence plus the AC intent.

Copy every original `Intent:` declaration line verbatim, including punctuation, quoting,
spacing, and order. Do not reconstruct it from normalized `check.intent`, summarize it, or
substitute the criterion ID. Keep the complete block through budgeting, continuation, and
retry paths. Use existing explicit budget-failure handling instead of silently losing intent.

Repair instructions must convey:

> Implement the specified behavior so this criterion passes. Fixture values are intentional
> examples selected during Plan. Failure does not authorize changing the expected result.
> Preserve the AC intent. Report a demonstrated contradiction with the specification through
> Plan repair; do not infer a new policy from unfamiliar literals.

Mechanical syntax/import repair remains available within its existing scope. It must preserve
intent and cannot invent behavior from failed implementation output.

### Implementation sequence

1. **Reconcile current work.** Read current memories, code, and diffs after the active session.
   Locate all AC authoring, admission, serialization, and repair paths, including language
   adapters. Preserve changes made by that session.
2. **Strengthen authoring.** Update governed AC contracts and applicable Plan prompts to
   require explicit intent. Validate raw metadata presence, not the criterion-ID fallback.
   Route missing/blank declarations through existing bounded authoring correction. Do not
   introduce a keyword-based semantic validator for intent prose.
3. **Preserve repair context.** Retain existing raw-block transport in Plan and AC repair;
   fill gaps in Build feedback and continuation/budget paths. Avoid a second serialization.
   Protect intent from mechanical rewriting.
4. **Remove the advisory.** Remove decimal-provenance producer/wiring and update its tests.
   Keep the other static checks. Audit binding heuristics only for demonstrated conflicts
   with authorized fixtures; preserve published-source fidelity and independent-suite rules.
5. **Verify TDD behavior.** Prove useful fixtures are admitted, failures reach implementation
   repair with intent, and expectations stay fixed unless a real AC defect is established.
6. **Update documentation and commit.** Update affected command/topic memories, authoring
   contracts, and changelog truthfully. Record protected-spec differences without editing
   that document. Commit implementation separately from this plan.

Existing artifacts without explicit intent continue to parse; deploying this change must not
make them unbuildable solely for that omission. Require explicit intent for newly authored or
deliberately regenerated AC. A later explicit replan can supply intent from specifications.
Do not bulk-migrate active Targets or mutate artifacts during read-only verification.

### Verification and acceptance

Use temporary fixtures and fake runners. No model call, API credits, or UAT is needed.

| Case | Required result |
|---|---|
| Metadata | One/two intent lines parse; original declarations survive repair assembly verbatim. |
| Authoring | Missing/blank intent triggers bounded correction for newly authored AC; ID fallback does not satisfy the requirement. |
| Repair prompts | Plan repair, AC repair, and Build implementation repair preserve exact lines containing quotes, apostrophes, `.005`, and repeated declarations. |
| Budget/retry | Retained jobs keep full intent and proof through budget and retry paths. |
| Division | Generated 6, 3, and 2 need no literal source provenance. |
| Native types | Python and supported Go tests retain numeric/string distinctions without coercion. |
| CSV regression | All seven reported decimal strings produce no unknown-provenance advisory and are not rewritten or demoted solely for missing literal sources. |
| Dependencies | Foundation importing later-delivered persistence still fails; correct ownership/order resolves the defect. |
| TDD failure | Wrong implementation fails and supplies repair feedback; expectation and intent remain unchanged. |
| Source conflict | Explicit contradictions follow the appropriate repair route without invented rounding/precision. |
| Existing artifacts | Older AC still parse; no deployment-only blocker or verification mutation. |

Start with targeted tests in `test_acceptance.py`, `test_acceptance_oracle.py`,
`test_plan_verify.py`, `test_plan_repair.py`, `test_ac_repair.py`, and relevant authoring/Build
prompt-assembly tests. Complete repository-required checks for implementation scope. This
plan's documentation validation is not evidence that the implementation tests passed.

### Plan naming convention

Use `design/topics/plan_<subject>.md` for plans intended for review or later execution.
Include status, scope, decisions, ordered actions, and completion evidence. The prefix does
not trigger execution or imply completion. Index the plan as required; keep existing topic
memories as current contracts. Do not rename unrelated files in this task.

## Decisions

- `2026-10-26` · Ed approved TDD, authorized Plan-selected examples and expected results,
  removal of decimal provenance noise, and preservation of dependency checks.
- `2026-10-26` · Ed selected AC intent metadata for concise behavior/fixture rationale and
  required verbatim inclusion in repair prompts.
- `2026-10-26` · Ed requested `plan_` naming and deferred implementation to protect the active
  session. This document is the handoff for later execution.

## Questions

- None.

## Actions

- `2026-10-26` · Execute the implementation sequence in a later session. Close when the
  acceptance matrix passes and the separate implementation commit and memories agree.
- `2026-10-26` · After implementation, Ed may validate the next LayersTesting run: decimal
  advisories disappear; dependency failures remain until their Plan correction is made.
  This session does not modify the generated criteria.

## Working Notes

The reported blockers are `foundation-project-tree` and `foundation-persistence-opens` in
`ARCHITECTURE.md`, importing persistence before its database story. Those are legitimate
ordering failures. The separate `csv-format-cents-values` advisory lists `0.00`, `0.05`,
`-0.05`, `-12.50`, `12.50`, `5000.00`, and `1234567.89`. Absence of these literals from source
material is not a test-design defect. This document does not infer the actual CSV source policy.
