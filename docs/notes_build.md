# NOTES: Build

| Field | Value |
|-------|-------|
| Version | 2026-06-19 V1 |
| Route | build |
| Status | Working notes — not canonical specification |
| Description | Design decisions for `drydock build` — prompt assembly, variable injection, model config, and output contract. |
| Pending spec | 5 approved items |
| Pending impl | 1 unimplemented section |

## Goal

Build `drydock build` the correct way, and iterate that.

## Decisions

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

## Not in scope yet

- Loop design details (deferred to separate session)
- `drydock build status` and `drydock build score`
- QuarterDeck evidence integration for build
- Multi-phase build orchestration
