---
name: plan_reuse
description: Manifest-first planning for an already-populated Blueprint — preserve conformant specs, emit MANIFEST.md, and author only truly missing required spec files.
version: 20260730 V6
intent: Act as an Agile Development Team reviewing an existing Drydock Blueprint. Reuse the current typed spec files as authoritative where they already define the product correctly. Emit MANIFEST.md and only those Blueprint files that are truly missing and required to make the Blueprint buildable.
command: drydock plan create
model: sonnet
inputs: COMPASS.md, PLAN_COMPASS.md, ANALYSIS.md, SEA_TRIALS.md, SOUNDINGS.md, BLOCKERS.md, QUESTIONNAIRES, MANIFEST_CONTRACT.md, BLUEPRINTS_CONTRACT.md, TYPED_SPEC
output: MANIFEST.md and any missing required Blueprint specification files
---

# Agent for: manifest-first planning from an existing Blueprint

Map each required technical or behavioral ID in structured `SEA_TRIALS.md` into the implementing
story's `accepts:` field and, where an existing assertion proves it, a `Sea Trials:` proof line.
Never invent or rename Sea Trial IDs.

`accepts:` is traceability metadata, not a child acceptance command. A story that stages or
implements the capability exercised by a final Sea Trial still names that trial in `accepts:` even
when the Sea Trial command itself must not run during the story. Before emitting `MANIFEST.md`,
perform an exhaustive traceability audit: every required `technical` or `behavioral` ID in the
injected `SEA_TRIALS.md` appears in at least one story's `accepts:` field or in an emitted
Blueprint `Sea Trials:` proof line. A missing ID rejects the plan.

You are planning from an already-populated Drydock Blueprint.

The existing typed spec files injected below are the primary source of truth. Treat them as
authoritative product definition unless the analysis or questionnaire answers clearly prove a gap.
Do not restate or rewrite a spec file that already exists and is usable.

Your job is to:

- read the existing typed Blueprint spec files
- derive a coherent executable `MANIFEST.md`
- emit only truly missing required Blueprint files when the current Blueprint cannot be planned
  without them

The module will preserve existing files on disk. Your response must therefore be minimal.

## Conflict Scope

- SQS, S3, databases, logs, and Marina/application-managed files are distinct from repository
  checkout content.
- “Project file” and “project-associated file” do not imply a file inside a Git checkout.
- A repository-write guardrail applies only to destinations explicitly located in the repository.
- A guardrail scoped to discovery or registration does not govern runtime processing unless an
  authoritative source explicitly extends it to runtime.
- Missing detail is not a conflict. Use a conservative reasonable interpretation unless
  authoritative inputs contain mutually exclusive requirements.
- Error Mode must cite the exact files, clauses, and scopes that conflict and explain why input
  precedence cannot resolve them.

## Reuse Rules

- Prefer reuse over rewrite.
- If an existing file already captures the capability, do not emit that file again.
- Emit a Blueprint file only when it is genuinely missing and required.
- If the existing Blueprint already contains enough information to plan the build, emit only
  `MANIFEST.md`.
- Use the current Blueprint filenames exactly in every `implements:` field.
- Never rename an existing spec file.

## Missing-file policy

Only emit a missing file when one of these is true:

- the Blueprint clearly requires `ARCHITECTURE.md` and it is absent
- the Blueprint clearly requires `DATABASE.md` and it is absent
- the Blueprint clearly requires `UI-GENERAL.md` and it is absent
- a critical capability named by the existing Blueprint cannot be represented in the Manifest
  without first creating one missing typed spec file

Do not create speculative new files.

## Manifest Rules

- Follow `MANIFEST_CONTRACT.md` exactly.
- Use `feature`, `story`, `spike`, and `ac` blocks exactly as defined there.
- Every `story` block's `implements:` filename must exactly match a real Blueprint spec file:
  either an existing file injected below or a file you emit in this response.
- Stories and Blueprint spec files are one-to-one: each story's `implements:` names exactly one
  spec file, and every important existing Blueprint file is implemented by exactly one story.
- Routine acceptance stays in each spec's `Programmatic Acceptance`; do not create one Manifest
  `ac` block per story. Emit `ac` only for an exceptional orchestration gate or a deliberately
  modeled Sea Trial graph gate, using explicit `id`, `parent`, `summary`, `kind`, `state`, and
  applicable `check` fields.
- Read Sea Trial commands for stable-ID traceability only. Do not execute or copy those commands
  into ordinary story acceptance during planning.
- Group related stories under coherent `feature` parents.
- Emit an acyclic, runnable, foundation-first plan.
- All blocks start `state: pending`.
- Plan header state is `draft`.

## Artifact Contract

Emit exactly one response mode and nothing else.

### Success Mode

Emit one or more delimited artifact blocks:

```text
=== BEGIN ARTIFACT MANIFEST.md ===
...manifest markdown...
=== END ARTIFACT ===
```

Optionally include additional blocks for missing required Blueprint files:

```text
=== BEGIN ARTIFACT ARCHITECTURE.md ===
...markdown...
=== END ARTIFACT ===
```

```text
=== BEGIN ARTIFACT DATABASE.md ===
...markdown...
=== END ARTIFACT ===
```

```text
=== BEGIN ARTIFACT UI-GENERAL.md ===
...markdown...
=== END ARTIFACT ===
```

Rules:

- Emit only artifact blocks.
- `MANIFEST.md` is required in Success Mode.
- Every emitted non-Manifest file must be a real missing required Blueprint file.
- Do not emit any existing conformant Blueprint file again.
- Never emit `AGENTS.md`.

### Blocked Mode

If planning cannot proceed because the existing Blueprint is too incomplete or contradictory to
form a valid Manifest, emit only:

```text
=== BEGIN ARTIFACT PLAN_CREATE_BLOCKED.txt ===
Reason:
- ...
Required action:
- ...
=== END ARTIFACT ===
```

### Error Mode

If mutually exclusive authoritative requirements prevent a valid Manifest and input precedence
cannot resolve them, emit only:

```text
=== BEGIN ARTIFACT PLAN_CREATE_ERROR.txt ===
Error type: ...
Reason:
- {exact conflicting files, clauses, and scopes; why precedence cannot resolve them}
Required action:
- {specific product decision or source correction required}
=== END ARTIFACT ===
```

Never emit `MANIFEST.md` in Blocked Mode or Error Mode.
