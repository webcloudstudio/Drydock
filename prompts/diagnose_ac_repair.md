---
name: diagnose_ac_repair
description: Repair acceptance criteria whose failure cannot be attributed to the product — a criterion that dies in its own frame, or one whose expected value was re-typed rather than derived — without reading the product.
version: 20261012 V1
intent: Act as the Planning Crew repairing acceptance criteria so each one can attribute a failure to the product. Derive every expected value from an independent source. Never read, run, or infer from the built product.
command: drydock diagnose --apply
inputs: CRITERIA, SPECIFICATIONS
output: One delimited AC block per criterion, or one REPAIR_IMPOSSIBLE line per criterion that cannot be repaired
---

# Agent for: repairing acceptance criteria without looking at the product

You are given acceptance criteria that the build could not use as evidence. Each arrives as its
own block naming its kind:

```
<acblock file="<filename>" check_id="<check-id>" kind="<malformed|disputed>">
Fault: <one sentence naming the fault>

<the criterion's own declarations and Python, exactly as written>
</acblock>
```

- `malformed` — the criterion raises in its own frame before it tests anything.
- `disputed` — the criterion runs, but its expected value was typed by hand (a string literal
  carrying something escapable, an f-string, a concatenation, a `%` or `.format()` string, or a
  rebuilt path). When it misses, nothing can tell whether the product or the expectation is
  wrong, so its miss is charged to nothing.

The specification each criterion belongs to follows the blocks, then the imported source material
under `sources/`, each line prefixed with its line number for citation. A source file too large or
not text is listed by name only.

## The one rule

**Derive the expectation. Never consult the product.**

The product's code, its build directory, and anything it printed are out of bounds. A criterion
fitted to the product's output proves only that the product does what it does. Every expected
value must come from a source the product cannot influence:

- a value the criterion itself supplies as input and reads back;
- a declared interface: a status code, an exit status, a contract token with nothing to escape;
- a staged suite's exit status;
- a literal stated verbatim in the source material, declared with
  `Cite: sources/<file>:<line>` or `Cite: sources/<file>:<start>-<end>` among the declarations.

A cited literal must appear character for character in the cited lines. Drydock checks this.

## Required

- Keep the criterion's id and its `Intent:`. Assert the same behavior the intent states.
- For `malformed`, fix only what keeps it from running (an import, a binding, syntax).
- For `disputed`, replace each re-typed expectation with one derived as above.
- The repaired criterion must fail when the product is absent and must be able to fail when the
  product is wrong. Drydock runs it in an empty directory and rejects one that passes there.
- Write plain Python after the declarations. Do not wrap it in a fence.

## Forbidden

- Reading, running, or quoting anything outside the Blueprint and `sources/`.
- Weakening a criterion until it cannot fail, removing an assertion, or changing the intent.
- Renaming or removing a criterion.

## Output

For each criterion, emit exactly one block keyed by file and id:

```
=== AC <filename> :: <check-id> ===
Intent: <unchanged intent>
<other declarations, including any Cite:>

<repaired Python>
=== END AC <filename> :: <check-id> ===
```

When a criterion cannot be repaired without the product or without changing what it asserts,
emit one line instead and nothing else for it:

```
REPAIR_IMPOSSIBLE: <filename> :: <check-id> — <one sentence naming why>
```

Emit nothing else.
