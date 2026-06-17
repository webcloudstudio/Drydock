# ARCHIVE: analyze
Archived from notes_analyze.md

### What analyze reads
`2026-06-14` · `spec:applied` · `impl:implemented`

`drydock analyze` reads the **imported source files** from `blueprint/sources/` only.
Top-level typed spec template files (`ARCHITECTURE.md`, `FEATURE-*.md`, etc.) in `blueprint/`
are NOT injected — they are empty at analyze time and are outputs of `plan create`, not inputs.

Multiple imports are supported: each `drydock import` lands files in `blueprint/sources/`
alongside prior imports. `analyze` reads all `.md` files under `blueprint/sources/` recursively.

This may be extended in a future session to also include hand-written top-level spec files.

---

### Two Decomposition Passes at Different Altitudes
`2026-06-14` · `spec:applied` · `impl:implemented`

- **`analyze` (Sprint Planning Part 1):** reads imported material. Derives the story list at
  title + high-level AC level. Surfaces spikes and blockers. Output: story list + questions.
  Does NOT write typed spec files into `blueprint/`.
- **`plan create` (Sprint Planning Part 2):** reads the story list + imported spec. Decomposes
  each story into typed specification files (`FEATURE-*.md`, `SCREEN-*.md`, etc.) that the
  build can execute against.

`drydock approve` is retired. Running `plan create` is the gate; Quality=Ready is the signal.

---

### Analyze Output Files
`2026-06-14` · `spec:applied` · `impl:implemented`

All written by `drydock analyze`. Read-only w.r.t. `blueprint/` spec files,
`BUILD_CONFIGURATION.md`, and `MANIFEST.md`.

#### ANALYSIS.md (target root)

The primary human-readable artifact. Format:

```
# Blueprint Analysis: <ProjectName>
generated: <date>
blueprint: <path>

## Analysis Summary

Quality: [ Ready | Questions | Blocked ]
  N blockers identified
  N questions surfaced
  N feature stories derived
  architecture stack: <declared stack or "not declared">
  N user interface screens found

## Open Questions
- [file or area] question text
...

## Story List
<Tables of story titles — no prescribed grouping, LLM organizes as appropriate>
<Tuning options offered to the PO>

## Blockers
<If any — explicit list with reason>

## Notes
<Non-conformant headers, ambiguous signals, observations>
```

Story list is titles only at this stage. Tuning options are recommendations the PO can
accept or override (e.g., decomposition approach, batch order, spike scheduling).

#### SEA_TRIALS.md (target root)

Strategic objectives at product level. Derived from decomposition + COMPASS.
3–7 rows typical.

```
| ID | Objective / Success Criterion | State | Evidence |
```

#### SOUNDINGS.md (target root)

Acceptance milestones derived from decomposition. One row per feature area (future
`FEATURE-*.md`), one row per screen (future `SCREEN-*.md`), a few rows per
database/persistence area. LLM makes up the milestones from the project shape.

```
| ID | Acceptance Criterion | State | Evidence |
```

#### COMPASS.md (target root, conditional)

Written when: (a) file does not exist, or (b) file exists but is an unpopulated template
(detected by HTML comment placeholders `<!--` or all-`- None.` sections).

Derived from all available spec material. Standard sections: Compass, Constraints,
Success Criteria, Acceptance Criteria, Guardrails, Open Questions.

#### spike-*.json (QuarterDeck/questionnaires/)

Fixed questionnaires emitted: `spike-intent.json`, `spike-stack.json`, `spike-guardrails.json`.
(`spike-gaps-ac.json` removed 2026-06-16 — see §Spike set: gaps/AC spike removed.)

Variable spikes for genuine unknowns only (not generic catch-alls), and only for human-owned
decisions (the Ownership test).

**Technology questionnaires** must offer concrete Rigging-derived options for the detected
project type. Example — Python web server: `flask`, `django`, `fastapi`, `other`.
"Other" includes instructions pointing to the relevant Rigging document.
Rigging stack guidance files are injected into the prompt based on detected project type.
Rigging stack files are trivial to create (one-line "best practices" prompt generates them).

#### Captain's Chair (QuarterDeck/)

Analyze fills a template with variables — not a custom write. Template lives in Rigging.
Variables injected: quality signal, story count, question count, blocker count, stack,
next recommended step, project name.

Format: self-contained HTML with embedded styles (`captains_chair.html`). QuarterDeck
registers it as a `document` item with `path_html`; renders in an 80vh iframe. The LLM
fills a Rigging HTML template with variables (quality, counts, stack, next step). No external
CSS dependency — file must be self-contained.

---

### Lifecycle State Persistence
`2026-06-14` · `spec:applied` · `impl:implemented`

Lifecycle state tracked in `METADATA.md` at the **target root** via field: `drydock build state:`.

State ladder (forward-only): `init → analyzed → planned → building → built`

Each command:
1. Reads `drydock build state:` from target-root `METADATA.md`.
2. If the new state is not forward, skips the Captain's Chair overwrite.
3. On success, updates `drydock build state:` and writes the Captain's Chair.

The Captain's Chair is write-only from commands — display artifact, never read back.

---

### Roles
`2026-06-13` · `spec:na` · `impl:implemented`

- **Product Owner** owns Intent (what to build, guardrails, AC) and Decisions (answers, route).
- **LLM (Scrum team)** owns decomposition, proposed edges, recommendations. Proposes; never ratifies.
- Questions are written in product-owner English — answerable by a non-technical PO, precise
  enough for a senior one. A genuine unknown the PO cannot answer becomes a spike.

---

### The Checklist (Embedded in Prompt)
`2026-06-13` · `spec:na` · `impl:implemented`

`analyze` runs a checklist over the spec (stack chosen? persistence defined? auth named?
success criteria present? AC present per objective? …). One unmet item → one question.
Embedded in the `analyze` prompt body, not a separate Rigging file.

---

### Console Actions = CLI Commands
`2026-06-13` · `spec:na` · `impl:implemented`

Every console action maps to a `drydock` verb; console is a thin GUI over the command surface.

- `drydock approve` — RETIRED 2026-06-14. Running `plan create` is the gate.
- QuarterDeck is optional — full pipeline must be drivable via CLI without the console.

---

## V5 Hardening — Prompt & Pipeline Correctness

Task cluster from the 2026-06-15 review of `prompts/analyze.md` against `src/drydock/analyze.py`.
Each section below is one task. `impl:unimplemented` = ready for `/apply-notes analyze`.

### Spike set: gaps/AC spike removed
`2026-06-16` · `spec:applied` · `impl:implemented`

`prompts/analyze.md` V6 (committed this session) drops the `spike-gaps-ac` questionnaire and adds
the Ownership test: a spike asks only a human-owned decision; acceptance criteria, success
evidence, smoke checks, build gates, and test sequences are synthesized outputs, not spikes. The
"four fixed spikes" model (§Analyze Output Files; notes_quarterdeck §Analyze Output Contract /
Spike Contract) is superseded — fixed set is now intent, stack, guardrails.

---

## Acceptance Criteria

1. No requirement silently invented: every gap/fork surfaces as a PO question.
2. Source of truth holds: Intent + Decisions regenerate every derived artifact.
3. `analyze` writes only planning artifacts. Read-only w.r.t. blueprint spec files and MANIFEST.
4. Story list is atomic-story level, with high-level AC per story.
5. Re-runs are deterministic given the same Intent + Decisions.
6. ~100-story cap respected or tool refuses with a clear message.
7. Quality=Ready means no blockers; plan create can proceed.
8. Blockers are explicitly flagged and distinct from questions.
9. Technology questionnaires offer concrete Rigging-derived options.
10. `drydock build state:` in METADATA.md advances forward-only.
11. Captain's Chair is template-filled, not custom-written.
12. COMPASS is written when absent or unpopulated (template detection by `<!--` or all-None.).
13. After `import` + `analyze`, `blueprint/` contains only `sources/`; no typed-spec stubs (BUG-7).
14. `analyze` prints the list of artifact filenames it created (FIX-8).
15. `spike-stack.json` options are stack-catalog filenames for the detected type; analyze never
    reads the per-technology stack files (FIX-5).
16. Checklist and project-type detection operate on imported source content only; no typed-spec
    file other than COMPASS is ever an analyze input (FIX-6).

---

## Guardrails

- **LLM never ratifies.** `analyze` must not write to `BUILD_CONFIGURATION.md`, `MANIFEST.md`,
  or any blueprint spec file.
- **No cross-stack batches.** A build batch must never mix component types / stacks.
- **One spec per story.** A story implements exactly one spec file. Enforced at `plan create`.
- **~100-story cap.** Over the threshold the tool refuses.
- **Forward-only state.** Commands do not overwrite Captain's Chair if state would go backwards.
- **Derived artifacts must be regenerable.** Rogue source of truth = drift.
- **QuarterDeck is optional.** Full pipeline drivable via CLI.
- **Fixed I/O locations (Ed, 2026-06-15).** Files never go to the wrong location.
  - `analyze`: reads `blueprint/sources/` → writes **target root** (`/`). The root planning
    artifacts (`ANALYSIS.md`, `SEA_TRIALS.md`, `SOUNDINGS.md`, `COMPASS.md`) are the "plan" — they
    live at root because they need review. QuarterDeck surfaces them by known filename via its
    config-file translation (already handled; do not re-engineer). `analyze` writes nothing to
    `blueprint/`.
  - `plan create`: reads **target root** (`/`) + `blueprint/sources/` → writes `blueprint/`
    (typed spec files).

---

## Open Questions

1. **Re-analyze: diff vs regenerate** — does a re-run highlight what changed from the previous
   `ANALYSIS.md`, or simply regenerate clean?
2. **Integrity failure UX** — block `MANIFEST.md` write only, surface as questions, or both?
3. **Drift propagation model** — how green/stale propagates when an upstream node changes post-build.
4. **Captain's Chair template** — structure and variables to be defined; create Rigging HTML template.

---

## Not in scope yet

Building `plan create`. Editing the canonical specification (reconcile after design stabilizes).

**Spec-diff as change ticket (future):** spec file changes between git commits = delta work items.
Drydock could detect spec diffs and surface them without a full re-analyze.
