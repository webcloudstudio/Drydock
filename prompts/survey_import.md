---
name: survey_import
description: Read a Blueprint or sources directory and generate per-command Surveyor acceptance-criteria files.
version: 20260622 V2
intent: Derive one SURVEY-<command>.md acceptance-criteria file per command or capability found in the specification, each with a distilled goal, code AC, spec AC, guardrails, and open questions.
command: drydock survey
model: opus
output: SURVEY-<command>.md acceptance-criteria files
---

# Surveyor — Generate Acceptance Criteria From A Specification

You are given the specification files for a target. Identify each command or capability the
specification defines, and produce one acceptance-criteria file per command, in the Surveyor AC
format. These files become the standard the build is later scored against — author them as the
quality bar, not as a description of current behavior.

## What to produce per command

For each command/capability, emit a file with:

- An H1 `# SURVEY-SPEC: <command>` and a short header table (Version, Description, Command).
- A `## Goal` — one distilled paragraph: what success means for this command.
- `## Acceptance Criteria — Code` — a table of behavioral AC.
- `## Acceptance Criteria — Specification` — a table of artifact/spec-quality AC.
- `## Guardrails` — MUST NOT statements.
- `## Questions` — genuine unknowns; never resolve one silently.

Each AC table row has columns: `ID | Criterion | Dim | Check | Weight | Verify`.
- `ID`: `<COMMAND>-<n>` (e.g. `STATUS-C1`), unique within the file.
- `Dim`: one of `D1` (behavioral), `D2` (spec quality), `D3` (process integrity),
  `D4` (evidence/reproducibility), `D5` (contract conformance).
- `Check`: `A` (assertion — mechanically checkable, preferred) or `J` (judgment — LLM).
- `Weight`: 1–3 by importance.
- `Verify`: how to check it — a command, a file test, or a method. Prefer assertions.

Target 3–7 AC per command across both tables. Favor assertions over judgments.

## Output format

Emit each file delimited exactly so, and **nothing else** — no preamble, no explanation, no commentary, no tool calls, no `<invoke>` or `<function_calls>` XML. Any output outside a delimited block is a protocol violation and will cause the run to fail. Start your response with the first `=== BEGIN ARTIFACT SURVEY-... ===` block. The name is typed once, at the open; every block is closed by the constant token `=== END ARTIFACT ===`.

```
=== BEGIN ARTIFACT SURVEY-<command>.md ===
# SURVEY-SPEC: <command>
...full file body...
=== END ARTIFACT ===
```

Use a lowercase, hyphenated `<command>` slug in the filename (e.g. `SURVEY-plan-create.md`).
The source specification files follow below.
