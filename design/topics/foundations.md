# MEMORY: foundations

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Description | A criterion must name the application it tests without inventing it. |
| Route | foundations |
| Modules | `rigging_contract.py`, `technology_stack.py`, `rigging_compact.py`, `plan_verify.py`, `manifest_edit.py` |
| Prompts | `BLUEPRINTS_CONTRACT.md`, `MANIFEST_CONTRACT.md`, `plan_create.md` |
| Tests | `tests/test_rigging_contract*.py`, `tests/test_technology_stack*.py`, `tests/test_plan_verify.py` |
| Governs | [plan](../commands/plan.md), [rigging](../commands/rigging.md), [build](../commands/build.md), [run](../commands/run.md) |
| Pending spec | 0 |
| Pending impl | 1 |

## Intent

A criterion must name the application it tests without inventing it. Marina_Luna's criteria split
98 imports of `app` against 77 of `marina_app` and called Flask's `test_client()` 134 times against
a FastAPI stack. The fix is to make the guess unnecessary: the Commander selects a technology, its
Rigging file publishes the package, entry, and fixture, and every criterion writes against a name it
was given.

## Guardrails

- None.

## Details

`2026-10-25` · First-use stack mode excludes a file only when it declares `Type: guidance`,
no foundation kind, and no foundation tier (absent/application). This removes common.md's false
unfounded-stack warning while keeping Bootstrap's explicit interface tier and FastAPI's runtime
foundation rule. The scheduling adapter resolves metadata and passes the guidance set to the pure graph
functions; the file name does not define the exemption. Both full and compact FastAPI
Rigging explain modern TestClient transport selection and lockfile/deprecation verification.


`2026-10-24` · Output DTO identity is validated before the persistence declaration freezes:
one normalized Python class name has one ordered field/type shape. Planning and the emitter
share normalization and the registry. Distinct projections receive operation-derived naming
guidance; identical definitions may intentionally share a class. The mutation-return policy
discussed below remains unchanged. See [plan](../commands/plan.md).

### Rules

`2026-10-22` · Python and Go publish rollback fixtures over the configured, provisioned store; autocommit remains the application default. The lifecycle is governed by [acceptance_criteria](acceptance_criteria.md). Cost when broken: generated clients disagree with shipped fixtures.

`2026-10-19` · Selection uses `Rigging/rigging_types.json`: exactly one shipped language and at most one database, web server and CLI. `Type` controls counts; Foundation/Tier/Category retain ordering and grouping. Language prerequisites are checked against selected Rigging files. Breaking this rule produces incompatible foundations.

`2026-09-20` · **One foundation per exclusive kind.** Exactly one language is required at approval and planning. Web server and CLI remain exclusive;
zero or one database engine may be selected. Two languages are refused.

`2026-09-20` · **Tiers order the chain inside every phase; they never forbid a block.**

| Tier | Name | Builds |
|---|---|---|
| 1 | `language` | tree, environment, test runner |
| 2.1 / 2.2 / 2.3 | `platform` | database, web server, CLI — sub-ordered by what imports what |
| 3 | `branding` | palette, typography, voice |
| 4 | `interface` | shared UI shell |
| 5 | `screen-foundation` | the screen idiom |
| 6 | `application` | every service and screen, ordered by `depends:` only |

Tiers 1–5 publish contracts; tier 6 publishes nothing. Declaring no tier is tier 6. Two tiers may
share a block when both are ready before the block starts and the packer finds savings above
`block_min_savings` (default 1000 tokens). A declared dependency must finish in an earlier block
for newly grouped work (2026-10-26); existing started groups remain intact for resume.
*Broken:* a prohibition where a cost function belongs.

`2026-09-20` · **The Rigging file owns the foundation's shape.** `**Foundation:** <kind>` in the
header (`**Category:**` carries the kind) and a `## Foundation Contract` section: platforms publish
`package` / `entry` / `fixture` (`app_server`, `persistence`, `cli`; `web_client`, `db_session`,
`cli_runner`); languages publish `source_root` / `test_command`.

`2026-09-20` · **The contract survives compaction verbatim** by splicing, never by instruction.

`2026-09-20` · **`unknown-package` judges two facts only:** importing a reserved foundation package
the stack did not select, and importing a published entry callable from another package. Arbitrary
third-party imports are not judged.

`2026-09-20` · **The Commander decides the set.** `TECHNOLOGY_STACK.md` is the record; plan never
adds a kind. The QuarterDeck selector uses language/platform/database radios, defaulting to
`python.md` / `fastapi.md` / `sqlite.md`.

`2026-10-18` · **Language and engine instructions answer mandatory questions.** Python and Go
publish AC execution/measurement and persistence provision; SQLite and PostgreSQL publish
configuration/initialization and shared-contract implementation. `Type` classifies this guidance;
existing Foundation/Tier fields still drive tooling. Questions are level-three headings inside
the Foundation Contract and survive compaction verbatim. The format and required answers live
in `Rigging/stack/README.md`. Cost when broken: prompts omit language-specific execution or
advertise persistence bindings that are not shipped.

`2026-10-18` · Language instructions resolve from `Rigging/languages/<language>/` by their existing basename. Stack discovery and build prompts search bundles alongside stack guidance. Cost when broken: valid language resources are omitted or acceptance evidence is misclassified.

`2026-10-18` · Shipped persistence libraries and templates live in each language bundle. Python and Go implement declared operations on SQLite and PostgreSQL. PostgreSQL DDL adapts integer primary keys to generated identities; schema application does not migrate existing tables. Cost when broken: the selected stack and generated runtime disagree.

`2026-10-20` · The Python `Database` translates every driver failure, including a refused connection, into `PersistenceError`; a `PersistenceError` raised by a driver passes through unchanged. Cost when broken: a raw driver exception escapes the shipped library and no build can repair it, because `persistence/` is copied unchanged.

### Mechanism

`rigging_contract.py` parses `**Foundation:** <kind>` and the `## Foundation Contract` section from
each Rigging file; kinds are open. `technology_stack` refuses multiple selections of exclusive kinds and a missing language. `drydock rigging compact` splices the contract into the compact verbatim. The
selected foundations' contracts ride with `TECHNOLOGY_STACK.md` in the plan prompt, and
`plan verify` refuses `unknown-package` imports. `TIER_ORDER` is the six-tier chain;
`PLATFORM_ORDER` sub-orders tier 2. The QuarterDeck selector uses radios for every max-one type, with None for optional types.

### Spec divergence

- The specification's tier table matches. It does not describe foundation contracts,
  exclusivity, or `unknown-package`.

## Decisions

### Synthesize foundation stories in plan (Slice 5)
`2026-09-20` · `spec:na` · `impl:unimplemented`

`2026-09-20` **Foundation stories are synthesized, not proposed.** Plan derives them from the
  approved `TECHNOLOGY_STACK.md`. Cost when broken: the app foundation lands at story 5 in block 4
  behind two dependencies, as it did in Marina_Luna, while block 1 spends a paid model call writing
  prose.


`src/drydock/plan_foundations.py` (new). Input: the approved `TECHNOLOGY_STACK.md` entries and the
resolved Rigging contracts. Output: one `PlannedStory` per exclusive kind selected, each with:

- `id` derived from the kind (`language-foundation`, `web-foundation`, `persistence-foundation`,
  `cli-foundation`)
- `depends` derived from the tier chain: every `platform` foundation depends on the `language`
  foundation, so the tree and the environment exist before anything is built into them
- `type: foundational`, `scope: target`
- `provides` naming the package and fixture from the contract
- acceptance criteria generated from the contract, not authored: the package imports, the entry
  returns the declared type, the fixture constructs

Plan emits these before the model's stories and the model does not propose them. Every
model-authored story implicitly depends on the foundation of each kind its `stack:` names —
derived in `plan_graph`, not declared.

Verification: unit tests over a synthetic stack with one, two, and zero exclusive kinds;
integration test producing a Manifest whose first phase-1 blocks hold only foundations, the
language foundation ahead of the platform ones; a regression test that
the existing Marina_Luna-shaped plan still schedules.

## Questions

5. `build.band_for()` is a third ordering concept — `BAND_FOUNDATION` / `BAND_DATA` /
   `BAND_FEATURES`, keyed off `implements:` (`ARCHITECTURE.md`, `DATABASE.md`). It predates tiers
   and orders Blueprint documents, not Rigging files. A synthesized tier-1 language foundation
   implements neither, so today it would band as `Features/Screens`. Slice 5 must reconcile the
   two or the build-order validator will contradict the tier chain.

## Actions

- `2026-10-19`: Run PostgreSQL integration for both persistence libraries with `DRYDOCK_TEST_POSTGRES_DSN`. Go and Python SQLite integration pass; PostgreSQL remains unverified (skipped, not passed).

- 2026-10-18: Completed language bundles, Go/Python persistence generation, and multiple engine
  selection. Automatic per-criterion code/persistence tracing remains separate Refit work.

## Working Notes

- `2026-10-24` · Persistence naming/return discussion after FxRates `20261025.014047`:
  operation names and output DTO names are separate identities. One output type name must
  have one consistent ordered field/type definition. A new projection needs a distinct,
  descriptive name, not an arbitrary numeric suffix. Deterministic operation-derived names
  remain proposed as automatic naming policy; the shared registry validating normalized
  Output names/shapes is now implemented as described above.
- `2026-10-24` · Current Python mutation returns (`persistence/db.py:480-524`): create without
  an output DTO returns the inserted key; update/upsert/delete without one return affected
  row counts. With a DTO, update/upsert read back the stored row; delete constructs an output
  from caller-supplied match values, or returns None if nothing matched. It does not retrieve
  the deleted row. `database_contract.py:_derived_dtos` currently synthesizes a key DTO for
  delete. Ed questions the need for write-output DTOs and asks whether writes can return
  None. A simpler explicit mutation-return policy remains under discussion; do not treat
  this question as approval to change runtime contracts. Correct the DTO collision during
  admission regardless of the eventual mutation-return choice.
-
