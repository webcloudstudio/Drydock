# Drydock Prompts

This directory contains prompts used by Drydock commands that invoke LLM agents.

Prompts are ported alongside the commands that consume them. Implemented commands receive their
prompts here; deferred commands have no prompts yet.

## Prompt contract

- **Naming:** `<command>_<subcommand>[_<modifier>].md`, lowercase (`_<modifier>` only when an
  operation needs more than one prompt).
- **Metadata:** a leading `---` YAML frontmatter block with required `name`, `description`,
  `version`, `intent` and optional `command`, `model`, `output`. Loaded and validated by
  `drydock.prompts.load_prompt`.

| Command | Prompt file | Status |
|---|---|---|
| `drydock rigging compact` | `rigging_compact.md` | Implemented |
| `drydock log append` capture contract | `log_append_capture.md` | Implemented |
| `drydock log audit` diff audit | `log_audit.md` | Implemented |
| `drydock plan create` | `plan_create.md` | Not yet ported — command is deferred |
| `drydock document generate` | `document_generate.md` | Not yet ported — command is deferred |
| `drydock import` | `import_source.md`, `import_speckit.md` | Not yet ported — command is deferred |
| `drydock analyze` | `analyze.md` | Not yet ported — command is deferred |
| `drydock build` | `build_story.md`, `build_spike.md` | Not yet ported — command is deferred |
