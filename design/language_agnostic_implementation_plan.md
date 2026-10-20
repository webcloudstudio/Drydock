# Language-Agnostic Target Generation and Library Encapsulation

| Field | Value |
|---|---|
| Date | 2026-10-19 |
| Status | Proposed implementation plan; simplified after review |
| Branch | `main` only |
| Target languages | Python and Go |
| Databases | SQLite and PostgreSQL |

## Objective and scope

Drydock remains Python. It generates a Target in the language selected in
`TECHNOLOGY_STACK.md`. Planning, compaction, build and repair use that selection.

The supported workflow is: select the stack, approve it, plan, then build. This work delivers
that workflow for Python and Go. Changing languages on an already planned or built Target is
outside scope; the operator starts a fresh Target. No language-switch recovery, plan fingerprints,
automatic resets or new compact invalidation system are required.

Reuse the shipped language bundles, persistence generators, libraries and acceptance runners.
Agents write application code that calls the libraries. Keep the existing Python implementation
and correct-call behavior.

Also excluded: Refit methodology, database migrations/versioning, impact analysis, per-criterion
coverage/tracing, and new gates that reject pre-existing Target code.

## 1. Select a valid stack

`TECHNOLOGY_STACK.md` remains the only selection record. Add `**Type:**` to selectable Rigging
files and use one count table, `Rigging/rigging_types.json`:

```json
{
  "language":   {"min": 1, "max": 1},
  "database":   {"min": 0, "max": 1},
  "web-server": {"min": 0, "max": 1},
  "cli":        {"min": 0, "max": 1}
}
```

Types absent from the table have no count limit. Rename `persistence-engine` to `database`.
Existing `Foundation`, `Tier` and `Category` fields retain their ordering and grouping roles.
Adding a count rule requires one table row, not another validator.

One function in `technology_stack.py` validates counts, shipped language availability and
language prerequisites. Save, approval, planning and build use it. Resolve language from the
selected Rigging file, never from a free-text technology name. Python and Go are selectable
because each ships its language file, compact and libraries under `Rigging/languages/`.

Use existing `Prerequisite:`/`Prerequisites:` declarations to reject incompatible selections
such as Go plus FastAPI. Remove incidental Python prerequisites from language-independent
infrastructure guidance. Keep CLI, FastAPI, Flask and Django guidance Python-specific.

QuarterDeck renders each `max: 1` type as a radio group; optional types include None. The table
excludes those files from its dropdown. Autosave may retain an invalid draft and shows the
shared validator's errors. Approval, planning and build require a valid stack; planning and
build also require approval before an LLM call. Changing language or database clears approval.

## 2. Supply the selected language everywhere

The language foundation receives the full language file. Every other build and repair prompt
receives its shipped compact, even when the block's `stack:` omits the language. Include it once
and count it in prompt sizing. Missing required guidance is an ordinary resource error.

Pass the selected language into Target compaction jobs so database, architecture and contract
compacts describe interfaces in that language. Keep the existing compaction lifecycle and
freshness rules. Rigging compaction remains unchanged: `go.md` supplies `go_compact.md`, and
`python.md` supplies `python_compact.md`.

Use existing planning context and language resolution; close omissions rather than add a
parallel context mechanism. Existing Python fallbacks can remain behind validated selection.

## 3. Build native applications with shipped libraries

Complete Go guidance with standard-library CLI and `net/http` application layouts and native
test fixtures. Keep the root application module and nested persistence module consistent.
The language foundation initializes the project before persistence generation; Go's root
`go.mod` must exist before linking the persistence module.

Use the existing generators and shipped Python/Go persistence libraries for SQLite and
PostgreSQL. SQL enforces required columns, nullability, defaults and other schema constraints.
The library returns useful errors; it does not duplicate schema validation or add required-column
metadata.

Keep basic interface checks: declared operations and inputs only, and required keys for keyed
operations. A keyless delete must fail without deleting rows. Verify database failures reach
callers and valid calls retain their existing behavior. Do not redesign the library.

## 4. Preserve native test results

Carry native runner results through the outer acceptance executor: pass, failure, skipped or
not-run, unavailable tool, compilation error and timeout. A skipped Go test is neither a pass
nor an ordinary assertion failure. Timeouts terminate child processes. Reuse existing result
and error handling rather than create another execution framework.

## Verification and delivery

Deliver one tested slice per local commit on `main`; no push. Use fake LLM runners only.

| Area | Required evidence |
|---|---|
| Selection | Zero/two languages and two databases fail; selecting no database succeeds; Go plus FastAPI fails; a new count-table row is enforced |
| QuarterDeck and CLI | Draft errors are visible; invalid approval fails; unapproved/invalid plan and build stop before an LLM call |
| Context | Python and Go guidance reaches build/repair even without a block-level language entry; each Target compaction role receives the language |
| Native applications | Temporary Python and Go CLI/HTTP fixtures work; language initialization precedes persistence generation |
| Persistence | Both language libraries work with SQLite and PostgreSQL; keyless delete changes no rows; database errors reach callers |
| Acceptance | Native outcomes remain distinguishable; timed-out child processes terminate |
| Packaging | Installed-wheel language resources resolve correctly |

Run lint and the regression suite. Report unavailable Go, CGO/C compiler or PostgreSQL DSN
prerequisites as missing verification, never as passes. Do not run UAT or touch its evidence.

Update README, changelog and affected design behavior in `foundations.md`, `run.md`, `plan.md`,
`rigging.md`, `build.md` and `acceptance_criteria.md` with the implementation. Leave the master
specification unchanged unless separately authorized.

The work is complete when the supported select → approve → plan → build workflow passes these
checks for Python and Go, with correct existing Python calls unchanged.
