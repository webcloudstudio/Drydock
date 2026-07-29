# Branding — Project Specification Documents

**Version:** 20260729 V1
**Category:** Branding
**Description:** The author's voice, structure, and editing protocol for a project's authoritative
specification document — the single normative artifact that defines what a product does.

Inherits nothing. This file governs the specification document itself, not the generated
documentation site (`BRANDING_DOCUMENTATION.md`) or long-form prose (`BRANDING_WHITEPAPERS.md`).
The reference implementation of this voice is `docs/Drydock_Specification.md`.

---

## What This Document Is

A project specification is a **user-facing contract**, not internal documentation. It states what
the product does, in what syntax, producing what files, with what exit codes. It is precise on
syntax and on high-level activity. It does not explain how the implementation works.

The reader is a senior technical practitioner. Assume competence. Do not teach shell, Git, LLM,
or programming concepts.

---

## Editing Protocol — Authority Sits With the Author

The specification is written in the author's voice. An agent cannot reproduce that voice and must
not try.

**An agent may, without asking:**

- Correct a CLI syntax line in a `### Commands` block or a command's synopsis when the code's actual
  argument surface has changed. The synopsis must match the parser.
- Add **one line** describing a new argument: what it does, in the existing style. One sentence.

**An agent must obtain explicit, per-edit approval for everything else** — new sections, rewritten
paragraphs, restructured tables, changed terminology, deleted content, or "improvements" to phrasing.
Approval for one block is not approval for the next.

**An agent must never** wholesale-replace a section, reflow prose it was not asked to touch, or
normalize the author's spacing and punctuation habits. When the document and the implementation
disagree, surface the conflict and let the author decide which one is wrong.

---

## Voice

**Present tense, declarative, third person.** The subject is the command or the artifact, and it
acts.

> `drydock build status` reads `MANIFEST.md` and the runtime logs and reports the state of the plan.

> `MANIFEST.md` is created by `drydock plan` and can be modified in the QuarterDeck.

No future tense. No conditional. No first person. No second person except when addressing the
operator directly in an instruction.

**Normative statements only.** The document says what is, never what was, might be, or is planned.
Prohibited: rationale, reasoning, open questions, status, history, alternatives considered, and all
hedging — "we could", "should probably", "might", "plan to", "in the future", "currently".

**Terse to the point of severity.** Sentences carry one fact. Adjacent facts become adjacent
sentences rather than a compound sentence with a conjunction.

> `drydock score ac` verifies acceptance deterministically, with no LLM call by running the
> acceptance criterion. It writes the blueprint acceptance criteria to SOUNDINGS.md with a status of
> `✓ PASS`, `✗ FAIL`, or `— UNVERIFIED` and a timestamp. `drydock score ac` is deterministic.

Repetition for emphasis is deliberate. A flat restatement at the end of a paragraph is a period at
the end of an argument, not an accident.

**No salesmanship and no transitions.** There is no "Now that we have covered", no "It is important
to note", no "In this section we will". Sections begin with the fact.

**Domain metaphor is load-bearing, never decorative.** Drydock's nautical vocabulary — Commander,
Blueprint, Manifest, Rigging, QuarterDeck, Sea Trials, Soundings, Compass, Refit, frontier — names
real artifacts and real roles. Each term maps to a file, a command, or a person. Never introduce a
metaphor that does not name something concrete, and never use a metaphor in place of a definition.

---

## Structure

### Defining a term

Bold lead-in, then the definition as a complete sentence. The term is defined once, at first use,
and used unqualified thereafter.

```markdown
**The Commander.** Drydock addresses its operator as the Commander. The Commander owns the product
direction, reviews the work, and approves decisions in the QuarterDeck.
```

### Command entries

Every command section uses this exact order, with no added, reordered, or omitted sections:

1. **CLI syntax** — a fenced ` ```text ` block containing the synopsis, one invocation form per
   line. Optional arguments in `[square brackets]`, required placeholders in `<angle brackets>`,
   enumerated choices as `<auto|markdown|source>`. A trailing `#` comment on a synopsis line is
   permitted when it distinguishes two forms.
2. **Behavior description** — prose. What the command reads, what it decides, what it writes.
3. **Input files** — a table.
4. **Output files** — a table.
5. **Exit codes** — a table.

One section per command. Duplicate or overlapping command headings are defects to be fixed, not
tolerated.

### Tables

Tables carry all structured facts. Prose never enumerates what a table can hold.

Input and output tables use three columns and a tight separator:

```markdown
| Artifact | Location | Purpose |
|---|---|---|
| `MANIFEST.md` | Target root | The executable build plan |
```

Exit-code tables right-align the code column:

```markdown
| Code | Meaning |
|---:|---|
| `0` | Scoring completes successfully |
| `1` | Scoring cannot complete or the Target does not satisfy the evaluated gate |
| `2` | Command syntax is invalid |
```

Exit-code meanings are stated as conditions, not as advice to the user.

### Capability lists

Feature and capability inventories are bold-headed groups of bare bullets. Bullets are fragments,
not sentences, and carry no terminal period. Density is the point — the reader is scanning.

```markdown
**Governance**
- `drydock analyze` is Story Planning and surfaces any gaps
- EARS acceptance criteria, grammar-validated.
- Sealed foundational specifications require a change ticket to alter.
```

### Diagrams

Mermaid `flowchart LR` with an explicit `%%{init: ...}%%` neutral theme and named `classDef` styles
for each artifact kind (directory, markdown, script, prompt, output, web). Diagrams illustrate flow
between named artifacts. A diagram never introduces a concept the prose has not already defined.

### Callouts

A `>` blockquote marks a single load-bearing constraint the reader must not miss. Used sparingly —
roughly once per phase. Never used for asides or commentary.

---

## Formatting Conventions

- Backticks on every command, filename, artifact, flag, and literal value. `MANIFEST.md`,
  `drydock plan`, `--dry-run`, `✓ PASS`. This is absolute.
- Artifact filenames are SCREAMING_SNAKE with the `.md` suffix: `SEA_TRIALS.md`, `PLAN_COMPASS.md`.
  Typed Specification files use `FEATURE-{Name}.md` and `SCREEN-{Name}.md`.
- Status glyphs are used literally in text: `✓ PASS`, `✗ FAIL`, `— UNVERIFIED`.
- Headings: `##` for phases, `###` for commands and major subsections. Phase headings carry an em
  dash and a named subtitle — `## SAIL Phase 3 — Implement: Sailing the Frontier`.
- Bold is for term definitions and inline field labels only. Never for emphasis inside a sentence.
- Do not normalize the author's whitespace. Double spaces after a sentence and occasional trailing
  spaces are the author's typing, not errors to be cleaned up in an unrelated edit.

---

## Prohibited

- Explaining implementation mechanics, module names, or internal call flow.
- Rationale, tradeoffs, alternatives, or design history.
- Status language: "not yet implemented", "coming soon", "deferred", "TODO".
- Marketing register: "powerful", "seamless", "robust", "simply", "just", "easy".
- Instructional scaffolding: "Let's", "Now we", "As you can see", "Note that".
- Restating a section's contents in a summary paragraph at its end.
- Emoji outside the literal status glyphs.
- Any reference to the assistant, model, or provider that produced an edit.
