---
id: DDF-009
title: Give refit tickets executable acceptance and reconcile them into the parent spec
area: drydock refit
impact: 8
complexity: 6
rank: 7
generated_at: 2026-07-26T22:46:01-04:00
review_model: claude-opus-5
source: drydock score drydock
---

# FEATURE DDF-009: Give refit tickets executable acceptance and reconcile them into the parent spec

| Field | Value |
|---|---|
| Area | drydock refit |
| Impact | 8/10 |
| Complexity | 6/10 |
| Rank | 7 |
| Project Types | All, Decisive for legacy brownfield modernization and any long-lived product |

## Problem

`refit.md` hard-codes `## Programmatic Acceptance` to `- None.` in every conformed ticket and places the testable statement under `## User Acceptance`, then emits `## ac 1: {AC summary} (assertion: verify {what})` — and `MANIFEST_CONTRACT.md` defines `assertion` as checking behavior 'from evidence or review', which is not executable. Every refit-built change therefore closes on a non-executable gate and is invisible to `drydock score ac`. Separately, a ticket amends a parent spec that is never updated: the parent's sha256 in `applied_specs` stays unchanged, so drift detection reports clean while the parent no longer describes the software that `document generate` and `score release` read the Blueprint to assess.

## Intent

`Drydock_Specification.md` § What is Drydock ('Drydock Blueprints are the authoritative, living definition of a software product') and § Drydock Features ('Complete change-management methodology'); `prompts/BLUEPRINTS_CONTRACT.md` § Acceptance Criteria Files ('Reconciliation: When a positive AC fact has been implemented and verified, move it to the parent spec body and delete the AC entry').

## Evidence

`prompts/refit.md` § Ticket body: '## Programmatic Acceptance\n\n- None.' with the testable statement placed under `## User Acceptance`; § Manifest rows: '## ac 1: {AC summary} (assertion: verify {what})'; `prompts/MANIFEST_CONTRACT.md` ac field table: '`assertion` — checks behavior from evidence or review'. `refit.md` frontmatter `inputs:` is absent entirely, so `BLUEPRINTS_CONTRACT.md` is never injected into the prompt that authors a CHANGE Blueprint file.

## Recommendation

Refit authors real `Programmatic Acceptance` into the ticket using the contract's `### check-id` plus fenced-python shape, with `BLUEPRINTS_CONTRACT.md` injected. On the ticket story closing verified, a reconciliation pass folds the ticket's normative content into the parent spec, bumps the parent's `Version`, records the new sha256 in `applied_specs`, moves positive acceptance into the parent's `Programmatic Acceptance`, leaves negative guardrails in the ticket per the contract's reconciliation rule, and archives the ticket under `blueprint/changes/applied/`. `drydock validate` reports unreconciled applied tickets as spec debt.

## Stories

### Story 1: Author executable acceptance in change tickets

As the Commander, I want a change ticket to carry a runnable proof, so that a refit is verified by `drydock score ac` like any other work.

**Acceptance Criteria**

- `refit.md` declares `inputs:` including `BLUEPRINTS_CONTRACT.md` and the parent spec, and the assembler injects both.
- A conformed ticket's `## Programmatic Acceptance` contains at least one `### check-id` heading with a fenced python block whenever the ticket changes behavior.
- A ticket whose acceptance is `- None.` without an inline reason fails validation.
- A ticket's checks are executed by `drydock score ac` and appear as rows in `SOUNDINGS.md`.

**Tests (RED first)**

- test_refit_prompt_declares_and_receives_blueprints_contract
- test_conformed_ticket_carries_fenced_check
- test_ticket_bare_none_acceptance_fails_validation
- test_ticket_checks_appear_in_soundings

### Story 2: Reconcile a closed ticket into its parent spec

As the Commander, I want a delivered change folded back into the spec it amends, so that the Blueprint keeps describing the software.

**Acceptance Criteria**

- When a ticket story reaches `closed/verified`, the parent spec named in `Amends` gains the ticket's normative body content and its positive acceptance checks.
- The parent spec's `Version` is bumped to the current date with the next increment.
- `applied_specs` records the parent's new sha256 with `applied_by` set to the ticket story id.
- The ticket file moves to `blueprint/changes/applied/` and its negative guardrails remain in it.

**Tests (RED first)**

- test_reconciliation_merges_body_and_positive_acceptance
- test_parent_version_bumped_on_reconciliation
- test_applied_specs_records_new_parent_sha
- test_ticket_archived_with_guardrails_retained

### Story 3: Report unreconciled tickets as spec debt

As the Commander, I want to see when the Blueprint has fallen behind the code, so that drift detection is not falsely clean.

**Acceptance Criteria**

- `drydock validate` lists every ticket whose story is `closed/verified` and which is not archived, naming the parent spec.
- `drydock status <Target>` reports a non-zero unreconciled-ticket count in its orientation output.
- `score release` evidence facts include the unreconciled-ticket count and it is scored under `blueprint_drift`.

**Tests (RED first)**

- test_validate_lists_unreconciled_tickets_with_parents
- test_status_reports_unreconciled_count
- test_release_facts_include_unreconciled_count

### Story 4: Enforce one Blueprint per ticket

As the Commander, I want a ticket that amends more than one Blueprint file rejected, so that reconciliation always has one unambiguous destination.

**Acceptance Criteria**

- A ticket whose `Amends` names more than one file fails refit with a message naming the ticket and the files.
- A ticket whose `Amends` names a nonexistent Blueprint file fails refit.
- A ticket amending a foundational file without an explicit change-ticket declaration still follows the existing foundational-drift rule.

**Tests (RED first)**

- test_multi_amends_ticket_rejected
- test_amends_unknown_file_rejected
- test_foundational_ticket_path_preserved

## Definition of Done

- A refit fixture end to end: ticket authored, story built, proof executed, ticket reconciled, parent version bumped, ticket archived.
- `SOUNDINGS.md` contains rows attributable to refit work.
- An unreconciled ticket is visible in `drydock status` and reduces `blueprint_drift`.
- `refit.md` declares `inputs:` and passes the DDF-007 validator.

## Implementation Plan

1. Rewrite `prompts/refit.md`: add frontmatter `inputs:`, replace the hard-coded `- None.` acceptance block with the contract's check shape, and stop emitting review-only `assertion` ac blocks as the gate.
2. Add a reconciliation routine in `refit.py` invoked on ticket-story verification, merging into the parent spec and updating `applied_specs` via `build_plan.py`.
3. Add the archive directory convention `blueprint/changes/applied/` and update the directory-layout documentation.
4. Add the unreconciled-ticket check to `validate_specification.py` and the counter to `status.py` and the `score release` evidence facts in `score.py`.
5. Add `Amends` cardinality validation in `refit.py`.
6. Add fixtures: single-amends ticket with behavior change, multi-amends ticket, ticket with guardrail-only content, closed-but-unreconciled ticket.

## Specification Impact

§ SAIL Phase 4 — drydock refit (adds reconciliation and archival), § Directory Layout (adds `changes/applied/`), and the Artifact I/O Matrix row for change tickets. Requires the author's approval.

## Risks

- Automated merging into a parent spec can mangle hand-authored prose; the merge must be conservative and reviewable in the QuarterDeck before it is written.
- Bumping the parent `Version` and sha256 changes drift state and may trigger rebuild of stories that were verified.
- Guardrail retention rules will be argued over case by case.
