# NOTES: Build

| Field | Value |
|-------|-------|
| Version | 2026-06-20 V2 |
| Route | build |
| Status | Working notes — not canonical specification |
| Description | Design decisions for `drydock build` — the plan/group/cost layer upstream of build, prompt assembly, variable injection, model config, and output contract. |
| Pending spec | 10 approved items |
| Pending impl | 6 unimplemented sections |

## Goal

Build `drydock build` the correct way, and iterate that.

## Decisions

### The process gap — plan/group/cost layer is upstream of build
`2026-06-20` · `spec:approved` · `impl:unimplemented`

Prototyper's pipeline was: Blueprint files + type specs → intent grouping (`BUILD_PLAN_INTENT`)
→ ordered phases → iteration loop. The intent file was the pivot that turned a flat input set into
a known, enumerable sequence of build steps. Drydock had a gap: nothing played the role of
`manifest_intent`. The plan gave stories, but stories are units of intent, not phases (a coherent
file-group with a known output set).

The gap is closed by giving Drydock the same shape, with the graph database and QuarterDeck doing
the work Prototyper did by hand:

```
specs → group (foundational first, no mixed screen/feature files) → cost each group in Python → build each step one at a time
```

Key consequence: this entire layer is **upstream of `drydock build`** and does not touch the build
command. Grouping, ordering, story-point costing, and interactive optimization all live in Python +
QuarterDeck. By the time `drydock build` runs, it walks an already-ordered, already-costed,
already-clean MANIFEST_COMPASS and makes one oneshot call per story. Build stays dumb — which is why
it can still be designed cleanly, since it is not yet built.

### Story as unit of work — file = feature/screen = story
`2026-06-20` · `spec:approved` · `impl:unimplemented`

`drydock analyze` decomposes by feature or screen, so each spec file represents a single feature or
screen — a finite code set suited to a single oneshot call. Therefore, for now:

**file = feature/screen = story = one oneshot call.**

This is directionally 1:1. Whether `tickets.json` and the specifications diverge is **postponed** —
no representative data set exists yet to test it. Assume convergence until tested.

A group is a batch of stories that share a context preamble and are built foundational-first with no
mixed screen/feature files. Each story is still its own oneshot call; grouping packs like objects so
the shared context ("stack tokens" — type specs, conventions, surrounding interfaces) is sent once
instead of re-sent per file.

### Story points — bytes / 4, computed at plan time
`2026-06-20` · `spec:approved` · `impl:unimplemented`

Story points = the estimated token cost of a unit of work, defined as **byte count / 4**. Each file
carries its own story-point value; a group's story points are the sum of its files'. Because every
input is known before the first LLM call, this is deterministic Python arithmetic computed at
`drydock plan` time — a pre-flight cost estimate, not a runtime guess.

### MANIFEST_COMPASS — clean authored file, derived costs
`2026-06-20` · `spec:approved` · `impl:unimplemented`

MANIFEST_COMPASS is the grouping artifact **and** the ordering artifact — the same role as
Prototyper's `BUILD_PLAN_INTENT`. It separates two kinds of content:

- **Authored (persisted):** group names, file membership, order.
- **Derived (never persisted):** token count per file, story-point rollup per group, totals.

The file stays clean — authored content only, no numbers stamped in. Costs are always computed on
demand, so they are never stale and never touch disk. Conceptual readout shape:

```
# Named Group    Story Points = xxx
FileName.md    Token Count = xxx   Story Points = xxx
```

That readout is a rendered view, not the file's on-disk form.

### QuarterDeck — render, cost, and regroup engine
`2026-06-20` · `spec:approved` · `impl:unimplemented`

The interactive optimization happens in a UI, not in a command. QuarterDeck reads MANIFEST_COMPASS,
computes token counts and story-point rollups live (bytes / 4), and renders the costed dashboard.
The user drags files between groups and reorders them; rollups recompute instantly because they were
never persisted. This is interactive optimization — watch the rollups rebalance, then save.

Round-trip contract: **on save, QuarterDeck writes back only the authored part** (regrouped /
reordered list). Computed columns never touch disk. The file round-trips clean.

### METADATA.md format
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

### build_dir variable
`2026-06-19` · `spec:approved` · `impl:implemented`

`build_dir` is the directory where the LLM writes generated code. It is separate from the Drydock
target directory (`$DRYDOCK_WORKSPACE/targets/<Target>/`), which holds only Drydock artifacts.

Resolution order:
1. `--build-dir` CLI argument (overrides, may be saved back to METADATA.md)
2. `build_dir` field in `targets/<Target>/METADATA.md`
3. `$DRYDOCK_BUILD_DIRECTORY/<Target>` (environment default)

### Variable injection — two sources, not merged
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

### Prompt assembly order — body last
`2026-06-19` · `spec:approved` · `impl:implemented`

Correct prompt structure for all LLM-assisted commands:

```
## Job block (scalar context: paths, dates, flags)
[inputs in declared inputs: order — content documents, fenced sections]
[prompt body — instructions, last]
```

Current `analyze` has the body first (bug). Build must not repeat this. The existing analyze
assembly should be corrected when build is implemented.

### Model config hierarchy
`2026-06-19` · `spec:approved` · `impl:implemented`

Model resolution order (highest to lowest priority):

1. `--model` CLI argument
2. `DRYDOCK_MODEL` environment variable (set via `drydock config`)
3. Default: `sonnet`

Prompt frontmatter `model:` field is a hint only and is ignored in this hierarchy. The resolved
model is computed by the caller at assembly time, not by `load_prompt`.

Rationale: sonnet is preferred for build — many per-story calls, smaller prompts, cost matters.

### Loop structure — deferred
`2026-06-19` · `spec:na` · `impl:unimplemented`

`build` loops in Python: one LLM call per plan story. Deferred to separate design session.

```python
for story in load_plan_stories(compass_path):
    inputs = base_inputs | story_fields(story)
    assembled = assemble_prompt("build_story", inputs)
    result = llm.run_prompt(assembled, model=resolved_model, ...)
    write_output(story, result)
    update_state(story.id, "built")
```

## Acceptance Criteria

- `drydock init` scaffolds a valid METADATA.md in the target directory
- `drydock build --build-dir <path>` resolves and persists `build_dir` correctly
- Model resolves via `--model` → `DRYDOCK_MODEL` → `sonnet`
- Assembled prompt structure: job block → inputs → body (instructions last)
- METADATA fields and plan item fields are injected from separate sources

## Guardrails

- Never merge METADATA variables and plan item variables into one namespace
- `build_dir` never points into `$DRYDOCK_WORKSPACE/targets/` — it is a separate code output path
- Prompt frontmatter `model:` value is not authoritative; model hierarchy overrides it
- Do not spend API credits in tests; inject a fake runner

## Open Questions

- Does the prompt header (METADATA context block) belong in Rigging (governed, ships with tool)
  or in the target's Blueprint (per-project customizable)?
- What is the output contract for build? Same delimited-block pattern as analyze
  (`=== FILENAME === ... === END FILENAME ===`), or different? Filenames come from the plan item,
  not a fixed known set.
- What does "foundational first" mean concretely in the ordering — derived from graph topology
  (dependency traversal), or a declared tier on each group? (Not yet explored.)

## Not in scope yet

- Loop design details (deferred to separate session)
- `drydock build status` and `drydock build score`
- QuarterDeck evidence integration for build
- Multi-phase build orchestration
- `tickets.json` vs specification divergence — postponed; no representative data set yet. Assume
  file = feature/screen = story convergence until tested.
