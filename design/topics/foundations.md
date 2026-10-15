# DESIGN: foundations

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Route | foundations |
| Modules | `rigging_contract.py`, `technology_stack.py`, `rigging_compact.py`, `plan_verify.py`, `manifest_edit.py` |
| Prompts | `BLUEPRINTS_CONTRACT.md`, `MANIFEST_CONTRACT.md`, `plan_create.md` |
| Tests | `tests/test_rigging_contract*.py`, `tests/test_technology_stack*.py`, `tests/test_plan_verify.py` |
| Governs | [plan](../commands/plan.md), [rigging](../commands/rigging.md), [build](../commands/build.md), [run](../commands/run.md) |
| Pending spec | 0 |
| Pending impl | 1 |

## Behavior

### Purpose

A Blueprint criterion must be able to name the application it tests without inventing it. Today
it invents it: Marina_Luna's 47 Blueprints split 98 imports of `app` against 77 of `marina_app`,
and wrote the Flask `create_app().test_client()` 134 times against a FastAPI stack whose Rigging
states the correct idiom in prose. Both are the same defect — the criterion author had no
published contract to write against, so it guessed, and guessed differently each time.

The fix is not detection. It is to make the guess unnecessary: the Commander selects a
technology, the Rigging file for that technology publishes the package name, entry contract, and
test fixture, Drydock synthesizes the foundation story that builds exactly that, and every later
criterion writes against a name it was given.

### Rules

- `2026-09-20` **One foundation per exclusive kind.** A Target has at most one language, one web
  server, one persistence layer, one CLI. Selecting FastAPI and Flask is a refusal, not a merge.
  Cost when broken: two incompatible application shapes in one build tree and every criterion
  coin-flipping between them.
- `2026-09-20` **Language is a foundation and it is built first.** A web server, a database, or a
  CLI is built *into* the tree, the environment, and the test runner the language foundation lays
  down; `fastapi.md` is not standalone and never was. Cost when broken: the platform story writes
  files into a tree that does not exist yet, or invents a second one.
- `2026-09-20` **A tier is a rank inside a phase, never a phase and never a block.** `**Tier:**`
  orders the chain that repeats in every phase. Cost when broken: the word `phase` comes to mean
  two things and neither is checkable.

  | Tier | Name | Builds |
  |---|---|---|
  | 1 | `language` | the tree, the environment, the test runner |
  | 2.1 | `platform` · database | the one database |
  | 2.2 | `platform` · web server | the one web server |
  | 2.3 | `platform` · CLI | the one command-line entry point |
  | 3 | `branding` | the palette, the typography, the voice |
  | 4 | `interface` | the shared UI shell, built with that palette |
  | 5 | `screen-foundation` | the screen idiom, built on that shell |
  | 6 | `application` | every service and every screen — no internal order |

- `2026-09-20` **Tiers 1–5 are the foundation; tier 6 is the application.** A foundation tier
  holds at most one selected Rigging file per kind and publishes a contract. Tier 6 publishes
  nothing and orders nothing: a service and a screen are ranked against each other by `depends:`
  alone. Cost when broken: the ordered chain is read as ordering the whole build, and every
  service acquires a rank it never earned.
- `2026-09-20` **Declaring no tier is tier 6, not a missing answer.** `tier_rank("")` returns the
  application rank. That is how a service stays free to land either side of the interface tier.
  Cost when broken: a file that claims nothing is read as claiming precedence.
- `2026-09-20` **Tier 2's three kinds are independent and sub-ordered by what imports what.**
  2.1 database, 2.2 web server, 2.3 cli: a web server and a CLI import persistence, and
  persistence imports neither. Cost when broken: the sub-order is arbitrary and the next author
  reorders it on taste.
- `2026-09-20` **Ordering the tiers forbids nothing.** Two tiers may legally share a build block.
  What keeps them apart is arithmetic, not a rule: `python.md` and `postgres.md` share no context
  beyond a compacted language file, so merging them saves nothing and only widens the context a
  small model must hold. Screens merge for the opposite reason — five screens at 100 lines of
  specification each against 400 shared lines of Rigging cost about 600 assembled lines together
  and 2,500 apart. Blocks are the optimizer's output and the optimization is mechanical, applied
  after the stories exist. `block_min_savings` is that cost function's floor: below it a merge
  buys nothing and is declined. Cost when broken: a prohibition is written where a cost function
  belongs, and the packer can no longer merge the cases that do pay.
- `2026-09-20` **The palette is settled before the shell, and the shell before any screen.**
  `BRANDING_MAIN.md`, `BRANDING_WEBSITE.md` and `BRANDING_DOCUMENTATION.md` carry tier
  `branding`; the branding files that govern published documents rather than a built UI carry no
  tier. Cost when broken: a screen is built against a look nobody has chosen, then restyled.
- `2026-09-20` **The Rigging file owns the foundation's shape.** Package name, entry contract, and
  fixture are declared in the Rigging file, not chosen per Target and not proposed by a model.
  Cost when broken: 134 criteria calling a method the framework does not have.
- `2026-09-20` **The contract survives compaction verbatim.** `drydock rigging compact` copies the
  contract section; it never passes it to a model to shorten. Cost when broken: the API drifts
  between the builder's copy and the Blueprint author's copy, silently.
- `2026-09-20` **The Commander decides the set.** `TECHNOLOGY_STACK.md` is the decision of record
  and is already Commander-owned and approved. Plan reads it; plan never adds a kind to it.

Settled naming and shape decisions (`2026-09-20`):

- `2026-09-20` Names are `app_server`, `persistence`, `cli` for packages and `web_client`,
  `db_session`, `cli_runner` for fixtures. `app_server` over `app` because `app` is also the
  conventional instance name, which is the collision `04de9bf` was written to repair.
- `2026-09-20` Kind lives in `**Category:**`, which already exists and is already machine-read.
  No new taxonomy is invented.
- `2026-09-20` The contract is carried through compaction by splicing, not by instructing the
  model to preserve it. An instruction is a request; a splice is a guarantee.
- `2026-09-20` A contract has two shapes. A platform foundation publishes `package` / `entry` /
  `fixture`; a language foundation publishes `source_root` / `test_command` and no package. One
  shape must be complete. Requiring the API trio of a language is why `language` sat outside the
  foundation set while being the most exclusive choice a Target makes.
- `2026-09-20` `unknown-package` judges two facts and no others: importing a reserved foundation
  package the stack did not select, and importing a published entry callable from any other
  package. Whether an arbitrary third-party import resolves is a fact about the build environment,
  not the Blueprint — guessing at it is how the retracted analyzers failed good specifications.
- `2026-09-20` Tier 6 is named `application`, not `blueprints`. `Blueprint` already names the
  typed specification documents that are plan's *input*; reusing it for the build work those
  documents describe would give one defined word two meanings.
- `2026-09-20` Tier 5 is `screen-foundation`, not `screen`. It is the idiom every screen is built
  on, not a screen; naming it `screen` invited `ui-flask.bootstrap-client.md` to be read as one.
- `2026-09-20` No block composition is forbidden — not two tiers, not two `stack:` sets. Blocks
  are the output of a mechanical optimization that runs after the stories exist, and a
  prohibition written into it can only stop merges that pay. The chain is stated by the tiers and
  enforced by `depends:`.
- `2026-09-20` `Slice` names a unit of Drydock's own delivery in these notes. `Stage` was already
  taken twice — `drydock uat --stage` and the Stage 1 / Stage 2 planning pipeline — and reading
  "Slice 5" as a sixth tier is exactly the collision the rename prevents.
- `2026-09-20` The QuarterDeck foundation selector is radios, not checkboxes, defaulting to
  `python.md` / `fastapi.md` / `sqlite.md` for a Target with no rows at all. A checkbox list
  invites the second selection `plan verify` then refuses, which is the wrong end of the process
  to learn it.

### Mechanism

`rigging_contract.py` parses `**Foundation:** <kind>` and the `## Foundation Contract` section from
each Rigging file; kinds are open. `technology_stack` refuses a stack selecting two files of one
exclusive kind. `drydock rigging compact` splices the contract into the compact verbatim. The
selected foundations' contracts ride with `TECHNOLOGY_STACK.md` in the plan prompt, and
`plan verify` refuses `unknown-package` imports. `TIER_ORDER` is the six-tier chain;
`PLATFORM_ORDER` sub-orders tier 2. The QuarterDeck selector is one radio group per exclusive
kind.

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

## Open Questions

5. `build.band_for()` is a third ordering concept — `BAND_FOUNDATION` / `BAND_DATA` /
   `BAND_FEATURES`, keyed off `implements:` (`ARCHITECTURE.md`, `DATABASE.md`). It predates tiers
   and orders Blueprint documents, not Rigging files. A synthesized tier-1 language foundation
   implements neither, so today it would band as `Features/Screens`. Slice 5 must reconcile the
   two or the build-order validator will contradict the tier chain.

## Working Notes

-
