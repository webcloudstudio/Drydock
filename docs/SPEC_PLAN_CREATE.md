# drydock plan create — Process Specification

**Version:** 20260613 V1  
**Command:** `drydock plan create <Blueprint> <Target>`  
**Status:** Draft — candidate section for `docs/Drydock_Specification.md`

---

## Purpose

`drydock plan create` performs agile story decomposition from a Blueprint specification into a
draft `MANIFEST.md` build plan. It reads all Blueprint inputs, the ANALYSIS.md produced by
`drydock analyze`, and any questionnaire answers persisted in `BUILD_CONFIGURATION.md`. It writes
`BUILD_PLAN_COMPASS.md` (internal planning inventory) and `MANIFEST.md` (draft plan), then
generates the Target's QuarterDeck Planning Session.

A draft plan has no runnable frontier. QuarterDeck whole-plan approval exposes the frontier and
permits `drydock build` to proceed.

---

## Command Signature

```
drydock plan create <Blueprint> <Target>
```

---

## Hard Gates

The following must pass before the LLM decomposition runs:

1. `METADATA.md` exists in `<Blueprint>` — abort with exit code 1 if absent
2. `COMPASS.md` exists in `<Blueprint>` — abort with exit code 1 if absent; COMPASS is the
   product intent document and without it there is no basis for prioritizing the build
3. `init_plan_compass` runs and produces `BUILD_PLAN_COMPASS.md` — abort if it fails

If `ANALYSIS.md` is absent in `<Target>/QuarterDeck/planning/`:
- Warn: "Run `drydock analyze <Blueprint> <Target>` first. Proceeding without questionnaire
  gates."
- Continue with deterministic defaults (stack from METADATA.md, project type inferred from
  file inventory).

If `BUILD_CONFIGURATION.md` questionnaire answers are absent when `planning.json` had
`gate: plan_create` items:
- Warn: "Unanswered planning questionnaire gates. Run the QuarterDeck Planning Session to
  answer them before proceeding."
- Allow override with `--force` to proceed anyway.

---

## Algorithm

### Step 1 — Build Input Inventory (`init_plan_compass`)

Existing behavior: `init_plan_compass` scans the Blueprint directory, orders files per
BLUEPRINTS_CONTRACT, and writes `<Blueprint>/BUILD_PLAN_COMPASS.md`. This is the authoritative
ordered file list consumed by the rest of plan create.

`BUILD_PLAN_COMPASS.md` contains:
- Ordered list of all spec files to inject into the build plan
- Planning groups derived from file types (foundation, features, screens, etc.)
- Total estimated token count per group

### Step 2 — Read Configuration

Read `<Blueprint>/BUILD_CONFIGURATION.md` if present. This file stores durable PO decisions:

```
stack:          python, flask, postgresql
project_type:   web
[additional answers keyed by questionnaire question id]
```

If `stack:` is absent in BUILD_CONFIGURATION.md, fall back to `stack:` in `METADATA.md`.
If absent in both, proceed with no stack files and record `stack: unspecified` in MANIFEST header.

### Step 3 — Assemble LLM Context

Inject into the `plan_create.md` prompt:

| Content | Source |
|---|---|
| Blueprint spec files | Ordered per BUILD_PLAN_COMPASS.md |
| ANALYSIS.md | `<Target>/QuarterDeck/planning/ANALYSIS.md` (if present) |
| BUILD_CONFIGURATION.md | `<Blueprint>/BUILD_CONFIGURATION.md` (if present) |
| MANIFEST_CONTRACT.md | `prompts/MANIFEST_CONTRACT.md` |
| BLUEPRINTS_CONTRACT.md | `prompts/BLUEPRINTS_CONTRACT.md` |
| Rigging stack files | From declared stack — e.g. `Rigging/stack/python.md`, `flask.md` |

Context budget: respect `prompt_warn_kb` from config. If total context exceeds threshold,
prefer compact architecture variants (`ARCHITECTURE_FUNC_compact.md`,
`ARCHITECTURE_UI_compact.md`) over the full `ARCHITECTURE.md`.

### Step 4 — LLM Agile Decomposition

The `plan_create.md` prompt instructs the LLM to emit `MANIFEST.md` blocks. Full decomposition
rules are in the prompt; summarized here for specification reference:

**Foundation (always Phase 1):**
- `DATABASE.md` → one `story` block (id: `foundation`, no parent, depends nothing)
- Config / environment setup → stories under foundation if not part of DATABASE.md

**Project-type decomposition:**

| Project type | Feature unit | Story unit |
|---|---|---|
| `web` | Each `FEATURE-*.md` paired with its `SCREEN-*.md` → one `feature` block | Backend story (implements FEATURE-*.md) + UI story (implements SCREEN-*.md) under the same feature |
| `api` or `cli` | Each command or sub-verb from `AGENTS.md` Capabilities → one `feature` block | Stories per capability or command group |
| `library` | Each public API class or module → one `feature` block | Stories per class |
| `pipeline` | Each pipeline stage → one `feature` block | Stories per stage |

**Stories:** 1–4 per feature. Each story must be independently buildable. Prefer small units
that can be verified in isolation.

**Spikes:** One `spike` block per unresolved `## Open Questions` bullet collected by analyze.
A spike must precede any story whose `instructions` depend on the spike's finding.
Spike findings feed the story's `implements` or `instructions` via `depends:`.

**Acceptance checks:** 1–3 `ac` blocks per story.
- At least one `kind: smoke` — a shell command that verifies the story exists and starts
- At least one `kind: assertion` — a behavioral check (test file present, route responds, etc.)
- Prefer 2 AC per story: one smoke + one assertion. Add a third only for high-risk stories.
- AC blocks gate story closure: a story cannot close until all its child ACs are `closed/verified`

**Story fields required:**

```
id:           {slug}
parent:       {feature-id}
summary:      {one line}
implements:   {spec files}
context:      {read-only files}
stack:        {rigging stack files}
instructions: |
  {imperative build instructions — specific enough for an engineer to build from}
depends:      {space-separated prerequisite ids}
size:         {XS | S | M | L | XL}
state:        pending
evidence:     {Target}/evidence/{id}.md
scope:        blueprint | target | both
```

**Priority ordering (build phase assignment):**

| Phase | Content |
|---|---|
| 1 | Foundation: DATABASE.md, config, shared infrastructure |
| 2 | Core backend features: highest Provides count, lowest Depends On count |
| 3 | Dependent features: require Phase 2 outputs |
| 4+ | UI screens, secondary features, polish |

Spikes that block Phase 2 stories belong in Phase 1.

**Sizing guidance for LLM:**

| Size | Meaning |
|---|---|
| XS | Trivial: one file, one function, < 1 hour |
| S | Small: one module or class, a few hours |
| M | Medium: multiple files, half a day |
| L | Large: multiple modules, a day or more |
| XL | Epic-large: break into smaller stories if possible |

### Step 5 — Post-process and Validate

The module post-processes LLM output before writing:

1. Parse all emitted blocks from the LLM response
2. Validate:
   - All `id:` values are unique within the Manifest
   - All `depends:` ids reference blocks that exist
   - All `parent:` ids reference `feature` blocks that exist
   - All `state:` values are `pending`
   - All `implements:` filenames exist in the Blueprint directory
3. Compute `plan_hash` from content hashes of all injected spec files
4. Write MANIFEST.md with plan header (`state: draft`)
5. Update `SOUNDINGS.md` via `sync_plan_soundings`
6. Update QuarterDeck Planning Session via `render_console`

If validation fails, abort with exit code 1 and report the first validation error.

---

## Outputs

| Artifact | Location | State after plan create |
|---|---|---|
| `MANIFEST.md` | `<Target>/MANIFEST.md` | `state: draft` |
| `BUILD_PLAN_COMPASS.md` | `<Blueprint>/BUILD_PLAN_COMPASS.md` | Written by init_plan_compass |
| Soundings | `<Target>/SOUNDINGS.md` | Plan AC gates projected in |
| QuarterDeck | `<Target>/QuarterDeck/` | Planning Session configured |

---

## MANIFEST.md Plan Header

```markdown
# MANIFEST: {ProjectName}
updated:     {ISO timestamp}
plan_hash:   {12-char sha256 of spec file content hashes}
state:       draft
stack:       {declared stack or "unspecified"}
project_type: {web | api | cli | library | pipeline | event-driven}
```

---

## Incremental Builds

`drydock plan create` is a first-pass command. It produces the initial MANIFEST from a
Blueprint. After the baseline is approved and build begins, spec changes are applied
incrementally through `drydock refit` — which detects changed files, emits only the delta,
and preserves accepted work.

Re-running `drydock plan create` on an already-approved or partially-built plan overwrites
MANIFEST.md. The QuarterDeck will require re-approval. Use with caution post-baseline.

---

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | MANIFEST.md written successfully |
| `1` | Hard gate failed, validation error, or LLM execution error |
| `2` | Usage error (wrong arguments) |

---

## Acceptance Criteria

- `drydock plan create <Blueprint> <Target>` writes a valid MANIFEST.md with `state: draft`
- MANIFEST.md contains at least one story block for each authored FEATURE-*.md in the Blueprint
- Each story has `state: pending`, valid `id:`, valid `implements:`, and at least one child AC
- Each story has a `size: XS|S|M|L|XL` field
- All `depends:` ids resolve to existing block ids
- DATABASE.md (if present) produces a Phase 1 foundation story
- Spikes are created for each unresolved ## Open Question from the Blueprint
- MANIFEST.md `plan_hash` matches the content of injected spec files
- Soundings is updated with plan acceptance gates
- QuarterDeck Planning Session is created at `<Target>/QuarterDeck/`
- `drydock build status <Blueprint> <Target>` shows frontier as empty (no runnable work until approved)

## Guardrails

- Plan create must not modify any Blueprint spec file
- The LLM emits MANIFEST.md block text; the module writes the file — the model has no
  file-write permission
- `init_plan_compass` must run before the LLM is invoked
- Re-running plan create after baseline approval logs a Ship's Log warning
- Stack files from Rigging are injected into stories, not hard-coded in the prompt
- No API-key-backed LLM provider; use subscription-authenticated CLI adapter

## Open Questions

- None.
