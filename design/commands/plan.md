# DESIGN: drydock plan

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Route | plan |
| Modules | `planning_session.py`, `plan_verify.py`, `plan_repair.py`, `plan_graph.py`, `plan_topology.py`, `database_contract.py`, `manifest.py`, `lineage.py` |
| Prompts | `plan_create.md`, `plan_create_speckit.md`, `plan_continue.md`, `plan_conform.md`, `plan_reuse.md`, `plan_repair.md`, `plan_artifact_waiver.md`, `BLUEPRINTS_CONTRACT.md`, `MANIFEST_CONTRACT.md` |
| Tests | `tests/test_plan*.py`, `tests/test_planning_session.py`, `tests/test_database_*.py` |
| Topics | [foundations](../topics/foundations.md), [acceptance_criteria](../topics/acceptance_criteria.md) |
| Pending spec | 0 |
| Pending impl | 0 |

## Behavior

### Purpose

Turn imported sources into Blueprints and a Manifest Build can execute without further
interpretation. Plan is the last place a defect is cheap. It never discards paid work, and it never
reports unbuildable work as buildable: the exit status says whether Build can execute what was
written.

### Syntax

```text
drydock plan <Target> [--overwrite] [--no-conform] [--override] [--continue-attempts <n>]
                      [--lineage-model <model>] [--model <model>] [--llm-provider <p>]
drydock plan verify <Target>     deterministic, read-only, no LLM call
drydock plan repair <Target>     one LLM pass making unrunnable criteria runnable
```

Intended workflow: `drydock plan verify <Target> || drydock plan repair <Target>`.
`--lineage-model` is accepted only by `drydock plan <Target>`.

### Rules

`2026-10-19` · Planning requires a valid, Commander-approved TECHNOLOGY_STACK.md before model execution, including with --override. Language comes from selected Rigging guidance. The language initialization story occupies a separate computed block so its project files exist before persistence generation; prompt sizing includes the selected full or compact language file. Breaking this rule plans an undecided or incompatible stack.

**Governing**

`2026-09-17` · **Repair the unambiguous, record the rest, discard nothing paid for.** Stage 2 has no
cross-run memory, so a discarded plan is re-authored from batch 1. *Broken:* 39 accepted
Blueprints and 9 calls written nowhere.

`2026-09-17` · **Severity tracks whether Build would write wrong code.** An unreadable declaration,
or a citation contradicting one, blocks its story; an omission is `material` and gates nothing.
*Broken:* 22 stories parked behind questions none needed.

`2026-09-19` · **A plan Build cannot execute fails the command.** The final `plan verify` must be
clean: every criterion runs and a table-declaring `DATABASE.md` parses. Otherwise artifacts are
written for `plan repair`, the Manifest is `draft` / `unbuildable`, and the exit is `1` — no waiver,
`--override` and unattended included. *Broken:* `PLAN CREATED` pass over unrunnable criteria.

**Inputs and authority**

`2026-07-30` · **Plan refuses an undecided analysis.** `BLOCKERS.md`, `Quality: Blocked`, or an
unanswered required questionnaire stops Plan before any call (`--override` waives only the
questionnaire). The only stack gate is Python relational persistence without its Rigging.

`2026-09-22` · **Analyze owns `COMPASS.md`; the Commander owns `PLAN_COMPASS.md`.** Plan never
appends sources to the Compass and never overwrites `PLAN_COMPASS.md`. *Broken:* stale pages
injected into every build step.

`2026-08-01` · **Plan decides and discloses.** Where sources are silent the crew chooses and records
the choice in `DECISIONS.json`, never in a Blueprint. A replan keeps only Commander-directed items.
Under `DRYDOCK_UAT=1` blocking questions become `material` decisions (`2026-08-22`).

`2026-07-31` · **Questions gate only their story.** Blueprints carry questions under `## Questions`;
an open one blocks its story and transitive dependents only. Answers are written to the owning
artifact, survive renames and replans by decision identity rather than filename, and Manifest
approval is never an answer.

`2026-07-30` · **A declared conflict is challenged once.** Only mutually exclusive authoritative
requirements qualify, and a surviving conflict must cite files and clauses; it defers the plan
(exit `2`).

**Stages**

`2026-09-13` · **Stage 1 defects are repaired before Stage 2 spends.** Coverage and the work graph
are checked against the declaration about to freeze.

`2026-10-13` · **A prose-only Stage 1 reply gets one corrective call.** The reply is quoted back
with a request for artifacts; a second prose reply fails with its text shown.

`2026-10-14` · **Stage 2 batches start fresh sessions.** Each batch gets the original context,
frozen topology and decisions, the five-Blueprint ledger, and the current `DATABASE.md` — no earlier
conversation. *Broken:* a five-file request grows to hundreds of thousands of tokens.

`2026-08-02` · **A short plan is resumed, never discarded.** Truncated output gets up to
`--continue-attempts` (default 3) continuation passes against the frozen declaration.

`2026-09-21` · **A repair pass that clears its files earns budget for what it unmasked**, capped at
three times the configured repair count. `2026-09-18` A defect between two files re-emits both.

**Graph**

`2026-08-01` · **Drydock computes order; the model declares only `depends:`.** Blocks come from
`group_blocks`; every story is in exactly one block; `Ungrouped` is fatal.

`2026-08-02` · **A replan keeps built work whose build-relevant fingerprint is unchanged.**
Renumbering and `Depends On` refactors do not dirty a story; `--overwrite` discards provenance.

**Persistence (`DATABASE.md`)**

`2026-09-17` · **Persistence is decided, never asked, and never forgiven.** A `DatabaseDefect`
goes to artifact repair; if the budget runs out the run fails and writes nothing. This is the one
exception to the governing rule, because only persistence is fully decidable from the artifacts.

`2026-09-17` · **`DATABASE.md` is cumulative and append-only**, seeded from the Rigging template plus
every source-declared table. Batches add; nothing is retyped or removed.

`2026-09-19` · **Only a Feature owns an access pattern; `DATABASE.md` owns shared ones.** A Screen is
never an `| Owner |`; an illegal owner is rewritten to `DATABASE.md` deterministically. Ownership is
read from the declaration, never from `stack:` (`2026-09-18`).

`2026-09-17` · **Four checks define agreement.** Owners cite what they own; a citation may narrow a
grant, never widen it; every table is reached by some pattern; every operation names a declared
table.

`2026-09-19` · **One pattern is one `<table>.<verb>` operation**, verb ∈ `get`, `list`, `create`,
`update`, `delete`. A Blueprint's `## Database Interface` entry is one checked line
(`id — access, supplies:, returns:`) or `- None — <why>.`; a parse failure quotes the line and the
accepted form.

`2026-09-19` · **Every column token is executable.** Types are `INTEGER`, `TEXT`, `REAL`, `NUMERIC`,
`VARCHAR(n)` with `PK`, `NOT NULL`, `UNIQUE`, `DEFAULT <literal>`, `REFERENCES t(c)`; composites are
`- UNIQUE (a, b)` / `- INDEX (a, b)`. Anything else is refused by name; the closed `DEFAULT` set
also prevents DDL injection. Foreign keys order `CREATE TABLE`.

`2026-09-17` · **A spelling outside the vocabulary is normalized, never guessed**, and the rewrite
is reported.

**Criteria**

`2026-09-17` · **A criterion states one expectation.** A status set admitting `404` beside others,
or both a 2xx and a 5xx, is refused. See [acceptance_criteria](../topics/acceptance_criteria.md).

`2026-10-18` · Python and Go support DATABASE.md persistence. Stack validation requires exactly one language and permits at most one database engine; other exclusive foundations retain their constraints. Cost when broken: the selected stack and generated runtime disagree.

### Mechanism

0. **Preflight** — refuse on blockers or missing persistence Rigging; capture questionnaire
   decisions; create `PLAN_COMPASS.md` and `EXCLUDE_FILES`; conform reusable imported specs with
   empty acceptance unless `--no-conform`.
1. **Stage 1** — freeze `TOPOLOGY.md` after coverage and graph repair.
2. **Seed** `DATABASE.md` from Rigging plus `sources/DATABASE.md`.
3. **Stage 2** — author Blueprints in batches of 5 against an Accepted / Current / Deferred /
   Defective ledger; accepted artifacts freeze, `DATABASE.md` merges.
4. **Normalize** — deterministic fixes in order: unterminated and fused AC blocks, access values,
   owners, database interfaces, standalone imports, factory bindings, foundation imports,
   published clients (see [foundations](../topics/foundations.md)). Each is taken only when
   unambiguous; anything else is left for step 8.
5. **Grade and repair** — weak criteria → warning and `material` decision; malformed criteria and
   database defects → artifact repair by defect kind.
6. **Integrity** — refuse only what makes the plan unbuildable.
7. **Write** — Blueprints, `DECISIONS.json`, `MANIFEST.md` with computed blocks and preserved
   provenance, lineage.
8. **Gate** — `plan verify`; clean → `approved`, exit `0`; else `draft`/`unbuildable`, exit `1`.

### Exit codes

| Code | Condition |
|---|---|
| `0` | Plan written and `plan verify` clean; Manifest `approved`. `plan verify`: no defects. |
| `1` | Plan written but unbuildable (Manifest `draft`, sub-state `unbuildable`); unrepaired `DatabaseDefect`; any operational failure. `plan verify`: defects found. `plan repair`: post-repair verification not clean. |
| `2` | Usage error, or a declared conflict confirmed by its challenge (`PlanDeferredResult`): `ERRORS.md` records it and `PLAN CREATED` is recorded failed with detail `plan deferred`. |

Every run records the `PLAN CREATED` (or `PLAN REPAIRED`) rung in project status, pass or fail.
A failing `plan verify` condemns the standing plan rung without voiding anything.

### Spec divergence

- The approved-stack precondition and shared type-count policy are implemented here; the master specification is unchanged.

- The specification's syntax omits `verify`, `repair`, `--override`, `--continue-attempts`, and
  `--lineage-model`.
- The specification lists only Blueprints and `MANIFEST.md` as outputs. Plan also writes
  `TOPOLOGY.md`, `DECISIONS.json`, `PLAN_COMPASS.md` and `EXCLUDE_FILES` (when absent), source
  lineage, and `ERRORS.md` on failure.
- The specification does not state that an unbuildable plan exits `1` with its artifacts written,
  or that a confirmed conflict exits `2`.

## Decisions

-

## Open Questions

1. **Compact scope** — does the applied registry and compact substitution rule cover only `stack:`
   files, or also `rules:` and `context:` files?
2. **Integrity failure UX** — block `MANIFEST.md` write only, surface as QuarterDeck questions, or
   both? (Lean: block + surface findings; PO decides whether to re-analyze or fix the spec.)
3. **Drift propagation model** — how green/stale propagates when an upstream node changes post-build.
4. **Zone D review** — dependent and deferred. `conform_specs` is unreviewed and may rewrite
   authored content. Determine whether it stays, and what its firing rate says about Zone B, only
   after its dependency and actual behavior are understood. No implementation decision is made.
5. **Contract-sensitive downstream invalidation** — determine whether a dependent story becomes
   dirty from a change to the upstream surface it actually consumes. Do not propagate dirty state
   merely because any upstream specification byte or story changed. The likely discriminator is a
   changed consumed contract or compact projection. Until this is designed, replanning resets the
   changed story only and leaves previously verified dependents unchanged.

*Closed 2026-08-01:* `ac` as node or field (§Programmatic Acceptance is not a node); deterministic
and model phase grouping (§Plan command workflow); TDD phase placement (§Content and acceptance are
authored together). *Dropped:* the Marina stopping condition — it was a property of the plan
boundary being rewritten. *Removed:* the Compass setup verb — `BUILD_PLAN_COMPASS.md` does not
exist.


## Open Actions

-

## Working Notes

-
