# NOTES: Build

| Field | Value |
|-------|-------|
| Version | 2026-06-20 V3 |
| Route | build |
| Status | Working notes — not canonical specification |
| Description | Design decisions for `drydock build` — the plan/group/cost layer upstream of build, prompt assembly, variable injection, model config, and output contract. |
| Pending spec | 2 approved items |
| Pending impl | 3 unimplemented sections |

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
already-clean BUILD_COMPASS and makes one oneshot call per story. Build stays dumb — which is why
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
