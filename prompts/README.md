# Drydock Prompts

This directory contains prompts used by Drydock commands that invoke LLM agents.

Prompts are ported alongside the commands that consume them. Implemented commands receive their
prompts here; deferred commands have no prompts yet.

## Prompt contract

- **Naming:** `<command>_<subcommand>[_<modifier>].md`, lowercase (`_<modifier>` only when an
  operation needs more than one prompt).
- **YAML frontmatter:** every prompt file begins with a leading `---` YAML frontmatter block.
- **Required blocks:** every prompt frontmatter block includes `name`, `description`, `version`,
  and `intent`.
- **Optional blocks:** frontmatter may also include `command`, `model`, `effort`, `inputs`, and
  `output`. `effort` is one of `low`, `medium`, `high`, `xhigh`, `max`; when absent the provider's
  own default reasoning depth stands.
  Frontmatter is loaded and validated by `drydock.prompts.load_prompt`.

| Command | Prompt file | Status |
|---|---|---|
| `drydock rigging compact` | `rigging_compact_contracts.md`, `rigging_compact_architecture.md`, `rigging_compact_database.md` | Implemented |
| `drydock prompt review` | `prompt_review.md` | Implemented |
| `drydock score drydock` | `score_drydock.md` | Implemented |
| `drydock analyze` | `analyze.md` | Implemented |
| `drydock plan create` | `plan_create.md` | Implemented |
| `drydock document generate` | `document_generate.md` | Implemented |
| `drydock import` | `import_source.md`, `import_speckit.md` | Not yet ported — command is deferred |
| `drydock build` | `build_story.md`, `build_spike.md` | Not yet ported — command is deferred |

## Config-driven inputs

`inputs:` is the agent's source of truth for **which files it consumes and in what order**. It is an
ordered, comma-delimited list of logical tokens; the Python assembler resolves each token to real
paths and globs at prompt-assembly time. The list is the injection (stack) order and always begins
with `COMPASS.md`. It is derived directly from the Artifact Feed Matrix
(`docs/Drydock_Specification.md`): every artifact whose column for that command carries an `I`,
`O/I`, `O*/I`, or the `X` gate.

Naming: a single file is named by its on-disk filename (`COMPASS.md`, `MANIFEST_CONTRACT.md`,
`tickets.json`); a globbed group uses a suffix-less logical token.

| Token | Resolves to |
|---|---|
| `QUESTIONNAIRES` | answered `QuarterDeck/questionnaires/spike-*.json` |
| `TYPED_SPEC` | the Typed Specification / blueprint source files (globbed) |

Rules:

- **Absent inputs are skipped** at assembly. `COMPASS.md`, the feedback files, and `BLOCKERS.md` are
  conditional; a listed input that does not exist is silently omitted.
- **Per-token semantics live in the assembler, not the row.** Most tokens inject fenced content;
  `BLOCKERS.md` injects prior answers for `analyze` but acts as the refuse-if-present gate for
  `plan create` (its `X` in the matrix). One row, command-aware resolution.
- **Computed job metadata** (date, target, blueprint path, system shape, analysis quality) is not a
  file and is not represented in `inputs:`.

`build`, `build score`, and `refit` receive their `inputs:` rows when their prompts are authored;
their matrix-derived rows are recorded in `notes/notes_quarterdeck.md` (§ Config Driven Agents).
