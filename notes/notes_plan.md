# NOTES: Plan Create

| Field | Value |
|-------|-------|
| Version | 2026-08-01 V12 |
| Route | plan |
| Status | Working notes — not canonical specification |
| Description | Plan team authority, source-to-Blueprint translation, decomposition, Commander-decision preservation, ordering, and downstream build handoff. |
| Pending spec | 38 approved items |
| Pending impl | 1 unimplemented section (Zone B declaration cutover) |
Read `notes_analyze.md` §Shared Model before this file — the work graph, source-of-truth model,
roles, and node header format are authoritative there and not reproduced here.

## Goal

From the Commander-reviewed epic, all immutable source material, and the Team Lead's complete
Analyze handoff, author the governed Blueprint and a validated, ordered, atomically decomposed
Manifest that the Shipyard Crew can build without synchronous access to the Commander.

## Decisions

### Plan Create CLI / Inputs / Outputs
`2026-06-13` · `spec:recommended` · `impl:implemented`

*Built, with the precondition divergence noted in As-Built (ANALYSIS.md + not-Blocked rather than
ROOT-green).*

**CLI:** `drydock plan create <Target>`

**Precondition:** `drydock approve <tgt>` must have been called. Exits with error if ROOT node
does not exist or is not green.

**Inputs:**
- `<Target>/blueprint/` Typed Specification (Intent: guardrails, AC, spec files)
- `<Target>/blueprint/BUILD_CONFIGURATION.md` (Decisions: approved route, PO answers)
- `<Target>/ANALYSIS.md` (approved top-level shape and recommendation)

**Outputs (derived):**
- `<Target>/MANIFEST.md` — the single executable build plan: work graph in header format
  (nodes + `depends-on` edges + state), ROOT seeded green.

`plan create` is the expensive, full agile decomposition, run only against an approved, de-risked
top-level shape. Writes derived artifacts only. `blueprint/` specs + `BUILD_CONFIGURATION.md`
remain the source of truth and must regenerate the graph.

### Decomposition Pipeline
`2026-06-13` · `spec:recommended` · `impl:implemented`

LLM expands the approved route into features → atomic stories → spikes → AC gates, assigning
`depends-on` edges throughout. Edges are inferred proposals; the approved Manifest is the persisted,
ratified home.

Each story maps to **one spec file** (`spec:` field). Hard constraint, not a guideline. This is
the lever that makes the no-cross-stack guardrail enforceable: typed spec filenames
(`FEATURE-*` vs `SCREEN-*`) prevent cross-stack mixing within one story.

The Analyze story list is the Team Lead's proposed map, not an immutable decomposition. The Plan
team reviews it after Commander questionnaires are answered and may retain, split, rename,
replace, or reorder its candidate stories.

### Scrum Guardrails
`2026-07-31` · `spec:recommended` · `impl:implemented`

- **Story too big → split.** A story exceeding the atomicity threshold must be split until atomic.
  Threshold configured in `.env`. Standard scrum guardrail.
- **Stories are atomic.** One spec file; one bounded unit of work.
- **Independent actions remain independent stories.** A screen and its route are separate stories;
  a story does not combine actions merely because they participate in one workflow.
- **Every story has ≥1 AC gate.** A story without a `depends-on` AC node is a defect; `plan create`
  must not emit it.

**As-built:** semantic splitting is owned by the frontier Planning Crew; deterministic validation
enforces exactly one governed specification per story, exactly one owning story per specification,
required acceptance, and valid dependency structure. The Plan prompt requires
independent actions and screen/provider work to remain separate specifications.

### Integrity / Validation Check
`2026-06-13` · `spec:recommended` · `impl:implemented`

Runs in `_integrity_check` after the Manifest is parsed.

- Acyclic: no dependency cycles. **(fatal — built)**
- All `depends-on` values resolve to existing node IDs. **(fatal — built)**
- Every story's `implements` names a real emitted spec file. **(fatal — built)**
- Every story has ≥1 AC. **(fatal — built 2026-06-16; was a warning)**
- Reachable / no orphans. **(warning — built)**
- ~~Story count ≤ ~100~~ — **retired**; see §Story count is not capped.

Fatal findings raise `SpecificationError` (exit 1). Note: spec files are written before the gate
runs, so a fatal failure currently leaves authored specs but no console update — make atomic later.

### Order and Batch
`2026-08-01` · `spec:approved` · `impl:implemented`

**`BUILD_PLAN_COMPASS.md` does not exist and never did.** It was a prototype artifact that reached
these notes but no implementation. `MANUAL_BUILD_ORDER` and PO hand-authored ordering came from the
same prototype and are equally void. There is no separate ordering file: `MANIFEST.md` is the
ordering. All references are removed rather than retired — there is nothing to retire.

**As-built:** Manifest dependencies and order define the runnable frontier. Build deterministically
selects dependency-ready work in Manifest order and splits each group into contiguous work kinds.
Feature/service and screen work never share a build prompt. QuarterDeck cost previews use the same
grouping, so the preview and execution boundaries agree.

**Hard guardrail — no cross-stack batches.** See §Blocks and stack creep for the mechanism.

## Feedback Loop & Injection Stack (2026-06-16)

Companion to notes_analyze.md §Feedback Loop & Injection Stack. Applies the standing-directive
methodology to `plan create` and finalizes its prompt injection stack.

### PLAN_COMPASS.md (standing directive)
`2026-06-16` · `spec:approved` · `impl:implemented`

`plan create` exports a persistent `<target>/PLAN_COMPASS.md`, re-injected into the
plan-create prompt on every run. Same contract as ANALYZE_COMPASS.md: created if absent with
default body `Enter Direction for the Manifest Run`, never overwritten by the command, top-of-file
note that it is used on every `plan create` run, edited/submitted via QuarterDeck, injected near
the top (after the job block). See notes_analyze.md §Standing-Directive Feedback File.

### BUILD_CONFIGURATION.md retired (plan create)
`2026-06-16` · `spec:approved` · `impl:implemented`

Drop `BUILD_CONFIGURATION.md` injection from `planning_session.py` and scrub `prompts/plan_create.md`.
**Supersedes** the BUILD_CONFIGURATION.md inputs in §Plan Create CLI / Inputs / Outputs and the
prototype ordering flags in §Order and Batch. PO direction now comes from PLAN_COMPASS.md and
answered questionnaires.

### Single-directional regenerate — no state merge
`2026-06-16` · `spec:approved` · `impl:implemented`

`plan create` is a one-directional clean regenerate. Do **not** inject the existing `MANIFEST.md`,
and **remove** the module-side `_merge_states`. Every run re-authors the plan fresh; prior block
states are **not** preserved. Rationale (Ed): a new plan is a new plan; LLMs are non-deterministic,
so attempting state/id consistency across re-plans is not worth it. **Supersedes** §As-Built
"state-merge on re-run" and any AC/guardrail language implying preserved states across re-plans.

### Final plan create injection stack
`2026-06-16` · `spec:approved` · `impl:implemented`

1. `prompts/plan_create.md` — prompt body
2. job block (inline) — `TARGET`, `BLUEPRINT_PATH`, `DATE`, `SYSTEM_SHAPE`, `ANALYSIS_QUALITY`
3. `<target>/PLAN_COMPASS.md` — standing directive, if present
4. `<target>/ANALYSIS.md`
5. `<target>/SEA_TRIALS.md`, `SOUNDINGS.md`, `COMPASS.md` (if present)
6. answered `QuarterDeck/questionnaires/spike-*.json`
7. contract files — `MANIFEST_CONTRACT.md`, `BLUEPRINTS_CONTRACT.md`
8. `<target>/blueprint/sources/**` — all readable imported source material

Removed vs current: `BUILD_CONFIGURATION.md` and the existing `MANIFEST.md` (prior plan).

### Analyze Team Lead and Product Owner handoff
`2026-07-31` · `spec:approved` · `impl:implemented`

Analyze is the Team Lead conducting the Product Owner feedback session. It evaluates completeness
of the epic and surfaces Commander expectations as product-level assertions, such as "Commander
wants a web server." Its acceptance criterion is that the Commander is satisfied that intent,
goals, constraints, contradictions, and required decisions have been captured.

Analyze is deliberately "secretly waterfall": it works iteratively with the Commander, but its
handoff must be complete and capable of becoming a buildable Plan. It authors `ANALYSIS.md` and
`COMPASS.md`; required questionnaires are answered before Plan. The story list is an expert
proposal for Plan to review, not a binding work breakdown.

### Analyze decomposition is the default work breakdown
`2026-07-31` · `spec:approved` · `impl:implemented`

The Story List and Story Realization Map in `ANALYSIS.md` are the completed planning decomposition
and Plan's default work breakdown. Plan preserves their proposed story boundaries and mapped source
filenames unless the complete planning context shows that a story is non-atomic, inaccurate,
contradictory, incomplete, or assigns content to the wrong owner. Plan then splits, merges, moves,
replaces, or reorders the affected scope without a deviation-reporting requirement.

Full rewrite remains authoritative over governed content. Plan rewrites every resulting story as a
governed specification using all planning inputs. Source structure is strong evidence for the story
boundary; source content is not authoritative.

### Cross-functional Plan team authority
`2026-07-31` · `spec:approved` · `impl:implemented`

Plan is a room containing the Scrum Master, test-driven development, UI, data, architecture, and
delivery disciplines. The team reviews the whole epic, determines atomic stories, authors governed
specifications, computes dependencies, and orders the work in `MANIFEST.md`.

Plan does not return to the Commander for synchronous clarification. It has full authority to
replace Plan-owned top-level Blueprint files and the Manifest as needed to implement Commander
intent. It may revise Analyze's proposed story list. A source Markdown file already organized as
one candidate story is strong evidence for retaining that file and boundary, but it is not
authority: Plan splits non-atomic files according to normal Agile rules and does not combine
independent actions.

### Immutable sources and Blueprint projection
`2026-07-31` · `spec:approved` · `impl:implemented`

`blueprint/sources/**` is immutable, unconstrained Commander input. Source filenames, nesting,
headings, formatting, and completeness are never validated as governed Blueprint syntax. Analyze
and Plan receive all readable source content; Analyze guides interpretation and decomposition but
does not restrict Plan's visibility to cited files.

Markdown sources are interpreted into governed top-level Blueprint specifications. Non-Markdown
sources are copied to the corresponding path one level above `sources/`, byte for byte. The copy
preserves every existing byte, including line-ending convention and final-newline state. Imported
Markdown is never copied over an authored governed specification.

### Persistent Commander input across replans
`2026-07-31` · `spec:approved` · `impl:implemented`

Commander input is preserved before Plan overwrites any Plan-owned artifact. It includes every
stage Compass, persistent questionnaire answers, and Commander edits or answers in Blueprint
`## Questions` sections. A deterministic scanner appends newly observed Commander information to
persistent replan memory. Replan consumes that accumulated memory so regenerated files cannot erase
human decisions or corrections.

### Plan decisions, severity, and implied approval
`2026-07-31` · `spec:approved` · `impl:implemented`

Plan normally resolves contradictions and incomplete detail by making its best decision, encoding
that decision consistently, and exposing it in the relevant Blueprint's `## Questions` section.
A useful record states the available options, the option selected and why, and asks whether the
Commander wants to redirect and replan. This enables override; it is not a request for permission.

Severity is plain English: `Low`, `Material`, or `Blocking`. Blocking decisions are extremely rare
and mean the team cannot responsibly endorse even its best available interpretation. Low and
Material records do not gate execution. Approval is implied by running the next command; there is
no mandatory review ceremony. The next stage fails only when a material blocker actually prevents
that stage.

### Shipyard Crew build handoff and decision records
`2026-07-31` · `spec:approved` · `impl:implemented`

Build is performed by the outsourced **Shipyard Crew**, which has no synchronous feedback channel
to the Commander. It cannot generate questionnaires or create a new question workflow. When a
story requires an interpretation, the builder proceeds with the best bounded choice and may append
a decision record to that story's owning Blueprint `## Questions` section. The record states what
was done and enables later override; it does not ask for approval or block the completed build.

A decision appears only in the specification that owns it. The same conflict is not duplicated
across related stories. Commander edits to these records become persistent input to a later replan.

### Crew presentation and terminal compatibility
`2026-07-31` · `spec:approved` · `impl:implemented`

Analyze presents the handoff using a stable crew roster: Commander, Team Lead, Planning Crew, and
Shipyard Crew. Descriptions may adapt to the project while role names and authority remain stable.
The presentation is concise, nautical, cute, and fun without obscuring status or responsibility.

CLI output is ASCII-safe on MSYS and other terminals whose Unicode rendering is not controlled.
Decorative emoji may appear in QuarterDeck HTML, where Drydock controls presentation, but terminal
meaning never depends on emoji or other ambiguous-width Unicode glyphs.

## Plan Restructure (2026-08-01)

Session goal: build `plan` the correct way. The driver was three consecutive Marina plan failures.
The diagnostic is recorded below; the restructure is the design response.

### Plan job inventory — deterministic versus model work
`2026-08-01` · `spec:approved` · `impl:implemented`

`plan` performs seventeen distinct jobs. Only four require a model.

**Model work:**
1. Author specification content.
2. Author programmatic acceptance (test-driven).
3. Resolve source and stack conflicts by precedence.
4. Surface questions and build failure modes.

**Deterministic work, to be grouped in one Python module:** phase computation, ordering, block
grouping, Manifest assembly, topological sort, runnable-frontier check, planning-feedback ledger,
typed-header shape, and delimiter verification.

**Moved upstream:** decomposition belongs to Analyze.

The Hard Rules in `plan_create.md` are largely instructions telling a model to behave like a
program — topological consistency, one-to-one mapping, non-empty frontier, delimiter balance,
header shape. They occupy the same context window as the four jobs that require intelligence.
Tightening that prose is not the lever; removing the jobs from the prompt is.

### One node type with story types
`2026-08-01` · `spec:approved` · `impl:implemented`

The Manifest is a list of stories. A `type` field is the only variation.

| Type | Contains | Runs |
|---|---|---|
| `foundational` | Foundation and scaffolding | Early; work depends on it |
| `service` | Everything that does work | Reorderable |
| `feature` | Acceptance criteria plus assembly and intent; no implementation instructions | After its members |

`architecture` was renamed `foundational` on 2026-08-01: it names a role in the graph, not a
document category, and it stopped colliding with source files labelled architecture that describe
services. `ac` is not a node type — see §Programmatic Acceptance is not a node.

`spike` is retired as a node type. Research questions are handled by questionnaires before Plan and
by the owning story's `## Questions` section after. **Supersedes** the `feature`/`story`/`spike`/`ac`
block taxonomy in `MANIFEST_CONTRACT.md`.

### Foundational versus service naming
`2026-08-01` · `spec:approved` · `impl:implemented`

Foundational work is structure and scaffolding. Standing up S3 and proving the connection
is architecture. Everything S3 subsequently does is a service.

Everything that is not architecture is a service, and services are reorderable because they carry
no structural debt. Much of what source material labels architecture is service work: the web
server and the database are foundation; a voice service interpreter is a service wearing an
architecture filename.

Foundation status derives from the dependency graph, not from a filename prefix. The rule is
*build the foundation that is needed*, not *build all foundation first*.

No fourth type. A "foundational service" — voice-to-text, for example — is foundational to whatever
depends on it, which the edges already state more precisely than a label could. A hybrid type would
encode in a name what the graph holds as fact.

### Story attributes
`2026-08-01` · `spec:approved` · `impl:implemented`

A story carries four orthogonal attributes, all deterministic:

| Attribute | Values |
|---|---|
| Type | `foundational`, `service`, `feature` |
| Delivery kind | `capability`, `integration`, `migration`, `test harness` |
| Acceptance contract | Flag; the story has real acceptance to honor |
| Stack | Stack files, each attached in **builder** or **consumer** mode |

Delivery kind is already emitted by Analyze in the Story Realization Map. Observed distribution
across Marina's 105 stories: capability 56, integration 13, migration 14, test harness 2, with the
acceptance-contract flag on 14. `acceptance contract` never appears alone, confirming it is a flag
rather than a kind.

Stack mode is a property of the story's relationship to the stack, not of build order. A builder
story receives the full stack file; a consumer story receives the interface view. This is the
computable form of the compact-substitution rule and can be decided at plan time rather than
tracked through an applied registry at build time.

Type is separate from stack. A `service` may be a backend provider or a screen, so the
no-cross-stack guardrail — which operates on stack — is unaffected.

### Feature is an assembly story
`2026-08-01` · `spec:approved` · `impl:implemented`

Features do not exist as a grouping construct. A feature is a story that depends on its member
stories, carries acceptance criteria, and carries assembly and intent instructions instead of
implementation instructions. Same node, same execution path, different content shape.

When its member stories complete, the feature story runs and is made to pass like any other story.
Integration testing therefore becomes a real build step rather than an implicit hope, covering the
seams between stories where multi-story builds actually break.

A feature story is preferably placed in the same block as its members.

### Blocks replace features as the build grouping
`2026-08-01` · `spec:approved` · `impl:implemented`

A **block** is a set of stories optimized for context: sized to amortize fixed stack-file cost
across one build run, never crossing stacks. Blocks are an optimization output, not a taxonomy.
UI stories group together whether or not they belong to the same Agile feature.

**Supersedes** the plan prompt rule that "context economy comes from `feature` grouping, not from
bundling." Context economy comes from blocks. This is the same construct already specified in
§Order and Batch and §The Compass as the `#`-delimited batch, still LLM-seeded rather than
Python-computed.

### Phase is Commander build sequencing
`2026-08-01` · `spec:approved` · `impl:implemented`

`Phase` is loose terminology for Commander instruction on how to build: *build Feature X, then
Feature Y*. It is not a layer chain. The layer stack repeats inside each phase rather than running
once across the project — foundational / database / service / ui, then service / ui, then
foundational / service / service / ui.

**Supersedes** the `Phase` reading in `plan_create.md` ("foundation and architecture usually precede
downstream features and screens"), which assumes a single pass through the layers and places work as
early as possible.

There are two topologies: the **high-level topology** (phases) and the **actual topology** (the
story dependency graph). The model authors both. Commander ordering direction is input the model
weighs, not an override applied afterward.

**Supersedes** the earlier reading of this section, which framed stage assignment as Commander
direction that Python applies and placement as a latest-valid computation. Ordering is authored, not
solved.

### Acceptance lives in one place per audience
`2026-08-01` · `spec:approved` · `impl:implemented`

- **Programmatic Acceptance** — executable assertions carrying pass/fail state. Lives in
  `MANIFEST.md`. Not human-readable, not human-editable, regenerated wholly by every plan run.
- **User Acceptance** — human-readable intent. Lives in the Blueprint specification.

Today both appear in the Blueprint *and* `ac` blocks appear in the Manifest. That is the
duplication. Splitting by audience gives each one home.

Durability is not a discriminator: the Blueprint does not survive a replan. Only the `## Questions`
section, harvested deterministically beforehand, and notes changes survive.

### Story sizing
`2026-08-01` · `spec:approved` · `impl:implemented`

The correct ceiling is what one build agent can implement and verify in a single pass — its
specification plus stack files in, a working diff and passing assertions out. This is measurable in
tokens before anything runs.

**Supersedes** the story-too-big effort threshold in §Scrum Guardrails and its `.env` setting. A
one-week sprint is an artifact of human capacity and carries no meaning here. The goal is a set of
small building blocks that can be built easily.

Note the symmetry: an over-sized story fails at build for the same reason an over-sized plan fails
at plan. One ceiling, one diagnosis, two altitudes.

### Shape conformance is a checker, not an instruction
`2026-08-01` · `spec:approved` · `impl:implemented`

Absolute guardrails against shape failure come from a deterministic post-checker over a declared
output contract, per `ideas/PROMPT_HARDENING.md` (Warrant / Hull Check / Second Pass). The prompt
currently ends by asking the model to verify its own delimiters and block completeness; that is
free and reliable in code.

Prompt hardening and this restructure are complementary, not alternatives. Staging is what makes a
Second Pass affordable: re-emitting a two-file stage costs almost nothing, while re-emitting a
thirty-file monolith re-sends the entire input. Hardening addresses shape failure only; it does not
address the Marina failure recorded below.

### Plan command workflow — Zones A, B, C, D
`2026-08-01` · `spec:approved` · `impl:implemented`

The spine of this file. `plan` is four zones, and the fix for a prompt holding seventeen jobs is not
to split the model call into phases but to take the thirteen deterministic jobs out of it.

| Zone | Owner | Job |
|---|---|---|
| A | Python | Gates, harvest, discard, resolve stack set, assemble prompt |
| B | Model | Author specifications, acceptance, relationships, topology, phases |
| C | Python | Verify, block, order, assemble `MANIFEST.md` |
| D | Model | Conform pass — guardrail, not load-bearing |

**Zone A as-built (13 steps):** clear the error record; verify `blueprint/`; read `ANALYSIS.md` and
parse source roles; gate on `BLOCKERS.md`; gate on `ANALYSIS_QUALITY: blocked`; gate on unanswered
required questionnaires; read prior `MANIFEST.md` and load prior applied-specs and block states;
harvest `## Questions` before Blueprints are discarded; ensure and read `PLAN_COMPASS.md`; ensure
the exclude file and load exclusions; discard unbuilt Blueprint specs; collect surviving specs and
decide rewrite/reuse/speckit mode; assemble the prompt — sources, contracts, questionnaires,
compass, `TECHNOLOGY_STACK.md`, analysis.

**Zone A gap:** the Rigging stack files themselves (`fastapi.md`, `common.md`) are never opened at
plan time; only `TECHNOLOGY_STACK.md`, which declares *which* stack is used. Resolving the stack
file set is a required new Zone A step — §Story attributes cannot assign builder/consumer mode
without it.

**Zone B as-built (one call, seven numbered steps):** review the planning basis; confirm the
decomposition shape; map analysis stories to authored spec scopes; write authored specification
content; author programmatic acceptance; compute header relationships; build the executable plan.
Steps 6 and 7 leave the prompt. Step 7 — the entire Manifest, including ordering, grouping,
topological consistency, and frontier non-emptiness — is the largest job, is almost entirely
deterministic, and runs *last*, after the model has spent its output budget on content and
acceptance. That is the structural reason a shortfall anywhere kills the Manifest specifically.

**Zone C as-built:** parse delimited blocks; validate output shape; strip unsatisfiable acceptance;
disambiguate Manifest IDs; integrity check; `conform_specs`; normalize Manifest contexts; write
specs, `MANIFEST.md`, QuarterDeck state.

**Zone D already exists.** `conform_specs` is a second model call, fired per non-conformant spec.
The stacked-pipeline architecture is a generalization of something already present, not an
invention. It is unreviewed, may rewrite authored content, and must not be relied on: if it fires
routinely that is a signal about Zone B, not a repair. Review deferred.

Closes open questions 6 and 7.

### Authorship versus verification
`2026-08-01` · `spec:approved` · `impl:implemented`

The division of labour is not semantic-versus-arithmetic. It is **authorship versus verification**.
The model decides everything requiring judgment; Python proves the result is internally consistent
and refuses it otherwise. Same principle as the Hull Check, applied to the graph instead of the
delimiters.

| Job | Owner |
|---|---|
| Relationships — `Depends On`, `Provides`, `Consumes` | Model |
| Actual topology — the story dependency graph | Model |
| High-level topology — phases | Model |
| Programmatic Acceptance | Model |
| Verification of all the above | Python |
| Block grouping | Python |
| Ordering and Manifest serialization | Python |

The model never sorts, never checks its own consistency, and never reasons about a position in an
order it has not computed. It states what each file requires and provides; Python does the rest.
Contradictions become a deterministic error with a precise message instead of a shape failure.

**Two-topology check.** The high-level and actual topologies must agree: a story in phase 2 cannot
depend on a story in phase 3. This is a real, silent, common failure, free to detect and impossible
for a model to reliably self-audit across a hundred stories. It is available only because both
topologies are authored explicitly.

### Content and acceptance are authored together
`2026-08-01` · `spec:approved` · `impl:implemented`

Zone B steps 4 and 5 stay in one prompt. Splitting them breaks the discipline: test-driven means the
assertion is written *with* the behavior, not audited onto it afterward. A separate acceptance call
would re-read every spec just written, re-derive what each route does, and infer intent from output
instead of holding it — paying full context to reconstruct what was free a moment earlier.
Reconstructed intent is where assertions drift from what the spec meant.

**Do not architect around prompt caching.** Caching demonstrably works within a run (Marina logs show
`cache_read_input_tokens: 303696`). Across separate `claude -p` invocations a prefix hit is
plausible — the mechanism keys on exact prefix match — but the breakpoints are not controllable from
outside the CLI, the preamble must match byte-for-byte, and the TTL is short. Every phase must be
correct if every token is cold. A cache hit is an optimization, never a load-bearing assumption;
load-bearing assumptions that cannot be tested are how undiagnosable failures happen.

### Programmatic Acceptance is not a node
`2026-08-01` · `spec:approved` · `impl:implemented`

Programmatic Acceptance is verification the build runs to prove a story is complete. A story is not
"built and failed" — it is built or it is not. Acceptance is therefore a field the story owns, and
passing is part of the story's own state transition, not an independent node with independent state.

`ac` leaves the block taxonomy entirely. Manifest node types are the three story types.

Closes open question 5.

### Blueprint holds the artifact, Manifest holds the schedule
`2026-08-01` · `spec:approved` · `impl:implemented`

The discriminator: **does the fact describe the artifact or the schedule?**

| Fact | Home | Why |
|---|---|---|
| `Provides`, `Consumes`, `Depends On` | Blueprint header | Describe the file — what it offers and requires |
| Story `type` | Manifest | Computed, machine-focused |
| `Phase` | Manifest | Describes when the file is built, not the file |
| Programmatic Acceptance | Manifest | Machine-focused; nobody should hand-edit it |
| User Acceptance, `## Questions` | Blueprint | Human intent |

Blueprint is the human-readable epic rewrite. Manifest is dependency and machine information.
`Phase` never touches disk in the Blueprint: the model emits it in its topology declaration —
transient, part of the response — and Zone C persists it as a story property in `MANIFEST.md`.
Zone D does not consume it.

Whether the model emits a stub Manifest or nothing is immaterial. What matters is that the header
declarations are complete, because Python's output is only as good as those edges.

### Blocks and stack creep
`2026-08-01` · `spec:approved` · `impl:implemented`

Blocks are ephemeral, Manifest-only, regenerated every run, and computed by Python. They are a
bounded bin-pack with every input known at plan time — types, stacks, phases, edges, story size:

- **Hard:** one topology type per block; never cross a phase boundary; never violate the edges
- **Objective:** amortize stack-file cost across the most stories that still fit one build pass

**The mechanism behind the no-cross-stack guardrail is stack creep from Rigging.** Mixing topology
types in one block forces every stack file each type needs into the block, so it pays for context
neither half uses and the build agent reads instructions for work it is not doing. The V1 evidence
that a mixed batch produced materially worse results than two batches now has a cause. This is the
reason story and topology types exist: they are the block-partition key.

### Builder and consumer mode
`2026-08-01` · `spec:approved` · `impl:implemented`

Split ownership:

- **The model authors** the foundational story that stands the stack up. Recognizing that something
  must establish the web server, and making it a node, is judgment and determines story structure.
- **Python assigns** the builder/consumer flag from first use in the computed order. By definition
  the first topology node using a stack is the builder; later ones are consumers. Ordering stays
  build-order-global, as compact substitution already is — not per-block, not phase-based.

If the model assigned the flag it would be asserting a position in an order it has not computed —
the same failure as authoring the Manifest last.

**Disagreement is a defect signal, not a tie to break.** A story requiring a stack to be stood up
carries that edge, so topology puts the founding story first and the first user *is* the builder.
The two answers diverge only when an edge or a foundational story is missing. If the first user of a
stack is not a foundational-type story, Python flags it. Both defects are silent today and both hand
a build agent an interface view of something nobody stood up.

Deriving this in Zone C rather than at build time makes it visible in the QuarterDeck cost preview,
auditable before anything runs, and independent of working-tree state. The cost of being wrong is
asymmetric — consumer-when-it-should-be-builder starves the agent; builder-when-it-should-be-consumer
merely costs tokens — so default to builder on ambiguity.

### Story count is not capped
`2026-08-01` · `spec:approved` · `impl:implemented`

The ~100-story cap (`_STORY_CAP`, fatal) is removed. §Story sizing replaced the effort threshold with
"one build pass," which has no opinion about how many stories a project contains; a correct
300-story project is plausible and would be refused today. Scale is answered with a stronger model,
not a refusal to plan.

A manageable number well under 100 remains the ideal, as guidance rather than a gate.

### As-Built Structure (2026-08-01)
`2026-08-01` · `spec:approved` · `impl:implemented`

The exact shape the restructure landed as. This section is the structural record; the sections
above remain the decision record.

**Module map**

| Module | Owns | Depends on |
|---|---|---|
| `src/drydock/plan_graph.py` | The deterministic core: story model, verification, ordering, stack-mode assignment, block grouping | nothing in Drydock |
| `src/drydock/plan_topology.py` | Declaration parsing, Manifest projection both ways, Manifest serialization | `plan_graph`, `errors` |
| `src/drydock/plan_shape.py` | Declared output contract and its post-checker (Hull Check) | nothing in Drydock |
| `src/drydock/plan_stack.py` | Zone A stack-file resolution and measurement; the single-build-pass ceiling | `technology_stack`, `paths`, `prompt_assembly` |
| `src/drydock/planning_session.py` | Zone A/B/D orchestration; calls the four modules above | all of them |
| `src/drydock/manifest.py` | Story-taxonomy fields on the node model | nothing new |

`plan_graph` deliberately imports nothing from Drydock. It is pure data plus algorithms, so the
thirteen deterministic jobs are testable without a filesystem, a Manifest, or a process.

**Data model — `plan_graph.PlannedStory`**

| Field | Type | Authored by |
|---|---|---|
| `story_id`, `name` | `str` | Model |
| `story_type` | `foundational` \| `service` \| `feature` | Model |
| `phase` | `int` | Model |
| `delivery_kind` | `capability` \| `integration` \| `migration` \| `test harness` | Model |
| `acceptance_contract` | `bool` | Model |
| `implements` | `str` — exactly one specification | Model |
| `depends`, `provides`, `consumes`, `stack` | `tuple[str, ...]` | Model |
| `size_tokens` | `int` | Drydock (`plan_stack`) |
| `stack_mode` | `builder` \| `consumer` | Drydock (`assign_stack_modes`) |
| `block` | `int` | Drydock (`group_blocks`) |

`STORY_TYPES`, `DELIVERY_KINDS`, and `STACK_MODES` are module constants in `plan_graph`;
`manifest.STORY_TYPES` mirrors the first for the parser's benefit.

**Verification — `plan_graph.verify_graph`**

Returns `tuple[GraphDefect, ...]`; each defect carries `code`, `story_id`, `message`, `fatal`.
Codes emitted: `missing-id`, `duplicate-id`, `unknown-type`, `unknown-kind`, `self-edge`,
`unknown-edge`, `cycle`, `no-specification`, `shared-specification`, `empty-frontier`,
`feature-without-members`, `phase-inversion`. `assign_stack_modes` additionally emits
`unfounded-stack` (non-fatal). All are fatal except `unfounded-stack`.

**Pipeline — `plan_graph.compute_plan`**

`verify_graph` → short-circuit on any fatal defect → `order_stories` → `assign_stack_modes` →
`group_blocks`. Returns `PlanComputation(stories, blocks, defects)` with `.fatal` and `.warnings`
partitions. Verification short-circuits because an inconsistent graph is not orderable and a
precise defect beats a derived artifact built on a contradiction.

`order_stories` is a Kahn topological sort over a heap keyed by `(phase, declaration index)`, so
the order is fully deterministic and the declared high-level topology sequences the work while the
declared edges constrain it.

`group_blocks` is a contiguous run-length pack over that order. The partition key is
`(phase, story_type, sorted(stack))`; the soft constraint is `budget_tokens`. Because the input is
already topologically ordered, contiguous grouping cannot violate an edge, so the packer never
needs an edge check.

**Zone C wiring**

`planning_session._apply_computed_schedule(plan)` runs inside `_prepare_manifest_in_memory`,
before `plan.validate()` and before any target artifact is written. It calls
`plan_topology.stories_from_manifest` → `plan_graph.compute_plan` →
`plan_topology.computed_field_updates` → `plan.set_fields`. Fatal defects become plan warnings
that the caller surfaces; `planning_session._integrity_check` independently runs `verify_graph`
and raises `SpecificationError` on any fatal defect, so an inconsistent plan never reaches disk.

**Taxonomy gate.** `stories_from_manifest` participates only for nodes carrying `type:`. A
Manifest written before the restructure has no `type:` field, projects to an empty tuple, and
skips Zone C entirely. That is the whole backward-compatibility mechanism — there is no version
flag and no migration.

**Manifest field contract**

Added to `manifest._CANONICAL_FIELDS["story"]`: `type`, `kind`, `phase`, `block`, `stack_mode`,
`provides`, `consumes`, `acceptance`. `provides` and `consumes` parse comma-only
(`manifest._INTERFACE_FIELDS`) because a route such as `GET /health` contains a space and the
whitespace fallback used for filename lists would split it in two. `ManifestNode` gained
`story_type`, `delivery_kind`, `stack_mode`, `phase`, `block`, and `has_acceptance_contract`
accessors; a legacy node returns `""`/`0`/`False` from all of them.

`feature`, `story`, `spike`, and `ac` remain in `manifest.BLOCK_TYPES` as the *block header*
vocabulary. Story types are a `type:` field, not a block header, so the parser is unchanged and
existing Targets keep loading.

**Zone A**

`plan_stack.resolve_target_stack(target_dir)` runs in `create_plan` immediately after
`ensure_exclude_file`. It reads `technology_stack.stack_files`, resolves each name against
`paths.get_stack_dir()`, and measures both the full file and its `*_compact.md` sibling
(suppressed by a `*_compact.skip.md` marker). Unresolved names become plan warnings; an empty
result is a normal outcome and never gates planning.

`ResolvedStackFile.tokens_for(mode)` is the computable form of the compact-substitution rule:
builder gets the full file, consumer gets the compact sibling when one exists and otherwise falls
back to the full file.

**Story sizing — a target, not a gate**

The ceiling is the existing `prompt_warn_tokens` configuration key — no new key was introduced.
That key already means *the maximum assembled prompt cost of one build step*, which is the same
quantity measured here at plan time; a second key would be the same number under a second name,
defaulting differently and drifting from it. §Story sizing's "one ceiling, one diagnosis, two
altitudes" is therefore literal.

**Nothing refuses, splits away, or downgrades work for exceeding it.** Some specifications are
irreducible. CommonMark's definition is a single ~50,000-token file of normative text, not
instructions, and it cannot be compacted; every story implementing against it is over target by
construction and every one of them builds. Marina exceeds 100,000 tokens. The target exists so the
Commander sees cost before spending it, and the Commander already knows which oversized work will
build.

`plan_stack.story_budget_tokens()` delegates to `build.resolve_warn_tokens()`, which resolves
`prompt_warn_tokens` through `config` (file, then environment) and downgrades to
`build.PROMPT_WARN_TOKENS` on an unusable setting rather than refusing to plan.
`plan_stack.DEFAULT_STORY_BUDGET_TOKENS` is an alias of `build.PROMPT_WARN_TOKENS` so plan-time
and build-time sizing cannot disagree. `plan_graph.DEFAULT_BLOCK_TARGET_TOKENS` mirrors
`config.DEFAULT_PROMPT_WARN_TOKENS`; it is a standalone fallback so `plan_graph` stays free of
Drydock imports.

Measurement runs in `plan_graph.measure_stories`, called from `compute_plan` via a `size_fn`
after stack modes are assigned — a consumer story costs the compact stack view and a builder story
costs the full file, so sizing cannot precede mode assignment.
`planning_session._apply_computed_schedule` supplies the real `size_fn`: the emitted (or on-disk)
specification text plus the resolved Rigging stack files, through `plan_stack.story_pass_tokens`.

**Packing rule.** `group_blocks` ends the current block when the *next* story would push it past
the target **and that story could plausibly start a smaller block**. A story already over target
on its own is packed regardless: splitting around it achieves nothing, and isolating every such
story would destroy the amortization blocks exist for — exactly backwards for a project whose
specifications are large by nature. Only phase, topology type, and stack set are hard partitions.

**Markers.** An over-target story carries `size:` and `budget: over-target` in its Manifest block;
an over-target block raises a non-fatal `over-target-block` warning. Defect codes
`over-target-story` and `over-target-block` are both non-fatal. `ManifestNode.size_tokens` and
`ManifestNode.over_target` read the markers back. A `target_tokens` of `0` disables grouping and
marking entirely.

**Shape conformance**

`plan_shape.OutputContract` declares `required`, `terminal`, `untyped`,
`require_typed_headings`, and `forbid_outside_text`. `check_contract` measures a parsed response
against it and emits `unclosed`, `orphan-end`, `duplicate-open`, `missing-artifact`,
`terminal-artifact`, `empty-artifact`, and `untyped-heading`. `second_pass_instruction` renders
the bounded re-emit — only the failed artifacts — which is what makes a Second Pass affordable.

`planning_session` splits the contract in two. `PLAN_OUTPUT_CONTRACT` is the fatal half
(`required=("MANIFEST.md",)`, typed headings off); `check_plan_shape` runs it in
`_validate_plan_output` once Success Mode is confirmed, before any parse or write.
`PLAN_SHAPE_ADVISORY` is the repairable half; `advisory_plan_shape` reports `untyped-heading` as a
warning because `conform_specs` (Zone D) is the existing repair path for exactly that.

Delimiter pairing is **not** re-checked in the plan path. `_parse_strict_blocks` already owns
pairing together with its documented recoveries (`_repair_missing_leading_delimiter`,
`_is_transposed_artifact_boundary`); running `check_delimiters` over the raw text would contradict
them. `check_delimiters` remains in `plan_shape` as the reusable Hull Check for stages that have
no such recovery.

Artifact *ordering* is likewise not in the fatal contract: the strict parser preserves response
order and `_outside_text_is_waiver_eligible` already requires a terminal `MANIFEST.md`.

**Removed**

- `planning_session._STORY_CAP` and its `story_count` accumulator.
- The `Before responding, verify:` self-audit tail of `plan_create.md`.
- The `Phase` row from the typed Blueprint header template.
- The `feature`-as-batching-unit and `spike`/`ac` block rules from `plan_create.md` and
  `MANIFEST_CONTRACT.md`.

**Prompt versions**

`prompts/plan_create.md` V27, `prompts/MANIFEST_CONTRACT.md` V13.

**Tests**

`tests/test_plan_graph.py` (34), `tests/test_plan_topology.py` (13), `tests/test_plan_shape.py`
(14), `tests/test_plan_stack.py` (17), plus eight Zone A/C integration tests appended to
`tests/test_planning_session.py`.

**Not carried across**

Zone D (`conform_specs`) remains unreviewed — see Open Question 4. The Zone B declaration cutover
is specified in its own section below.

---

### RESUME HERE — Zone B topology declaration cutover
`2026-08-01` · `spec:approved` · `impl:unimplemented`

**Status: designed, half-built, not wired.** Everything below is the outstanding work. Start here.

**What is already done.** `src/drydock/plan_topology.py` contains a complete, tested declaration
parser and Manifest serializer:

- `TOPOLOGY_BLOCK = "TOPOLOGY.md"` — the reserved artifact name. **Nothing writes or reads it
  today.** It is a constant, not a live artifact.
- `parse_topology(text) -> (stories, defects)` — parses `## story <id>` headings plus
  `field: value` lines into `PlannedStory` objects. Non-fatal on unknown `type`/`kind` (falls back
  to `service`/`capability`) and non-integer `phase` (falls back to `1`).
- `parse_topology_strict(text)` — same, raising `SpecificationError` on any defect.
- `render_story_block(story, number)` and `render_manifest(project, stories, blocks)` — serialize
  the *computed* plan. Verified to round-trip through `DrydockManifest.parse`.
- `tests/test_plan_topology.py` covers all of the above.

**What Zone C does instead, today.** The model still emits `MANIFEST.md` directly. Zone C reads it
back through `plan_topology.stories_from_manifest(plan.blocks)`, which participates only for nodes
carrying `type:`, then computes and stamps the schedule fields in place. The declaration path and
the Manifest path therefore both exist; only the Manifest path is live.

**Why it was deferred.** Landing the restructure and an output-format cutover in the same change
would have made a regression impossible to attribute. The restructure is proven with the existing
output format; the cutover is a separable, smaller change.

**The remaining work, in order.**

1. **Prompt.** In `prompts/plan_create.md` step 7, replace "Emit `MANIFEST.md`" with "Emit
   `TOPOLOGY.md`" and give the declaration grammar: one `## story <id>` heading per governed
   specification, then `summary`, `type`, `kind`, `phase`, `implements`, `depends`, `provides`,
   `consumes`, `stack`, `acceptance`, and the passthrough fields
   (`covers`, `accepts`, `context`, `rules`). No `id:` line — the heading carries it. No `block:`,
   no `stack_mode:`, no `state:`, no ordering. The instruction "do not sort, do not group" already
   in the prompt becomes literally enforceable, because a declaration has nowhere to express order.
2. **Output contract.** In `planning_session.PLAN_OUTPUT_CONTRACT`, change
   `required=("MANIFEST.md",)` to `required=(TOPOLOGY_BLOCK,)`. Add `TOPOLOGY.md` to
   `_RESERVED_BLOCKS` so it is never written to `blueprint/`. `PLAN_SHAPE_ADVISORY.untyped`
   already lists it.
3. **Zone C entry.** In `create_plan`, replace the `_validate_plan_output` Manifest parse with:
   `parse_topology(blocks[TOPOLOGY_BLOCK])` → `compute_plan(..., size_fn=...)` →
   `render_manifest(...)` → `DrydockManifest.parse` for validation → the existing
   `_prepare_manifest_in_memory` merge path. `_apply_computed_schedule` collapses into this: it
   exists only to re-derive from a Manifest the model wrote.
4. **Instructions field.** `render_story_block` does not yet emit `instructions:`, which the build
   engine requires. Add it to `_PASSTHROUGH_FIELDS` and to the renderer, and handle the scalar
   block form (`instructions: |`) in `parse_topology` — the current field parser is single-line
   only. **This is the one real gap; the rest is wiring.**
5. **Preamble.** `render_manifest` emits only `# MANIFEST:`, `updated:`, and `blocks:`. It must
   also carry `plan_hash`, `state`, `applied_specs`, and `planning_feedback`, which
   `_prepare_manifest_in_memory` currently sets on a parsed plan. Decide whether the renderer
   takes them or the merge path keeps setting them afterward — the latter is less code.
6. **Reserved-block modes.** `PLAN_CREATE_BLOCKED.txt` and `PLAN_CREATE_ERROR.txt` are unchanged;
   `check_plan_shape`'s deferred-mode branch keys on `set(blocks) <= _RESERVED_BLOCKS`, which keeps
   working once `TOPOLOGY.md` joins that set — verify the `and "MANIFEST.md" not in blocks` guard
   is retargeted.
7. **Legacy path.** Decide whether `plan_reuse.md` and `plan_create_speckit.md` also cut over or
   keep emitting `MANIFEST.md`. They currently share `_validate_plan_output`. Keeping them on the
   Manifest path is fine — `stories_from_manifest` already handles it — but the branch must be
   explicit rather than incidental.

**Why bother.** Two reasons, both from §Authorship versus verification. First, a declaration has
no way to express a position, so the model cannot assert an order it has not computed even by
accident — today the instruction is prose the model may ignore. Second, the declaration is small:
a Second Pass over a malformed declaration re-sends almost nothing, whereas re-emitting a
thirty-file `MANIFEST.md` re-sends the entire plan. That is the staging argument in §Shape
conformance, and it only pays off once the declaration is the artifact.

### Diagnostic — the Marina plan failure was not a capacity limit
`2026-08-01` · `spec:na` · `impl:n/a`

Recorded so the analysis is not repeated.

| Run | Prompt | Output tokens | Text | Files | MANIFEST |
|---|---|---|---|---|---|
| CommonMark 07-27 | 313 KB | 132,692 | 107 KB | 30 | yes |
| CommonMark 07-27 | 314 KB | 134,592 | 106 KB | 31 | yes |
| Marina 08-01 | 373 KB | 69,657 | 65 KB | 13 | no |
| Marina 08-01 | 374 KB | 69,052 | 35 KB | 8 | no |
| Marina 08-01 | 374 KB | 70,077 | 35 KB | 8 | no |

All five runs used `claude-sonnet-5` on the same code path and ended with `stop_reason: end_turn`.
Sonnet emitted 132,692 output tokens and a complete thirty-file plan five days before the failures,
so there is no ceiling near 70,000. Every emitted block was well-formed and correctly closed; the
runs were not truncated.

`drydock plan CommonMark` passes under the current prompt, so `plan_create.md` V26 and the
accumulated guardrails are exonerated. The three Marina runs terminating within 1.5% of each other
indicates a consistent stopping condition rather than model variance. The cause remains
unidentified and Marina-specific.

---

## Acceptance Criteria

1. Does not run without ROOT green (approval precondition enforced; exits with error otherwise).
2. Emits a graph that is atomic-story (one spec per story), fully AC-gated, acyclic, reachable,
   with no story-count ceiling.
3. Story-too-big guardrail applied; oversized stories split before emission.
4. Integrity check passes before `MANIFEST.md` is written; failure surfaces actionable findings.
5. Writes `MANIFEST.md` with ROOT seeded green. No separate ordering file is produced.
6. Deterministic given the same Intent + Decisions.
7. All `depends-on` edges use the single direction (dependent node declares); no `gates` syntax.
8. Multiple `parent` values allowed and parsed correctly.
9. Analyze hands Plan a Commander-reviewed, expectation-complete epic and a proposed story map.
10. Plan receives all readable immutable sources and may revise the proposed decomposition.
11. Markdown becomes governed specifications; non-Markdown assets are projected byte-for-byte.
12. Commander questionnaires and Blueprint question edits survive every replan.
13. Plan and Build decisions remain story-local, visible, non-duplicated, and non-blocking unless
    explicitly classified `Blocking`.
14. Running the next command implies approval when no blocker prevents that stage.

## Guardrails

- **Precondition: ROOT green.** Must not run unless `drydock approve <tgt>` has been called.
- **No cross-stack batches.** Hard rule; applies to both manual and automatic ordering.
- **One spec per story.** `spec:` field required; blank is a defect.
- **Every story has ≥1 AC gate.** A story without a `depends-on` AC node must not be emitted.
- **Integrity check gates emission.** `MANIFEST.md` not written until the graph passes fully.
- **Immutable source provenance.** Never modifies `blueprint/sources/**`.
- **Plan owns governed outputs.** Plan may replace top-level Blueprint specifications and
  `MANIFEST.md` only after persistent Commander input has been harvested.
- **`depends-on` is the only edge syntax.** No `gates`, no other direction. Parser enforces this.

### Compact substitution rule — stack files
`2026-06-22` · `spec:approved` · `impl:implemented`

The first use of a stack file across the full build uses the full file. Every subsequent use
substitutes the compact derivative (`*_compact.md`) if it exists. The rule is build-order-global —
not per-story, not phase-based.

The manifest always stores canonical names (`common.md`, `fastapi.md`). Compact substitution is
derived, never authored.

### Applied registry in the manifest
`2026-06-22` · `spec:approved` · `impl:implemented`

`build` writes one field to the manifest: a per-file applied registry. Each entry records the git
commit ID at the time the file was applied to a build step.

Substitution logic at build time:
- No applied record, or recorded commit differs from HEAD → use **full** file; record commit on
  successful build completion
- Recorded commit matches HEAD → use **compact**
- Uncommitted working tree → **build blocked** (no clean commit ID available)

The manifest is not human-editable (managed via QuarterDeck). No human override of applied flag.

### Applied Blueprint Specification provenance
`2026-06-26` · `spec:approved` · `impl:implemented`

`build` writes `applied_specs` in the Manifest preamble for Blueprint files applied by successful
stories and spikes. This registry is separate from the older compact-substitution `applied:`
field. It covers only Blueprint-resolved `implements:` files and Blueprint-resolved `context:`
files.

Each record stores path, SHA-256 content hash, latest file-level git commit when available,
applying step id, and application timestamp. SHA-256 is authoritative; commit is diagnostic.

Before executing any agent, `build` compares every previously applied spec record against current
Blueprint content. Changed or missing files block build with a stale-spec report. New unapplied
Blueprint files do not block build.

### Uncommitted files guard
`2026-06-22` · `spec:approved` · `impl:implemented`

A build step cannot execute if the working tree contains uncommitted changes. The applied registry
records commit IDs; a dirty tree yields no reliable ID to record or compare.

### Cost estimator forward pass
`2026-06-22` · `spec:approved` · `impl:implemented`

The cost estimator (QuarterDeck compass / `assemble_steps`) cannot read the applied registry — it
is empty before any story has run. It simulates the forward pass independently:

1. Walk stories in manifest order.
2. Maintain a local "seen" set for this calculation pass.
3. First occurrence of a stack file → cost using the full file.
4. Subsequent occurrence → cost using compact sibling (if it exists); fall through to full if not.

The cost estimator groups stories and emits a derived view of the manifest showing compact file
names in downstream stories (e.g., `fastapi_compact.md` instead of `fastapi.md`). The user sees
the substitution and the resulting token cost before anything runs. This makes the token cost
honest and the substitution auditable before build executes.

The build runner performs the same substitution at execution time and writes results to the applied
registry — two passes, same substitution decisions.

## Open Questions

1. **Compact scope** — does the applied registry and compact substitution rule cover only `stack:`
   files, or also `rules:` and `context:` files?
2. **Integrity failure UX** — block `MANIFEST.md` write only, surface as QuarterDeck questions, or
   both? (Lean: block + surface findings; PO decides whether to re-analyze or fix the spec.)
3. **Drift propagation model** — how green/stale propagates when an upstream node changes post-build.
4. **Zone D review** — `conform_specs` is unreviewed and may rewrite authored content. Determine
   whether it stays, and what its firing rate says about Zone B.

*Closed 2026-08-01:* `ac` as node or field (§Programmatic Acceptance is not a node); deterministic
and model phase grouping (§Plan command workflow); TDD phase placement (§Content and acceptance are
authored together). *Dropped:* the Marina stopping condition — it was a property of the plan
boundary being rewritten. *Removed:* the Compass setup verb — `BUILD_PLAN_COMPASS.md` does not
exist.

## Not in scope yet

Editing the canonical specification. Detailed Shipyard Crew execution mechanics beyond the
story-local decision-record contract. Story-too-big splitting is retired by §Story sizing; the
story count cap is retired by §Story count is not capped and removed from the code.

Remaining implementation work: §RESUME HERE — Zone B topology declaration cutover, and the Zone D
review in Open Question 4.

`BUILD_PLAN_COMPASS.md`, `MANUAL_BUILD_ORDER`, and PO hand-authored build ordering are prototype
artifacts that never existed in implementation. They are removed from these notes and from
`notes/archive/archive_plan.md`, which carries a deprecation banner. `CHANGELOG.md` retains its
historical mention as a release record.
