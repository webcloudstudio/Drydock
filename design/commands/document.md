# MEMORY: drydock document

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Description | Produce Target documentation from the Blueprint. |
| Route | document |
| Modules | `target_documentation.py`, `readme_generate.py` |
| Prompts | `document_generate.md` |
| Tests | `tests/test_target_documentation.py`, `tests/test_readme*.py` |
| Topics | — |
| Pending spec | 0 |
| Pending impl | 0 |

## Intent

Produce Target documentation from the Blueprint. `generate` spends one LLM call writing
`DOC-<SECTION>.md` guides; `assemble` deterministically renders them into a themed, browsable
`index.html`; `assemble readme` rebuilds the built project's `README.md` from Blueprint files.

## Guardrails

- None.

## Details

### Syntax

```text
drydock document <Target> [--model <model>] [--llm-provider <p>] [--theme <theme>]
drydock document generate <Target> [--model <model>] [--llm-provider <p>]
drydock document assemble <Target> [--theme <theme>]
drydock document assemble readme <Target>
```

### Rules

`2026-10-21` · **A reply without artifacts is retried once, with the reason.** A successful reply that holds no artifact delimiter — prose, a question, a refusal — prints
`[document] response without artifacts, retrying once with the reason: "<excerpt>"` and reruns the
unchanged prompt with an appended `Artifact retry` block that quotes the reply and forbids asking,
refusing, or explaining. A second such reply fails the ordinary parse. Shared mechanism:
`artifact_blocks.retry_reply_without_artifacts`. *Broken:* LayersTesting `20261021.180733`
ended at analyze when Haiku asked which output form to use instead of emitting.

`2026-10-21` · **Stray text is discarded, never fatal.** Up to three lines of plain narration
before, between, or after intact artifact blocks are dropped and printed as `[document] stray text
<where> discarded: "<text>"`. Outside text shaped like content — a heading, list, table, fence,
JSON, markup, `===`, more than three lines or 500 characters — or beside an orphan close still fails
the parse. *Broken:* a weak model's one-line preamble fails the run, or a body that lost its opener
is silently dropped.

`2026-07-01` · **Configuration is created once and owned by the Commander.**
`targets/<Target>/documentation.yaml` (theme, sections) is written with defaults when absent and
never overwritten. Default sections: `OVERVIEW`, `FEATURES`, `SCREENS`, `ARCHITECTURE`, `SCHEMA`,
`FLOWS`, `PIPELINE`, `SIGNALS`; the first four are required. Themes: `slate`, `harbor`, `paper`.
Cost when broken: Commander layout choices reset on every run.

`2026-07-01` · **Documentation lands beside the built software.** Guides and `index.html` are
written to `$DRYDOCK_BUILD_DIRECTORY/<Target>/docs/`, not the workspace. Cost when broken:
published docs separated from the code they describe.

`2026-07-01` · **The model emits guides; the module writes them.** `generate` parses delimited
`DOC-*.md` blocks for the configured sections, writes each, and deletes known guides the response
did not emit, so the guide set always matches the last generation. A failed call writes nothing.
Cost when broken: stale guides from an earlier section set mixed with current ones.

`2026-07-01` · **Assembly is deterministic and needs guides.** `assemble` spends nothing, writes
`styles/spec.css` and `index.html`, and fails when no `DOC-*.md` exists. Cost when broken: an
empty site published as documentation.

`2026-06-10` · **README generation never aborts a build.** `generate_readme` swallows its own
failures and returns nothing; `assemble readme` turns that into exit `1` with the reason. It
requires the build directory to exist. Cost when broken: a README defect fails a successful build.

### Mechanism

1. **generate** — ensure config, assemble the prompt from Blueprint files and metadata, one
   `run_prompt`, parse and write guides, prune unemitted known guides.
2. **assemble** — validate theme, discover guides in section order, write CSS and `index.html`.
3. **pipeline** (`document <Target>`) — generate, then assemble.
4. **readme** — resolve `build_dir` from `METADATA.md` or config, write `README.md`.

### Exit codes

| Code | Condition |
|---|---|
| `0` | Written. |
| `1` | Target, build directory, or guides missing; LLM failure; README generation failed. |
| `2` | Usage error, unknown theme, or unexpected arguments. |

### Spec divergence

- The specification does not state that output is written to
  `$DRYDOCK_BUILD_DIRECTORY/<Target>/docs/`, or that sections not emitted are deleted.

## Decisions

-

## Questions

1. **Dead assemble path.** `cli.cmd_document_assemble(argv)` is unreferenced. It runs the
   `build_documentation` assembler and rewrites `app_help_file_location` in every Target's
   `console.yaml`. Remove it?

## Actions

-

## Working Notes

-
