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

Read [analyze](analyze.md) first: the work graph, source-of-truth model, and node header format
are defined there.

## Behavior

### Purpose

Turn the imported source specification into Blueprints and a Manifest that Build can execute
without further interpretation. Plan is the last stage where a defect is cheap: every rule below
exists because the same defect cost a paid Build call, or an entire planning run, when it was
caught later instead.

Plan never discards work it has paid for. A run that reaches batch 8 has spent nine LLM calls; a
single bad cell in one artifact is not a reason to write nothing. Keeping the work never means
reporting it as buildable: the exit status says whether Build can execute what was written.

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

`2026-10-14` · **Stage 2 batches start fresh Claude sessions.** Each batch receives the unchanged
original planning context, frozen topology and decisions, the current five-Blueprint ledger, and
the accepted cumulative `DATABASE.md` when present. It receives no earlier batch conversation.
Stage 1 corrective calls still resume the response they repair. Cost when broken: each batch
inherits every prior Blueprint response and thinking tokens, so a five-file request grows into a
hundreds-of-thousands-token session.

`2026-09-22` · **Analyze owns the sole synthesized Compass.** Plan never appends imported source
pages to `COMPASS.md`, even when the Source Roles table calls them author intent. The table still
excludes such Markdown from asset promotion; Analyze already extracted its project-wide direction.
Cost when broken: every Build step receives verbatim README, metadata, or feature-index pages after
the short orientation, wasting prompt capacity and allowing stale detail to overrule it.

`2026-09-17` · **Repair what is unambiguous, record what is not, discard nothing paid for.** The
governing rule; the rest are instances of it. A plan that fails whole over one defect throws away
correct work that cannot be resumed — Stage 2 has no cross-run memory, so a discarded plan is
re-authored from batch 1. Cost when broken: 39 accepted Blueprints and 9 calls, written nowhere.

`2026-09-17` · **Severity tracks whether Build would write wrong code, not distance from the
contract.** A declaration Build cannot read, or a citation that contradicts one, blocks the story
that implements it. An omission — a section absent, a boundary undocumented — is recorded as
`material` and gates nothing. Cost when broken: 22 stories of a well-specified project parked
behind questions none of them needed.

`2026-09-19` · **Only a Feature owns an access pattern; `DATABASE.md` owns what no Feature does.**
A Screen reaches data through a Feature's service and is never an `| Owner |`. A shared pattern —
a log several Features write and several Screens read — names `DATABASE.md`, may be cited by any
Blueprint, and is required of none. An illegal owner is rewritten to `DATABASE.md` deterministically;
no repair pass invents a Blueprint file name. Cost when broken: Marina_Luna spent its whole repair
budget on `FEATURE-ACTIVITY-EVENTS.md`, a file no Blueprint answered to.

`2026-10-13` · **A prose-only reply gets one corrective call before it fails.** If the Stage 1
reply contains no artifact blocks, the model answered instead of planning, and outside-text waiver
has nothing to judge. Plan quotes the reply back and asks once for the artifacts. It tells the
model to resolve each point it raised and record it in `DECISIONS.json`. A second prose reply is
recorded with its text shown. Cost when broken: ReadingList `20261014.014000` stopped at plan over
one questionnaire, 11 seconds into a run.

`2026-09-17` · **A spelling outside the vocabulary is normalized, never guessed.** An `Access` cell
reading `read/write` or `append` is settled to a declared level and the rewrite is reported. A
value with no unambiguous reading is left exactly as written for the contract parser. Cost when
broken: a whole plan lost to one cell.

`2026-09-17` · **`DATABASE.md` is cumulative and append-only.** Seeded before the first batch from
the Rigging template plus every table the source specification declares, then held open for the
run. A batch emits additions only; nothing already declared can be retyped, reordered, or
paraphrased away. Cost when broken: an empty declaration let Build invent a schema with
`create_all()`, which never alters an existing table, and the build deadlocked six columns short.

`2026-09-17` · **A criterion states one expectation.** An accepted-status set admitting `404`
beside any other status is true of an application with no routes; one admitting both a 2xx and a
5xx holds whatever the implementation does. A stub that pins the status it answers with is a real
test, and `404` alone is a negative probe. Cost when broken: 35 criteria, 21% of a plan's gates,
reporting acceptance no build had earned.

`2026-09-19` · **A plan Build cannot execute fails the command.** The last step runs the
`drydock plan verify` check: every criterion can run, and a `DATABASE.md` that declares tables
parses. On failure the artifacts are still written for `drydock plan repair`, but the Manifest is
`state: draft`, `build_sub_state` is `unbuildable`, `PLAN CREATED` records a failure, and the exit
code is `1`. No waiver applies, `--override` and unattended runs included. Cost when broken:
Marina_Luna reported `PLAN CREATED` pass and `approved` over six unrunnable criterion containers
and thirteen unreadable access patterns, with 328 warnings and exit `0`.

`2026-09-17` · **Persistence is decided, never asked.** It is the one part of a plan wholly
decidable from the artifacts: the schema, the operation surface, and each Blueprint's citations
either agree or they do not, and nothing about a disagreement needs a Commander. So persistence
defects — an unreadable declaration included (`2026-09-19`) — raise `DatabaseDefect` into the
artifact repair loop, and — alone among plan defects —
are not forgiven when the repair budget is spent. The run fails and writes nothing rather than
hand Build a storage contract known to be wrong. This is the one deliberate exception to the
governing rule above, and it is narrow: only persistence earns it, because only persistence is
this decidable.

`2026-09-17` · **Four checks define agreement.** A Blueprint the declaration names as an `Owner`
cites the operations it owns (superseded 2026-09-18 — the trigger was `stack:` until then); a
citation may narrow what a pattern grants and never widen it (`read-write` exists because a
repository surface is often genuinely both); every table in `## Schema` is reached by some access
pattern; every operation names a table the schema declares.
Cost when broken: 17 Blueprints citing nothing while the boundary was reported rather than
repaired, and a declaration of four tables whose fourth no story could reach.

`2026-09-19` · **The declaration renders the schema, so every column token must be executable.**
A type cell is `<TYPE> [PK] [NOT NULL] [UNIQUE] [DEFAULT <literal>] [REFERENCES <table>(<column>)]`
over `INTEGER`, `TEXT`, `REAL`, `NUMERIC`, or `VARCHAR(<n>)`; composite constraints are
`- UNIQUE (a, b)` / `- INDEX (a, b)` bullets under the field table. Anything else is refused by
name rather than ignored. Cost when broken: a modifier that parses as nothing is a constraint the
author believes exists and the database does not have, discovered in production rather than in the
plan. `DEFAULT`'s literal set is closed for a second reason — the rendered DDL is executed against
a live connection, so an open cell is a DDL injection path into Drydock's own process. Foreign
keys resolve against the same file and order `CREATE TABLE` by dependency: SQLite tolerates any
order and PostgreSQL does not, so an unordered render is accidentally SQLite-shaped.

`2026-09-19` · **One access pattern declares one repository operation.**
The verb is `get`, `list`, `create`, `update`, or `delete`. Cost when broken: a pattern carries
exactly one `Input:` and one `Output:` table, so a cell naming `settings.get, settings.set`
describes two operations with one pair of DTOs and leaves which fields belong to which undeclared
— the generated persistence layer then cannot build either statement. The verb set is closed
because that layer builds statements rather than carrying SQL text; an open verb set makes it a
SQL generator, which is the thing the design exists to avoid.

`2026-09-18` · **Persistence ownership is read from the declaration, never from `stack:`.**
`DATABASE.md`'s `| Owner |` row carries the owning Blueprint's file name, and that is what decides
who must cite: a Blueprint named there states the operations it owns, a Blueprint named nowhere
writes `- None`. An Owner naming no emitted Blueprint is the declaration's own defect, reported
once against `DATABASE.md`. Cost when broken: `stack:` says which technology a story is built
with, not whether it reaches a repository — in Python every story carries `sqlalchemy.md` and
`alembic.md`, so the gate demanded a citation from the application shell that only runs the
startup migration, and said nothing at all about a Go or C++ Target. The owner check meanwhile
compared a file name to prose the contract never asked for, so Luna's nine service-named owners
surfaced as one unrepairable conflict in the first Blueprint to cite one.

`2026-09-21` · **A pass that clears its files buys budget for what it unmasked.** Validation is
staged, so a defect in one artifact hides defects in others. When a repair pass leaves none of the
files it rewrote cited, the newly surfaced defect gets its own pass budget, capped at three times
the configured repair count. Cost when broken: Luna spent all three passes on `DATABASE.md`; the
third fixed it and exposed a SCREEN route-coverage defect, and the plan failed with no pass left.

`2026-09-18` · **A defect between two files repairs both of them.** The artifact repair loop
re-emits exactly the sources a defect names, so a citation conflict is reported against the
Blueprint and `DATABASE.md` together. Cost when broken: handed only the citing Blueprint, the
model has no legal move when the declaration is the wrong side — Luna spent four of five passes
on one file, returning the same defect each time, and the twelve other defects never got a pass.
`_next_repair_chunk` takes the first kind in first-seen order, so one unrepairable kind starves
every later one.

`2026-09-18` · **A checked grammar is stated where the author reads it, or it cannot be met.**
A `## Database Interface` entry is one bullet on one line — id, em dash, access, `supplies:`,
`returns:` — and a Blueprint that reaches no repository writes `- None — <why>.` Every bullet
under the heading is checked, and the parse failure quotes the offending line and the accepted
form, because the repair prompt carries the defect message and nothing else. Cost when broken:
the grammar lived only in a devlog post while `BLUEPRINTS_CONTRACT.md` described the semantics,
so Luna wrote the prose it was asked for, 21 Blueprints parsed as malformed, and five repair
passes returned the same prose because no message said what to write. A Screen that delegates
persistence had no way to say so at all.

`2026-09-17` · **`Repository operation` is `<table>.<verb>`, checked.** It is the only place the
declaration says which table a pattern reaches, so table coverage is read from its prefix. Cost
when broken: free text there makes the coverage check guess, and a check that guesses about
persistence is worse than none. `stack/persistence.md` binds the other end at build — the
repository's public methods are exactly these operations.

`2026-07-30` · **Plan refuses to start on an undecided analysis.** `BLOCKERS.md` present,
`Quality: Blocked`, or an unanswered required Analyze questionnaire decision stops Plan before any
LLM call; `--override` waives only the questionnaire gate. An absent `TECHNOLOGY_STACK.md` is not a
gate: an undecided stack is resolved from the sources. The one stack gate is Python relational
persistence without its required Rigging selections. Cost when broken: a paid plan authored
against a question the Commander had not yet answered.

`2026-07-30` · **A declared conflict is challenged once before it stops the run.** Missing detail,
a stale derived count, or response length is not a conflict; only mutually exclusive authoritative
requirements that precedence cannot resolve are. A conflict that survives the challenge must cite
its files and clauses. Cost when broken: whole runs stopped on false conflicts.

`2026-07-30` · **`PLAN_COMPASS.md` is human-owned.** Created if absent, never overwritten, never a
destination for plan errors. Cost when broken: Commander guidance replaced by generated text.

`2026-08-01` · **Drydock computes the build order; the model declares only prerequisites.**
`depends:` is model-authored; ordering and the numeric `block:` membership come from
`group_blocks`. Every story belongs to exactly one computed block; `Ungrouped` is a fatal Manifest
defect. Cost when broken: Build runs one story at a time in an order no one checked.

`2026-08-01` · **Plan decides and discloses; it never stalls Build on a choice.** Where sources are
silent the Planning Crew chooses, proceeds, and records the choice in `DECISIONS.json`, never in a
Blueprint. A replan keeps only Commander-directed prior items. Cost when broken: Build stops on a
decision Plan should have made, or a replan erases the Commander's direction.

`2026-08-02` · **A short plan is resumed, never discarded.** Truncated output is scored against the
frozen declaration and the remainder requested in up to `--continue-attempts` (default 3)
continuation passes. Cost when broken: an entire Stage 2 spend repaid because a response ran out
of length.

`2026-08-02` · **A replan keeps built work whose build-relevant content is unchanged.** Plan has
full authority over every Plan-owned output, but a story keeps its state and provenance when its
build-relevant fingerprint matches; `Depends On` refactoring and block renumbering do not dirty it.
`--overwrite` discards all provenance. Cost when broken: a topology-only replan forces a full
rebuild.

`2026-08-22` · **An unattended run answers its own questions.** Under `DRYDOCK_UAT=1` the prompt
carries the Unattended UAT policy: resolve each ambiguity from sources, Compass, and fixture inputs,
record the choice as a material `DECISIONS.json` entry with its `system_choice`, and continue.
Blocking questions are downgraded to `material` with status `recommended`; defects are not
questions and still fail the terminal gate (`2026-09-19`). Cost when broken: a UAT run parked on a
question no one is present to answer.

`2026-09-13` · **Stage 1 defects are repaired before Stage 2 spends.** Coverage and the work graph
are checked against the declaration about to be frozen; a defect costs one repair call. An
unrepaired graph defect is refused there. Cost when broken: final validation refuses the same
declaration after every Stage 2 batch has been paid for.

### Mechanism

0. **Preflight** — clear the error record; refuse on blockers, `Blocked`, unanswered required
   decisions, or missing persistence Rigging; capture questionnaire decisions; create
   `PLAN_COMPASS.md` and `EXCLUDE_FILES` if absent; resolve the stack file set; discard unbuilt
   Plan output. Reusable imported specs with empty acceptance are conformed unless `--no-conform`.
1. **Stage 1** freezes `TOPOLOGY.md` after coverage and graph repair. A declared conflict is
   challenged once. Declared artifacts are fixed before any Blueprint is authored.
2. **Seed** — `_seed_database_blueprint` merges the Rigging template with `blueprint/sources/
   DATABASE.md` and strips the template's `<!-- drydock:example -->` blocks.
3. **Stage 2** authors Blueprints in batches of `_PLAN_BLUEPRINT_BATCH_SIZE`, driven by a ledger of
   Accepted / Current / Deferred / Defective. An accepted artifact is frozen; `DATABASE.md` alone
   stays open and is merged by `merge_schema`. Each Claude batch starts a new session from the
   original prompt prefix plus frozen outputs, ledger, and current database declaration.
4. **Normalize** — `_normalize_unterminated_acceptance_blocks` (an id-less `=== END AC` counts as
   a terminator), then `_normalize_fused_acceptance_boundaries` (which repairs chains, names an
   id-less closer after the open criterion, tokenizes only the proof body when judging a cut, and
   keeps a repair only if the result alternates strictly), then `_normalize_database_access_values`,
   then `_normalize_database_owners` (an `| Owner |` naming no Feature in the plan becomes
   `DATABASE.md`, shared, `2026-09-19`), then `_normalize_database_interfaces` (each owner's `## Database Interface` written from
   `DATABASE.md`; an unknown Owner elsewhere withholds only the `- None` rewrite, `2026-09-19`),
   then `_normalize_standalone_imports` (`2026-09-19`): a criterion reading a name it never binds
   gets `import subprocess`, or the one import statement every sibling criterion in the same
   Blueprint uses for that name; an ambiguous or unbound name is left for step 8,
   then `_normalize_factory_bindings` (`2026-09-20`): a criterion reading the module name it
   imported its factory from — `from app import create_app` then `app.test_client()` — gets
   `app = create_app()` below its last import. Taken only when the name is not a standard library
   module, exactly one name is imported from the module rooted at it, and no attribute read of the
   name matches a submodule of that import; anything else is left for step 8,
   then `_normalize_foundation_imports` (`2026-09-21`): a criterion importing a selected
   foundation's entry callable from any other package — `from marina_app import create_app` —
   imports it from the module the contract's own example uses (`app_server.main` for FastAPI,
   `app_server` for Flask). Runs after factory bindings, which read the invented name. Taken only
   when the statement imports that one name; anything else is left for step 8. The selected
   foundations' `## Foundation Contract` sections ride with `TECHNOLOGY_STACK.md` in the prompt,
   then `_normalize_published_clients` (`2026-09-21`): `create_app().test_client()` becomes the
   contract's `web_client()`, imported from `<package>.testing`; the entry import is replaced when
   nothing else reads the entry. Foundation clients are plain functions in `<package>/testing.py`
   because criteria run as scripts, not under pytest; acceptance fails a criterion whose foundation
   package is absent from the build directory as `foundation not built` without running it.
5. **Grade** — `_weak_acceptance_defects` yields a warning and a `material` decision.
   `_malformed_acceptance_defects` raise `CriteriaDefect` (kind `acceptance-malformed`) and also
   yield a warning and decision. `_database_contract_defects` (every bad pattern, via
   `database_contract_defects`), `_database_table_defects` and `_database_interface_defects`
   (unknown owners read even when the contract does not parse) raise `DatabaseDefect`, in the
   repair-exhausted pass too.
5a. **Repair** — a raised `CriteriaDefect` or `DatabaseDefect` carries `defects` tagged by kind.
   `_next_repair_chunk` groups by kind and takes up to `_PLAN_BLUEPRINT_BATCH_SIZE` sources,
   then cites every defect those sources carry whatever kind found it (`2026-09-19`);
   a pass re-emitting `DATABASE.md` is also given the plan's Blueprint file names, the only legal
   `| Owner |` values (`2026-09-19`);
   `_repair_pass_budget` extends the pass count to reach every chunk; `_artifact_repair_assembly`
   re-emits only the cited artifacts and re-validates. On exhaustion a `CriteriaDefect` is
   re-validated with `enforce_criteria=False` and written for step 8 to fail; a
   `DatabaseDefect` is not, and the run writes the error record and stops.
6. **Integrity** — `_integrity_check` raises only for defects that make the plan unbuildable, such
   as a `DATABASE.md` declaring no tables.
7. **Write** — Blueprints, `DECISIONS.json` reconciled against Commander-directed items, then
   `MANIFEST.md` with computed blocks and preserved provenance, then lineage. Decisions carry the
   story that implements the artifact, so a blocking one parks exactly that story.
8. **Gate** — `plan_verify.verify` over the written Blueprint. Clean: `approved`, exit `0`. Not
   clean: Manifest `draft`, sub-state `unbuildable`, an `ERRORS.md` record (phase `plan verify`,
   `2026-09-19`), `PlanNotBuildable`, `PLAN CREATED` failed.
   `drydock plan repair` restores `approved` only when its own post-repair verification is clean.

### Exit codes

| Code | Condition |
|---|---|
| `0` | Plan written and `plan verify` clean; Manifest `approved`. `plan verify`: no defects. |
| `1` | Plan written but unbuildable (Manifest `draft`, sub-state `unbuildable`); unrepaired `DatabaseDefect`; any operational failure. `plan verify`: defects found. `plan repair`: post-repair verification not clean. |
| `2` | Usage error, or a declared conflict confirmed by its challenge (`PlanDeferredResult`): `ERRORS.md` records it and `PLAN CREATED` is recorded failed with detail `plan deferred`. |

Every run records the `PLAN CREATED` (or `PLAN REPAIRED`) rung in project status, pass or fail.
A failing `plan verify` condemns the standing plan rung without voiding anything.

### Spec divergence

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

6. **Exit `2` for a deferred plan.** AGENTS.md reserves `2` for usage errors and deferred
   (unimplemented) commands; a confirmed source conflict also exits `2`. Keep `2` as "needs the
   Commander", or move it to `1`?

## Working Notes

-
