# DOCUMENTATION NOTES

Specification-approved sections awaiting application to the canonical specification.

## notes_analyze.md

#### TASK FIX-1: Quality gate is blockers-only
`2026-06-15` · `spec:approved` · `impl:implemented`

`prompts/analyze.md` contradicts itself: the Quality table defines `Ready` as "no open
questions" (line ~60) but then states "Questions do not block Quality reaching `Ready`"
(line ~67). The canonical model (this file, "Blockers vs Questions"; AC #7) is **blockers-only
gating**.

Fix — reword the Quality section to:
- `Blocked` = one or more blockers → pipeline halts.
- `Questions` = no blockers, open questions remain → `plan create` may proceed.
- `Ready` = no blockers, no open questions → `plan create` may proceed.
- Replace the confusing sentence with: *"Only blockers halt the pipeline. Both `Questions`
  and `Ready` permit `plan create`; open questions distinguish the two but do not gate."*

No code change; `analyze.py` already treats the signal as display-only.

#### TASK FIX-2: spike-stack.json example must be valid JSON
`2026-06-15` · `spec:approved` · `impl:implemented`

`prompts/analyze.md:254` shows `"options": {detected framework options …}` — invalid JSON.
`analyze.py:_parse_output` runs `json.loads` on every `spike-*.json` block and **hard-fails the
entire analyze** on any invalid block. The template the model is shown is itself unparseable.

Fix — make the in-block example valid JSON with a concrete placeholder array, e.g.
`"options": ["flask", "django", "fastapi", "other"]`, and move the "fill from the injected
catalog for the detected type" instruction into prose **outside** the JSON. See FIX-5 for the
options contract.

#### TASK FIX-3: SOUNDINGS precedence — stated AC, then synthesize
`2026-06-15` · `spec:approved` · `impl:implemented`

Prompt is internally inconsistent: line ~186 / ~361 say SOUNDINGS rows come from "actual
`## Acceptance Criteria` bullets in spec files," but analyze reads only arbitrary imported
sources, which usually have no such section, and this file's design says the LLM **synthesizes**
milestones from project shape.

Fix — replace with an explicit precedence rule: *"Derive acceptance milestones from the imported
sources and the story list. Where a source states explicit acceptance criteria, use them;
otherwise synthesize one milestone per feature area / screen / persistence area from the project
shape."* Drop the "in spec files" phrasing — there are no typed spec files at analyze time.

#### TASK FIX-4: "Do not invent gaps" vs the completeness checklist
`2026-06-15` · `spec:approved` · `impl:implemented`

`prompts/analyze.md:365` ("Do not invent gaps") reads as if it conflicts with the checklist,
which is *designed* to turn each absent decision into a question.

Fix — clarify the rule: *"Do not fabricate requirements or problems the sources do not imply. A
genuinely absent decision (e.g. no auth model stated) is a real gap — surface it as a question,
not as an invented requirement."*

#### TASK FIX-5: spike-stack offers catalog filenames; analyze never reads stack files
`2026-06-15` · `spec:approved` · `impl:implemented`

**Clarified scope (Ed, 2026-06-15):** analyze does **not** read the individual `Rigging/stack/*.md`
files — ever. It offers their **filenames** as the `options` in `spike-stack.json` for the PO to
pick in the questionnaire. If the imported source already names the stack, the prompt picks it;
only when the source is silent does it fall to the questionnaire. The stack files must exist —
the system relies on the list; with no list the build degrades to "create a web server" with no
specifics (works, but non-reproducible run-to-run). The injected `Rigging/stack/README.md`
catalog already enumerates the filenames and their `STACK.yaml` mappings — that is the source of
the options list.

Fix — reword prompt Inputs + Hard Rules so:
- `spike-stack.json` `options` = stack catalog filenames/slugs from the injected README catalog,
  filtered to the detected project type, plus `other`.
- State explicitly that analyze never opens the per-technology stack files; it only lists them.
- If the source names a stack, pre-select it; else leave it as an open questionnaire item.

No `analyze.py` change required — the README catalog is already injected (`analyze.py:151`).

**TBD (future session):** a `drydock` mechanism to generate stack files from a one-line
"best-practices for technology X" prompt. Out of scope here; the files exist today.

#### TASK FIX-6: Checklist & project-type detection read sources only
`2026-06-15` · `spec:approved` · `impl:implemented`

**Resolved fork (Ed, 2026-06-15): source-only.** Do **not** inject `METADATA.md`. Every typed file
other than COMPASS (`ARCHITECTURE.md`, `DATABASE.md`, `FEATURE-*.md`, `SCREEN-*.md`, `UI*.md`) is an
**output** of a later step and is never an input to analyze. The current prompt wrongly tells the
model to inspect those files (checklist lines ~76–83; project-type table lines ~106–117), but they
are not injected — forcing hallucination, over-questioning, or misclassification.

Fix — reframe both:
- **Completeness checklist:** each item asks whether the fact is *stated in the imported sources
  (or prior `BUILD_CONFIGURATION.md`)* — e.g. "persistence model described in the sources,"
  "stack named in the sources," "success criteria stated" — not "DATABASE.md present" /
  "METADATA.md `stack:` field."
- **Project-type detection:** detect `web/api/cli/library/pipeline/event-driven` from the
  *content and structure of the imported sources* (described screens, routes, commands, datasets,
  topics), not from the presence of `SCREEN-*.md` / `AGENTS.md` filenames.

#### TASK BUG-7: blueprint/ must hold only sources after analyze
`2026-06-15` · `spec:approved` · `impl:implemented`

**Observed defect (Ed):** after `import` + `analyze`, `blueprint/` contains the full typed-spec
scaffold (`ARCHITECTURE.md`, `DATABASE.md`, `FEATURE-Example.md`, `HOMEPAGE.md`, `IDEAS.md`,
`SCREEN-Example.md`, `UI-Component-Example.md`, `UI.md`). It should contain **only** the imported
source(s) under `blueprint/sources/`. Typed spec files are `plan create` outputs.

**Root cause (verified):** not analyze — analyze never writes to `blueprint/`. `drydock import`
seeds the scaffold: `import_markdown.py:69,74` calls `init_specification(..., update=True)`, which
copies `Rigging/spec_template/*` (ARCHITECTURE.md, DATABASE.md, FEATURE-Example.md, …, plus
COMPASS.md, METADATA.md, README.md) into `blueprint/`.

Fix — stop import from materializing typed-spec template files into `blueprint/`. After import,
`blueprint/` = `sources/` only. Confirm nothing downstream (`plan create`,
`validate_specification`, `plan_compass`) depends on the pre-seeded stubs; if it does, move that
dependency to `plan create` generation.

**Resolved placement (Ed, 2026-06-15):**
- `METADATA.md` lives at the **target root** (`targets/<TGT>/METADATA.md`) — not in `blueprint/`.
  It already exists there (lifecycle state via `set_build_state`); drop it from the blueprint
  scaffold seeding. Use the target-root file.
- `COMPASS.md` is analyze's conditional **target-root** output; not seeded into `blueprint/`.
- Net: `Rigging/spec_template/*` should not be copied into `blueprint/` at import at all.

#### TASK FIX-8: analyze prints the filenames it created
`2026-06-15` · `spec:approved` · `impl:implemented`

`drydock analyze` must report the artifacts it wrote (ANALYSIS.md, SEA_TRIALS.md, SOUNDINGS.md,
COMPASS.md if written, each `spike-*.json`, commanders_chair.html if written). The CLI handler has
the paths on `AnalyzeResult`; surface them as a printed list on success.

---

#### TASK FIX-9: Structure analyze as ordered steps with per-step artifact contracts
`2026-06-15` · `spec:approved` · `impl:implemented`

**Direction (Ed, 2026-06-15):** analyze stays **one agent** — no multi-call orchestration. Author
its prompt as a sequential pipeline where each step states what it **consumes** and what artifact
it **emits**, in dependency order. This is normal prompt authoring, not a redesign. Only two
agents matter in this pipeline — `analyze` and `plan create` — and each is one well-structured
sequential agent.

`prompts/analyze.md` already has `## Tasks — Execute in this order` (steps 1–6) and
`## Output Format`. What is missing is the per-step input→output contract. Order:

```
sources → roles review → blockers/questions → story list
        → SOUNDINGS (from stories) → SEA_TRIALS (from stories + COMPASS)
        → quality signal (from blockers/questions) → questionnaires → COMPASS (conditional)
```

Fix — give each Tasks step an explicit "consumes / emits" line, and sequence so each artifact is
derived from the prior step's output (e.g. SOUNDINGS and SEA_TRIALS derive from the story list;
quality derives from the blocker/question counts) rather than independently re-derived. No code
change; this is prompt structure. Compatible with all FIX-1…FIX-8.

#### TASK FIX-10: BLOCKERS.md writer must reject empty/placeholder content
`2026-06-16` · `spec:approved` · `impl:implemented`

**Implemented 2026-06-16 (structural / fail-closed):** `analyze._validate_blockers` accepts the
BLOCKERS block only when it carries ≥1 `## ` blocker entry; empty, whitespace, placeholder
(`(omitted…)`), or title-only blocks return `None`, so the writer does not create the file and
removes any stale one (`analyze.py` write block). Prompt nudged (`prompts/analyze.md`) as
defense-in-depth. Tests: `TestValidateBlockers`, `test_placeholder_blockers_block_returns_none`,
`test_titleonly_blockers_block_returns_none`, `test_placeholder_blockers_block_not_written`.

**Contract:** the *existence* of `<Target>/BLOCKERS.md` is the sole flag meaning "blocked"; it
halts `plan create` (`planning_session.py:343`). The file must therefore never exist with empty or
placeholder content. Moved here from `notes_plan.md` — `analyze` is the writer and sole owner of
this artifact; `plan create` only reads it.

**Observed defect (2026-06-16):** the analyze LLM emitted a `BLOCKERS.md` block whose body was the
placeholder `(omitted — no blockers)` instead of omitting the block. The writer trusted it —
`analyze.py:235` `blocks.get("BLOCKERS.md") or None` filters only the empty string, not placeholder
text — so a 26-byte junk file was written and falsely tripped the `plan create` precondition.

**Fix — make the deterministic writer the enforcement point, not the prompt.** In
`analyze.py:_parse_output` / the write block at `:406-413`, treat any non-genuine blocker content
as "no blockers": when the parsed BLOCKERS body is empty, a known placeholder, or lacks a
recognizable blocker structure, do not write — and `unlink` any existing file (the resolution path
already at `:412`). The prompt instruction ("emit the block only when blockers exist") stays as
advisory defense-in-depth, but correctness must not depend on model compliance.

**Open (decide before implementing):** structural enforcement — require ≥1 recognizable blocker
entry (e.g. a `## ` heading) and unlink otherwise (fail closed) — vs known-placeholder filtering
(blocklist empty / `(omitted…)` / template boilerplate). Lean: **structural / fail-closed**, so any
non-conforming model output degrades to "no blockers" rather than a false halt. Add a unit test with
a placeholder-body block asserting no file is written (and an existing file is removed).

---

#### Standing-Directive Feedback File (methodology)
`2026-06-16` · `spec:approved` · `impl:implemented`

Each generative step exports a persistent feedback file re-injected into its prompt on every run:

- created by the command if absent, default body `Enter Direction for the <Step> Run`;
- **never overwritten** by the command once it exists — the human owns it;
- top-of-file note states the instructions are used every time `<command>` runs;
- edited and submitted by the user through QuarterDeck (saved back to the same file);
- injected as a standing directive near the **top** of the prompt (after the job block, before
  prior-answer / source context) — highest-priority human steering reads first.

`analyze` → `ANALYZE_COMPASS.md`; `plan create` → `PLAN_COMPASS.md` (notes_plan.md).
Supersedes `BUILD_CONFIGURATION.md` as the free-text PO-direction channel.

#### ANALYZE_COMPASS.md
`2026-06-16` · `spec:approved` · `impl:implemented`

- Location: `<target>/ANALYZE_COMPASS.md` (target root).
- QuarterDeck: shown directly under ANALYSIS in the nav; editable; submit saves to the file.
- Injected at analyze stack position 3 (after the job block, before `BLOCKERS.md`).

#### BUILD_CONFIGURATION.md retired
`2026-06-16` · `spec:approved` · `impl:implemented`

Dropped — not in `docs/Drydock_Specification.md`, originated as an offhand comment, has no defined
format, writer, or value. Remove its injection from `analyze.py` and `planning_session.py`, and
scrub references in `prompts/analyze.md`, `prompts/plan_create.md`, `prompts/BLUEPRINTS_CONTRACT.md`.
Its two former roles are now carried by the feedback files (free-text direction) and answered
`spike-*.json` (structured decisions). **Supersedes** the "Decisions = BUILD_CONFIGURATION.md"
entry in §Source of Truth and the BUILD_CONFIGURATION.md references in §Process Flow.

#### Rigging catalog = filename list, not README content
`2026-06-16` · `spec:approved` · `impl:implemented`

Today analyze injects the full text of `Rigging/stack/README.md` (an LLM-authored file). Replace
with a **filename list only** — names, no content, `README.md` excluded. The names are the
selectable options for `spike-stack.json`. Refines FIX-5: the option source is the directory
listing, not the README catalog.

**Resolved (Ed, 2026-06-16):** the list includes **both** `Rigging/BRA*.md` (branding) and
`Rigging/stack/*.md`, excluding `README.md`. Implemented in `analyze._rigging_catalog_names`.

#### Final analyze injection stack
`2026-06-16` · `spec:approved` · `impl:implemented`

1. `prompts/analyze.md` — prompt body
2. job block (inline) — `BLUEPRINT_PATH`, `DATE`, `COMPASS_EXISTS`
3. `<target>/ANALYZE_COMPASS.md` — standing directive, if present
4. `<target>/BLOCKERS.md` — prior blocker answers, if present
5. Rigging catalog filename list — `BRA*.md` + `stack/*.md`, no `README.md`, names only
6. `<target>/blueprint/sources/*.md` — imported sources

COMPASS is **not** injected into analyze (only the `COMPASS_EXISTS` flag); analyze generates
COMPASS. The feedback file is anchored top-of-stack rather than "after the compass."

#### ANALYSIS.md Tab-Structure Redesign
`2026-06-16` · `spec:approved` · `impl:implemented`

QuarterDeck tabs from `##` headings in ANALYSIS.md. Four decisions agreed in session:

1. **Remove `## Analysis Summary` heading.** The content before the first `##` heading renders as
   the implicit first tab (Overview). Adding `## Analysis Summary` creates a duplicate Overview/Summary
   split. Dropping the heading merges them into one Overview tab.

2. **Drop `## Blockers` section from ANALYSIS.md.** `BLOCKERS.md` is the artifact; its existence is
   the pipeline signal. Blockers must not also appear as a tab inside ANALYSIS.md.

3. **`## Open Questions` references spike files.** Each open-question item cites which
   `spike-*.json` questionnaire covers it (e.g. "see `spike-stack.json`"), so the tab makes the
   spike connection visible to the PO.

4. **Final ANALYSIS.md tab structure:** `Overview / Story List / Open Questions / Notes` — driven
entirely by `##` headings. All changes are prompt-only edits to `prompts/analyze.md`.

#### Analyze Documentation Contract Alignment
`2026-07-18` · `spec:approved` · `impl:na`

The canonical `drydock analyze` section records the actual command contract: CLI syntax including
the LLM options, exit codes, re-run inputs, and material target-side effects. It does not identify
`SOUNDINGS.md` as an Analyze artifact. The input inventory includes prior `SEA_TRIALS.md`, the
Rigging manifest, `EXCLUDE_FILES.md`, and target metadata identity fields where those supply
Analyze job context. `EXCLUDE_FILES.md` excludes exact imported-source filenames from Analyze and
Plan prompt injection.

#### Stack Selection Is a Planning Gate
`2026-07-18` · `spec:approved` · `impl:implemented`

Analyze always provides `discovery-stack.json` as a multi-select checkbox questionnaire over real
manifest components. It has no synthetic `other` option. The LLM may recommend a small relevant
subset, but that recommendation is not an answer.

An empty stack selection is the stable `blocker-stack-selection` planning gate. Any non-empty
Commander selection in QuarterDeck confirms the stack; no approval button and no Analyze re-run
are required solely to clear this gate. Plan consumes the persisted selection directly. Other
blockers keep the existing answer-and-re-analyze workflow.

## notes_build.md

#### Story points — bytes / 4, derived on demand
`2026-06-20` · `spec:approved` · `impl:implemented`

Story points = the estimated token cost of a unit of work, defined as **byte count / 4** (rounded
up). The token estimate and the story-point count are the **same number** — a token is ~4 bytes, so
there is one derived unit, not two. Each file carries its own story-point value; a group's story
points are the sum of its files'; the total is the sum of groups. This is deterministic Python
arithmetic, but it is a **render concern, not a plan-command step**: costs are recomputed live in the
QuarterDeck every time the grouping changes, never stamped into a file. Implemented in
`src/drydock/build_compass.py` (`recompute_token_costs`, `story_points_for`).

#### BUILD_COMPASS — clean authored file, derived costs
`2026-06-20` · `spec:approved` · `impl:implemented`

`BUILD_COMPASS.md` is the grouping artifact **and** the ordering artifact — the same role as
Prototyper's `BUILD_PLAN_INTENT`. It is **generated by `plan create`** as a clean authored file
(`# ` group headers, one spec filename per line, foundational groups first) at the Target root and
edited in QuarterDeck story-planning; it is distinct from `PLAN_COMPASS.md` (human steering prose
for `plan create`). The earlier rich-narrative form (numbered phases with
`stories`/`stack`/`rules`/sizes) was rejected: it stamped derived numbers into the file and
duplicated context already in the Manifest graph, contradicting the clean-file rule. It separates
two kinds of content:

- **Authored (persisted):** group names (`# ` headers), file membership, order.
- **Derived (never persisted):** story points per file, rollup per group, total.

The file stays clean — authored content only, no numbers stamped in. Costs are always computed on
demand, so they are never stale and never touch disk. Authored on-disk form:

```
# Foundational
FEATURE-Schema.md
FEATURE-Auth.md

# Screens
SCREEN-Dashboard.md
```

Parser/writer in `src/drydock/build_compass.py` round-trips the authored content; `seed_from_specs`
produces a flat one-group seed from the Manifest's spec files.

#### QuarterDeck compass type — render, cost, and regroup engine
`2026-06-20` · `spec:approved` · `impl:implemented`

The interactive optimization happens in a UI, not in a command. The QuarterDeck `compass` type
(`QuarterDeck/app.py`) reads `BUILD_COMPASS.md` and renders one navigable pane: each group with its
story-point rollup, each file with its story points, and a total — all from `recompute_token_costs`,
never persisted. An absent file offers a one-click **seed from the Manifest**.

Navigation is deliberately dumb: move a group up/down, combine a group into the previous one, split a
file into a new group, rename a group. **Each mutation persists immediately** — it writes back only
the authored part (clean, no numbers) and re-renders so the rollups recompute live. The console holds
no working state; there is no Save button. The file round-trips clean.

#### METADATA.md format
`2026-06-19` · `spec:approved` · `impl:implemented`

One file, markdown, human-editable, standard across all Drydock-managed projects. Lives in the
target directory. `drydock init` scaffolds the default.

Required fields: `name`, `display_name`, `short_description`, `stack`, `version`.
Optional fields: `brand`, `git_repo`, `release_tag`, `build_dir`.
State field: `drydock_build_state` (written by Drydock commands, e.g. `analyzed`, `built`).

Format (no YAML block, flat key-value under a comment heading):

```
# AUTHORITATIVE PROJECT METADATA - THE FIELDS IN THIS FILE SHOULD BE CURRENT

name: PortfolioManager
display_name: Web Cloud Studio — Portfolio Manager
brand: webcloudstudio
git_repo: https://github.com/...
short_description: One-line project description.
stack: Python/Astro
version: 0.1.0
release_tag: webcloudstudio@0.1.0
build_dir: /path/to/code/output

drydock_build_state: analyzed
```

#### build_dir variable
`2026-06-19` · `spec:approved` · `impl:implemented`

`build_dir` is the directory where the LLM writes generated code. It is separate from the Drydock
target directory (`$DRYDOCK_WORKSPACE/targets/<Target>/`), which holds only Drydock artifacts.

Resolution order:
1. `--build-dir` CLI argument (overrides, may be saved back to METADATA.md)
2. `build_dir` field in `targets/<Target>/METADATA.md`
3. `$DRYDOCK_BUILD_DIRECTORY/<Target>` (environment default)

#### Variable injection — two sources, not merged
`2026-06-19` · `spec:approved` · `impl:implemented`

Two distinct sources feed the assembled prompt. They are never merged into one dict:

- **METADATA.md** → project-level context (name, stack, short_description, build_dir, etc.)
- **Plan item** → task-level context (story title, body, acceptance criteria, etc.)

Each source is injected into its own section of the assembled prompt. The `inputs:` frontmatter
field (already implemented in `prompts.py`) is the declared injection order and serves as the
variable config. No separate config file is needed.

The prompt frontmatter should declare which METADATA fields are required for this prompt (extend
frontmatter with a `variables:` block). Implementation detail of namespacing is left to the
implementer.

#### Prompt assembly order — body last
`2026-06-19` · `spec:approved` · `impl:implemented`

Correct prompt structure for all LLM-assisted commands:

```
## Job block (scalar context: paths, dates, flags)
[inputs in declared inputs: order — content documents, fenced sections]
[prompt body — instructions, last]
```

Current `analyze` has the body first (bug). Build must not repeat this. The existing analyze
assembly should be corrected when build is implemented.

#### Model config hierarchy
`2026-06-19` · `spec:approved` · `impl:implemented`

Model resolution order (highest to lowest priority):

1. `--model` CLI argument
2. `DRYDOCK_MODEL` environment variable (set via `drydock config`)
3. Default: `sonnet`

Prompt frontmatter `model:` field is a hint only and is ignored in this hierarchy. The resolved
model is computed by the caller at assembly time, not by `load_prompt`.

Rationale: sonnet is preferred for build — many per-story calls, smaller prompts, cost matters.

## notes_conformance-gate.md

#### Two acceptance levels, both tested
`2026-07-23` · `spec:approved` · `impl:implemented`

Story/block acceptance criteria (in the Blueprint) and project acceptance criteria (Sea Trials)
are both real and both tested — not either/or. Sea Trials are the LLM-judged project layer and
are naturally small (a reasonable project is not 100 LLM-evaluated criteria). The "never sample"
rule therefore bites on the programmatic ACs, not on Sea Trials.

#### Strong gates, fail fast; `score ac` stays manual
`2026-07-23` · `spec:approved` · `impl:implemented`

The gate's job is to stop a wrong story from propagating: halting and redoing a mis-built step
is cheaper than diagnosing a large finished project. The story/block-stage AC test during build
is the **automatic gate**. `drydock score ac` is **manual re-verification, not a gate** — if the
stories built honestly, it is already green.

## notes_plan.md

#### Order and Batch
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

#### PLAN_COMPASS.md (standing directive)
`2026-06-16` · `spec:approved` · `impl:implemented`

`plan create` exports a persistent `<target>/PLAN_COMPASS.md`, re-injected into the
plan-create prompt on every run. Same contract as ANALYZE_COMPASS.md: created if absent with
default body `Enter Direction for the Manifest Run`, never overwritten by the command, top-of-file
note that it is used on every `plan create` run, edited/submitted via QuarterDeck, injected near
the top (after the job block). See notes_analyze.md §Standing-Directive Feedback File.

#### BUILD_CONFIGURATION.md retired (plan create)
`2026-06-16` · `spec:approved` · `impl:implemented`

Drop `BUILD_CONFIGURATION.md` injection from `planning_session.py` and scrub `prompts/plan_create.md`.
**Supersedes** the BUILD_CONFIGURATION.md inputs in §Plan Create CLI / Inputs / Outputs and the
prototype ordering flags in §Order and Batch. PO direction now comes from PLAN_COMPASS.md and
answered questionnaires.

#### Single-directional regenerate — no state merge
`2026-06-16` · `spec:approved` · `impl:implemented`

`plan create` is a one-directional clean regenerate. Do **not** inject the existing `MANIFEST.md`,
and **remove** the module-side `_merge_states`. Every run re-authors the plan fresh; prior block
states are **not** preserved. Rationale (Ed): a new plan is a new plan; LLMs are non-deterministic,
so attempting state/id consistency across re-plans is not worth it. **Supersedes** §As-Built
"state-merge on re-run" and any AC/guardrail language implying preserved states across re-plans.

#### Final plan create injection stack
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

#### Analyze Team Lead and Product Owner handoff
`2026-07-31` · `spec:approved` · `impl:implemented`

Analyze is the Team Lead conducting the Product Owner feedback session. It evaluates completeness
of the epic and surfaces Commander expectations as product-level assertions, such as "Commander
wants a web server." Its acceptance criterion is that the Commander is satisfied that intent,
goals, constraints, contradictions, and required decisions have been captured.

Analyze is deliberately "secretly waterfall": it works iteratively with the Commander, but its
handoff must be complete and capable of becoming a buildable Plan. It authors `ANALYSIS.md` and
`COMPASS.md`; required questionnaires are answered before Plan. The story list is an expert
proposal for Plan to review, not a binding work breakdown.

#### Analyze decomposition is the default work breakdown
`2026-07-31` · `spec:approved` · `impl:implemented`

The Story List and Story Realization Map in `ANALYSIS.md` are the completed planning decomposition
and Plan's default work breakdown. Plan preserves their proposed story boundaries and mapped source
filenames unless the complete planning context shows that a story is non-atomic, inaccurate,
contradictory, incomplete, or assigns content to the wrong owner. Plan then splits, merges, moves,
replaces, or reorders the affected scope without a deviation-reporting requirement.

Full rewrite remains authoritative over governed content. Plan rewrites every resulting story as a
governed specification using all planning inputs. Source structure is strong evidence for the story
boundary; source content is not authoritative.

#### Cross-functional Plan team authority
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

#### Immutable sources and Blueprint projection
`2026-07-31` · `spec:approved` · `impl:implemented`

`blueprint/sources/**` is immutable, unconstrained Commander input. Source filenames, nesting,
headings, formatting, and completeness are never validated as governed Blueprint syntax. Analyze
and Plan receive all readable source content; Analyze guides interpretation and decomposition but
does not restrict Plan's visibility to cited files.

Markdown sources are interpreted into governed top-level Blueprint specifications. Non-Markdown
sources are copied to the corresponding path one level above `sources/`, byte for byte. The copy
preserves every existing byte, including line-ending convention and final-newline state. Imported
Markdown is never copied over an authored governed specification.

#### Persistent Commander input across replans
`2026-07-31` · `spec:approved` · `impl:implemented`

Commander input is preserved before Plan overwrites any Plan-owned artifact. It includes every
stage Compass, persistent questionnaire answers, and Commander edits or answers in Blueprint
`## Questions` sections. A deterministic scanner appends newly observed Commander information to
persistent replan memory. Replan consumes that accumulated memory so regenerated files cannot erase
human decisions or corrections.

#### Plan decisions, severity, and implied approval
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

#### Shipyard Crew build handoff and decision records
`2026-07-31` · `spec:approved` · `impl:implemented`

Build is performed by the outsourced **Shipyard Crew**, which has no synchronous feedback channel
to the Commander. It cannot generate questionnaires or create a new question workflow. When a
story requires an interpretation, the builder proceeds with the best bounded choice and may append
a decision record to that story's owning Blueprint `## Questions` section. The record states what
was done and enables later override; it does not ask for approval or block the completed build.

A decision appears only in the specification that owns it. The same conflict is not duplicated
across related stories. Commander edits to these records become persistent input to a later replan.

#### Crew presentation and terminal compatibility
`2026-07-31` · `spec:approved` · `impl:implemented`

Analyze presents the handoff using a stable crew roster: Commander, Team Lead, Planning Crew, and
Shipyard Crew. Descriptions may adapt to the project while role names and authority remain stable.
The presentation is concise, nautical, cute, and fun without obscuring status or responsibility.

CLI output is ASCII-safe on MSYS and other terminals whose Unicode rendering is not controlled.
Decorative emoji may appear in QuarterDeck HTML, where Drydock controls presentation, but terminal
meaning never depends on emoji or other ambiguous-width Unicode glyphs.

#### Plan job inventory — deterministic versus model work
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

#### One node type with story types
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

#### Foundational versus service naming
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

#### Story attributes
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

#### Feature is an assembly story
`2026-08-01` · `spec:approved` · `impl:implemented`

Features do not exist as a grouping construct. A feature is a story that depends on its member
stories, carries acceptance criteria, and carries assembly and intent instructions instead of
implementation instructions. Same node, same execution path, different content shape.

When its member stories complete, the feature story runs and is made to pass like any other story.
Integration testing therefore becomes a real build step rather than an implicit hope, covering the
seams between stories where multi-story builds actually break.

A feature story is preferably placed in the same block as its members.

#### Blocks replace features as the build grouping
`2026-08-01` · `spec:approved` · `impl:implemented`

A **block** is a set of stories optimized for context: sized to amortize fixed stack-file cost
across one build run, never crossing stacks. Blocks are an optimization output, not a taxonomy.
UI stories group together whether or not they belong to the same Agile feature.

**Supersedes** the plan prompt rule that "context economy comes from `feature` grouping, not from
bundling." Context economy comes from blocks. This is the same construct already specified in
§Order and Batch and §The Compass as the `#`-delimited batch, still LLM-seeded rather than
Python-computed.

#### Phase is Commander build sequencing
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

#### Acceptance lives in one place per audience
`2026-08-01` · `spec:approved` · `impl:implemented`

- **Programmatic Acceptance** — executable assertions carrying pass/fail state. Lives in
  `MANIFEST.md`. Not human-readable, not human-editable, regenerated wholly by every plan run.
- **User Acceptance** — human-readable intent. Lives in the Blueprint specification.

Today both appear in the Blueprint *and* `ac` blocks appear in the Manifest. That is the
duplication. Splitting by audience gives each one home.

Durability is not a discriminator: the Blueprint does not survive a replan. Only the `## Questions`
section, harvested deterministically beforehand, and notes changes survive.

#### Story sizing
`2026-08-01` · `spec:approved` · `impl:implemented`

A story is a normal Agile story: **1 to 5 story points**. Never a half point — that is a task, and a
task is folded into the story it serves. Never twelve — that is split. A story does one thing
completely, carries test criteria, and is releasable on its own. A task is not releasable and is
therefore not a story.

**A story has no token dimension.** Tokens measure the block a story is built in, never the story.
See §Token thresholds belong to the block.

**Supersedes** the story-too-big effort threshold in §Scrum Guardrails and its `.env` setting, and
supersedes this section's own earlier ceiling — "what one build agent can implement and verify in a
single pass". That framing was wrong at the root, not merely misplaced. It presumed a build pass has
a capacity edge corresponding to a unit of work; a model will accept a whole epic in one pass and
build it badly, so capacity says nothing about whether the unit is a story. It also read to a model
as a permission slip: anything that fits is fine, and "add a button" fits best of all. That was a
ceiling with no floor. The Agile definition above is the floor and the ceiling together.

The abandoned symmetry claim — an over-sized story fails at build for the same reason an over-sized
plan fails at plan — was the same error at two altitudes. Only the block has a token ceiling.

#### Shape conformance is a checker, not an instruction
`2026-08-01` · `spec:approved` · `impl:implemented`

Absolute guardrails against shape failure come from a deterministic post-checker over a declared
output contract, per `ideas/PROMPT_HARDENING.md` (Warrant / Hull Check / Second Pass). The prompt
currently ends by asking the model to verify its own delimiters and block completeness; that is
free and reliable in code.

Prompt hardening and this restructure are complementary, not alternatives. Staging is what makes a
Second Pass affordable: re-emitting a two-file stage costs almost nothing, while re-emitting a
thirty-file monolith re-sends the entire input. Hardening addresses shape failure only; it does not
address the Marina failure recorded below.

#### Plan command workflow — Zones A, B, C, D
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

#### Authorship versus verification
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

#### Content and acceptance are authored together
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

#### Programmatic Acceptance is not a node
`2026-08-01` · `spec:approved` · `impl:implemented`

Programmatic Acceptance is verification the build runs to prove a story is complete. A story is not
"built and failed" — it is built or it is not. Acceptance is therefore a field the story owns, and
passing is part of the story's own state transition, not an independent node with independent state.

`ac` leaves the block taxonomy entirely. Manifest node types are the three story types.

Closes open question 5.

#### Blueprint holds the artifact, Manifest holds the schedule
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

#### Blocks and stack creep
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

#### Builder and consumer mode
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

#### Story count is not capped
`2026-08-01` · `spec:approved` · `impl:implemented`

The ~100-story cap (`_STORY_CAP`, fatal) is removed. A correct 300-story project is plausible and
would be refused today. Scale is answered with a stronger model, not a refusal to plan.

**Justification replaced `2026-08-01`.** This section originally rested on §Story sizing's "one
build pass," which that section has since retracted. The conclusion stands on a different footing:
story count is an *output* of correct Agile decomposition, never a target to hit or avoid. The thing
worth bounding is blocks, not stories. Do not re-derive a cap from the retracted argument.

The old cap was catching bad granularity by proxy — an LLM deciding that "add a button" and "add a
test" were each a story. The proxy is gone and the thing it stood for is now stated directly in
§Story sizing. A manageable number remains the ideal, as guidance rather than a gate; when the count
is implausibly high, Analyze asks (see §Constraints surface as questions).

#### As-Built Structure (2026-08-01)
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

`tests/test_plan_graph.py` (34), `tests/test_plan_topology.py` (20), `tests/test_plan_shape.py`
(14), `tests/test_plan_stack.py` (17), plus eight Zone A/C integration tests appended to
`tests/test_planning_session.py`.

**Not carried across**

Zone D (`conform_specs`) remains unreviewed — see Open Question 4. The Zone B declaration cutover
landed separately on 2026-08-01; see §Declaration cutover as-built.

---

#### Zone B topology declaration cutover
`2026-08-01` · `spec:approved` · `impl:implemented`

**Status: landed `2026-08-01`.** `plan create` asks for `TOPOLOGY.md`; Drydock serializes
`MANIFEST.md` from it. The as-built record is §Declaration cutover as-built below; the seven-step
plan that follows is the decision record and is retained for its rationale.

**What was already done before the cutover.** `src/drydock/plan_topology.py` contains a complete,
tested declaration parser and Manifest serializer:

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
4. ~~**Instructions field.**~~ **DONE `2026-08-01`.** `parse_topology` consumes a `field: |` body,
   ending it at the first column-zero line so a following field or `## story` heading still parses;
   common indentation is stripped. `render_story_block` emits the indented two-space form
   `build_plan` reads. `instructions` joined `_PASSTHROUGH_FIELDS`. Verified end to end:
   declaration → computed Manifest → `DrydockManifest.parse`, multi-paragraph prose and blank line
   intact. This was the one real gap; **the rest is wiring.**
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

**Constraints added `2026-08-01` — read before step 3.** The delimiter guardrail landed after this
section was written and changed the signatures it describes.

- `_validate_plan_output(blocks, blueprint_dir, result, source_text=None)` takes a fourth argument:
  the delimited response the blocks were parsed from. The cutover must keep passing it. It is
  `None` only for blocks recovered from write-tool-call syntax, which carry no delimiters.
- `create_plan` tracks a `blocks_text: str | None` local alongside `blocks`. Every path that
  reassigns `blocks` must reassign it: `_parse_write_call_blocks` recovery sets it to `None` (two
  sites), and the conflict-challenge path sets it to `challenge_result.text` where it already
  rebinds `result`. Miss one and the check measures the wrong text.
- **Do not tighten delimiter pairing.** Two lenient recovery paths are deliberate and tested:
  `_repair_missing_leading_delimiter` synthesizes a dropped opening delimiter, and
  `_parse_strict_blocks_by_line` tolerates a missing final one. A strict
  `opens == ends == expected` rule breaks `test_missing_first_delimiter_is_recovered` and
  `test_missing_final_delimiter_is_recovered`. `_artifact_delimiter_defects` is narrow on purpose;
  `_artifact_delimiters_are_complete` keeps the strict rule for waiver eligibility only.
- `parse_build_plan` takes a **Path**, not text. To validate rendered Manifest text in memory use
  `DrydockManifest.parse(text)`.
- `_apply_computed_schedule` already builds the `size_fn` step 3 needs: `story_pass_tokens(...)`
  over `resolve_stack_set(...)`, with the target from `plan_stack.block_target_tokens()`. Lift it
  rather than rewriting it — only its *input* changes, from `stories_from_manifest(plan.blocks)` to
  `parse_topology(blocks[TOPOLOGY_BLOCK])`.
- Step 7 recommendation: keep `plan_reuse.md` and `plan_create_speckit.md` on the Manifest path.
  Branch on which artifact the response carries, explicitly, at the top of `_validate_plan_output`.
- **Two names are duplicated across modules — edit the right one.** `render_manifest` exists in
  both `plan_topology.py` (the serializer this section means) and `manifest_edit.py` (unrelated,
  takes a `ManifestDoc`). `_repair_missing_leading_delimiter` exists in both
  `planning_session.py` (the one on the plan path, returns `str | None`) and `artifact_blocks.py`
  (returns `str`).

**Verification reality.** No test proves the cutover works, because it changes what the *model* is
asked to emit. A fake runner emitting `TOPOLOGY.md` proves the plumbing only. The real check is a
live `drydock plan Marina` (~12 min, ~$2.70) and a live `drydock plan CommonMark` regression. Land
the wiring with fake-runner tests, then verify live — do not treat a green suite as proof.

#### Declaration cutover as-built
`2026-08-01` · `spec:approved` · `impl:implemented`

**Carrier branch.** `_validate_plan_output` resolves `carrier = TOPOLOGY.md if present else
MANIFEST.md` as its first statement, and every mode check below it keys on `carrier`. The reuse and
Spec Kit prompts are unchanged and keep the Manifest path; the branch is explicit rather than
incidental, as step 7 required.

**Zone C entry.** Once Success Mode, delimiter pairing, and the shape contract pass,
`_manifest_from_declaration` runs: `parse_topology` → `_compute_schedule` → `render_manifest`. Its
result replaces `blocks["MANIFEST.md"]` and the declaration is popped, so the rest of the function
— disambiguation, `_parse_plan_text`, questions normalization, acceptance stripping, the integrity
check — is untouched. An empty declaration and any fatal graph defect raise before a file is
written. Parse defects with a documented fallback (unknown `type`/`kind`, non-integer `phase`) and
computation warnings become plan warnings.

**`_apply_computed_schedule` did not collapse; it was lifted.** Both paths now call the shared
`_compute_schedule(declared, blueprint_dir, emitted_files)`, which owns the `size_fn` over
`resolve_stack_set` and `block_target_tokens()`. Only the *input* differs — a parsed declaration
versus `stories_from_manifest`. `_prepare_manifest_in_memory` takes `schedule_computed`, set from
`declared_topology` in `create_plan`, so the declaration path does not re-derive from the Manifest
it just wrote.

**Preamble.** Solved by splitting ownership rather than by extending the renderer. `render_manifest`
emits `# MANIFEST:`, `updated:`, `state: approved`, and `blocks:`, plus a `preamble` mapping;
`applied_specs` stays with `_prepare_manifest_in_memory`, which already owns it. `plan_hash` is
written by nothing and read by nothing but a dataclass field, so it is not emitted.
`planning_feedback` had no home in a declaration and would have been silently lost: the new
`parse_topology_preamble` reads `planning_feedback` and `note` from before the first `## story`
heading, and the prompt directs the model to put them there.

**Contract.** `PLAN_TOPOLOGY_CONTRACT` (`required=(TOPOLOGY.md,)`) sits beside the unchanged
`PLAN_OUTPUT_CONTRACT`; `check_plan_shape` takes the contract as an argument and the carrier
selects it. `TOPOLOGY.md` joined `_RESERVED_BLOCKS`, so it is never written to `blueprint/`, and
`_outside_text_is_waiver_eligible` accepts either plan artifact as the terminal block.
`_parse_write_call_blocks` recovers a target-root `TOPOLOGY.md` write call the same way it recovers
`MANIFEST.md`.

**Passthrough.** `copy`, `scope`, and `feedback` joined `_PASSTHROUGH_FIELDS` and the render order,
closing the gap between what `MANIFEST_CONTRACT.md` lets the model author and what a declaration
could carry.

**Prompt versions.** `prompts/plan_create.md` V28 (step 7 rewritten as a declaration grammar with a
worked example; Output Contract, Hard Rules, and the Sea Trials audit retargeted),
`prompts/MANIFEST_CONTRACT.md` V14 (one paragraph stating that `plan create` emits the declaration
and that the field semantics govern both forms).

**Tests.** Eight in `tests/test_planning_session.py` (serialization and computed order, declaration
never on disk, `planning_feedback` carried, phase inversion refused, unknown edge refused, empty
declaration refused, Manifest carrier still plans, topology contract) and three in
`tests/test_plan_topology.py` (preamble fields, no preamble after the first story, rendered preamble
parses back).

**Still true: not verified live.** The suite proves plumbing only.

#### Token thresholds belong to the block
`2026-08-01` · `spec:approved` · `impl:implemented`

The token ceiling is a **block** property. Because a block holds at least one story, it constrains a
story only in the degenerate single-story case — which is the only sense in which token cost is ever
story guidance. One measurement, one owner, no duplicate rule to keep in sync.

Two thresholds, both user-settable:

| Threshold | Default | Meaning |
|---|---|---|
| `prompt_warn_tokens` | 50,000 | Yellow. Advisory, surfaced as a Manifest annotation. Never a stop sign. |
| `prompt_error_tokens` | 120,000 | Red. The only genuine ceiling. |

Warn must stay advisory on evidence, not preference: the first real specification tested against it
— CommonMark — tripped 50K immediately with a legitimate contract. A threshold a correct plan
crosses on day one cannot be a gate.

`plan_stack` names this directly: `block_target_tokens()`, `exceeds_block_target()`,
`DEFAULT_BLOCK_TARGET_TOKENS`. Prior spellings (`story_budget_tokens`, `exceeds_build_pass`,
`DEFAULT_STORY_BUDGET_TOKENS`) are retained as aliases; they attached the measurement to a story.

#### Artifact delimiter guardrail
`2026-08-01` · `spec:approved` · `impl:implemented`

Two structural failures reached the Blueprint as silent damage. Both now fail loudly in
`_validate_plan_output`, via `_artifact_delimiter_defects`.

- **Opens but never closes.** `_BLOCK_RE` pairs on a backreference, so an opener with no
  `=== END ===` matches nothing and the whole specification vanishes without a word. One real run
  lost `FEATURE-Autolinks.md` from a 26-artifact response.
- **A header inside a parsed body.** The response was cut mid-artifact and resumed by restarting it;
  `_BLOCK_RE` then spans from the first header to the first `=== END ===`, fusing the truncated
  attempt and its retry into one block that still pairs 1:1 and still counts as present.

Validated against 26 recorded runs: 23 clean accepted, 3 rejected, each provable damage. The check
is **structural and has no opinion about size** — it is not a token gate and must never become one.
It is deliberately narrow: missing leading and trailing delimiters have their own recovery paths,
and orphan `END` lines are already rejected by `_reject_unpaired_end_delimiters`.

The check runs only when the blocks came from delimited text. Blocks recovered from write-tool-call
syntax carry no delimiters, so `source_text` is `None` for them and the check is skipped.

#### Compact substitution rule — stack files
`2026-06-22` · `spec:approved` · `impl:implemented`

The first use of a stack file across the full build uses the full file. Every subsequent use
substitutes the compact derivative (`*_compact.md`) if it exists. The rule is build-order-global —
not per-story, not phase-based.

The manifest always stores canonical names (`common.md`, `fastapi.md`). Compact substitution is
derived, never authored.

#### Applied registry in the manifest
`2026-06-22` · `spec:approved` · `impl:implemented`

`build` writes one field to the manifest: a per-file applied registry. Each entry records the git
commit ID at the time the file was applied to a build step.

Substitution logic at build time:
- No applied record, or recorded commit differs from HEAD → use **full** file; record commit on
  successful build completion
- Recorded commit matches HEAD → use **compact**
- Uncommitted working tree → **build blocked** (no clean commit ID available)

The manifest is not human-editable (managed via QuarterDeck). No human override of applied flag.

#### Applied Blueprint Specification provenance
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

#### Uncommitted files guard
`2026-06-22` · `spec:approved` · `impl:implemented`

A build step cannot execute if the working tree contains uncommitted changes. The applied registry
records commit IDs; a dirty tree yields no reliable ID to record or compare.

#### Cost estimator forward pass
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

## notes_planning_questions.md

#### Canonical Questions section
`2026-07-31` · `spec:approved` · `impl:implemented`

Every question-bearing Markdown artifact uses the exact heading `## Questions`. Alternate structural
headings such as `## Open Questions`, `## Question`, and bare `QUESTIONS:` are invalid. In a Typed
Blueprint, `## Questions` is the first `##` section after the title and typed metadata table. The
section remains present when empty and contains `- None.`.

Each question uses a deterministic, human-readable record:

```markdown
## Questions

### Q-001: State Changer

- Origin: plan
- Status: open

#### Question

Which state model governs this workflow?

#### Answer
```

Origins include `plan` and `analyze-questionnaire`. Status values include `open` and `answered`.
An answered record requires a non-empty answer. Sea Trials uses the same section syntax.

#### Story-local build gate
`2026-07-31` · `spec:approved` · `impl:implemented`

An open Blueprint question marks the owning Manifest story `Blocked Questions`. The story and its
transitive dependents are not buildable. Independent frontier stories remain buildable. Answering
every question automatically ungates the story; no additional approval is required.

The Manifest clearly projects question counts and the `Blocked Questions` state. A Commander may
approve an unanswered story in the current Manifest. That approval ungates the current plan but is
not a substantive answer and does not survive Manifest replacement or feed a future Plan run.

#### QuarterDeck question editing
`2026-07-31` · `spec:approved` · `impl:implemented`

QuarterDeck groups Build Questions by Blueprint and provides an answer textarea and Save action for
each question, in addition to full Blueprint editing. Saving writes directly to the Blueprint,
changes the question to `Status: answered`, preserves its stable ID, origin, and text, and dirties the
Blueprint normally.

QuarterDeck also exposes the persistent Plan Feedback artifact. When the originating Blueprint
exists, the persistent record is read-only and the Blueprint question interface owns editing. When
the originating Blueprint no longer exists, QuarterDeck may edit the persistent record directly.

#### Persistent Plan feedback
`2026-07-31` · `spec:approved` · `impl:implemented`

A substantive answer is promoted into a persistent Plan feedback store. The durable decision has a
stable semantic identity independent of Blueprint filenames and story decomposition. A source
Blueprint path is provenance only.

The record retains the stable decision ID, origin, semantic subject, original question, answer,
answer timestamp, source Blueprint provenance, and current disposition. The Blueprint is the
authority while it exists; the feedback store preserves continuity across Blueprint replacement.

#### Replan decision realization
`2026-07-31` · `spec:approved` · `impl:implemented`

Before replacing Blueprints, Plan harvests answered Blueprint questions into persistent feedback and
injects all active feedback into the Plan prompt. A resolved decision is written into normal Blueprint
content, not reproduced under `## Questions`.

Plan classifies every injected decision as `applied`, `retained`, or `retired`. Applied decisions name
their current realization. Retained decisions remain future Plan feedback. Plan may retire a decision
only because a product scope change makes it irrelevant, and it records the reason. Missing, renamed,
split, merged, or replaced Blueprint files never justify retirement.

The Manifest records the current run's feedback disposition and realization without becoming the
authoritative decision store.

#### Analyze-to-Plan closure
`2026-07-31` · `spec:approved` · `impl:implemented`

Analyze questionnaires remain persistent pre-Plan human-decision sources. Plan consumes their answers
and creates the owning Blueprint with the decision applied to normal specification content. Provenance
is retained in persistent Plan feedback.

When additional human-owned unknowns arise during Blueprint creation, Plan emits them under the owning
Blueprint's `## Questions` section instead of deferring the entire Plan. Only a question that prevents
coherent story decomposition may stop Plan before Blueprints exist.

## notes_quarterdeck.md

### Move validation — layer bands, not linear dependency — 2026-07-03
`2026-07-03` · `spec:approved` · `impl:implemented`

**Symptom (Marina2).** Moving the Infrastructure feature up was rejected with "would break build
topology: ac-marlib-1 before its dependency infra; voice-capture before its dependency s3-share."
The message named blocks that are not drawn on the compass, so the reason was invisible.

**Diagnosis.** `infra` (Terraform Layers) is in the *right* spot — it depends on catalog, report,
access-control, queue, and s3-share, so it correctly sits last among the features. The manifest's
only forward-reaching edges are two *acceptance* blocks: `ac-marlib-1` (under marlib, feature 2)
and `ac-ui-terraform-1` (under Screen — Terraform), both `depends: infra`. Every *story* already
sits after its dependencies. So the file is linearly valid except for acceptance blocks pointing
forward.

**Root cause.** The move validator enforces a strict "every block after all its deps" invariant.
But file order does not determine build correctness — the engine picks work at run time via
`next_buildable_step()` walking `depends:`. Manifest order is display/priority only. The validator
guards an invariant the engine never needs.

**Decision.**
- Ordering constrains **layer bands only**: Foundation < Data/Persistence < Features ≈ Screens.
  Features and Screens are one band — no "all features before any screen" rule. Movement is free
  within a band.
- `ac` blocks leave the ordered stream entirely — never positioned, never move-checked.
- The validator lists only the violations a move actually causes, not the full pre-existing set.
- **Auto-normalize** = topo-sort the manifest into a canonical valid order (a real capability, not
  a rescue for an invalid file). Offered when a manifest is out of band order.

**Open rendering gap.** The compass draws stories but not their `ac` blocks and prints no
dependency names, which is why the rejection cited items the Commander cannot see. Rendering `ac`
as each story's Definition of Done (below) closes this.

## notes_rigging_compact.md

#### Compact audience is user, not builder
`2026-06-22` · `spec:approved` · `impl:implemented`

The compact derivative is written for a **consumer** of the service described in the source file —
an agent that calls the API, not one that builds it. Builders receive the full source file.
The previous implementation produced a "behaviorally faithful miniaturization" preserving every
constraint and code block. That was the wrong lens; it produced a smaller builder document, not a
caller document. The new prompt extracts only callable units.

#### Output format: MCP-inspired markdown
`2026-06-22` · `spec:approved` · `impl:implemented`

Each callable unit (HTTP route, class method, function, required config entry) is one block:

```
### METHOD /path   or   ### ClassName.method_name
One-line description.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|

Returns: TypeName — brief description
```

This mirrors the MCP tool schema (name, description, inputSchema, returnType) in a form any LLM
trained on tool-use patterns can read immediately. Tables may be used for structured return schemas.
Rationale, implementation detail, constraints, and code blocks showing internals are excluded.

#### No-surface classification and COMPACT_ERROR
`2026-06-22` · `spec:approved` · `impl:implemented`

Files with no callable technical surface (branding guides, tone documents, process narratives)
cannot produce a useful compact derivative. The LLM classifies these inside the prompt and emits:

```
COMPACT_ERROR: no technical surface — builder use only
```

The module detects this token, marks the item `no-surface` (not `failed`), and writes no compact
file. Exit code remains 0 — this is expected behavior, not an error. The distinction from `failed`
(which is an LLM error) is critical: `no-surface` is the correct outcome for builder-only files.

#### File selection: --include-file, --exclude-file, --include-dir
`2026-06-22` · `spec:approved` · `impl:implemented`

The existing auto-discovery (required pairs + existing `_compact.md` siblings) remains the
default. Three new flags extend it:

- `--include-file <file.md>` — add a specific file (repeatable)
- `--exclude-file <file.md>` — remove a file from the auto-discovered set (repeatable)
- `--include-dir <dir>` — add all `.md` files under a directory (repeatable)

All inputs must resolve to `.md` files. `_compact.md` files are never sources.
Files are processed one at a time; no batch LLM calls.
