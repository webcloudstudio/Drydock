---
name: plan_continue
description: Stage 2 Blueprint authoring instruction appended after plan_create has accepted and frozen a complete TOPOLOGY.md declaration.
version: 20261027 V11
intent: Author one bounded batch of Blueprint specifications from the frozen topology, closing each artifact before opening the next.
command: drydock plan create
output: A bounded batch of Blueprint specification files
---

# Continuation

Stage 1 is complete. Drydock accepted and froze the complete `TOPOLOGY.md` declaration before
starting this Blueprint-authoring stage. The full planning context above remains authoritative.

The ledger below states exactly what Drydock accepted, what is still missing, and what came back
defective. Treat it as fact.
This batch starts a new session. Earlier Blueprint responses and reasoning are not available.
Use the frozen topology, decisions, ledger, and `DATABASE_compact.md` or the `DATABASE.md` seed
when supplied.

## Your job

Emit **exactly** the artifacts in the ledger's **Current batch**, in the stated order. Nothing else.

- Do not re-emit an accepted artifact. Drydock retains its content.
- Within this response, a complete replacement block for the same filename updates its earlier
  draft. The last block receives normal validation; a partial replacement is not accepted.
- `DATABASE.md` is authored in its own batch, complete, and then frozen. When it is the Current
  batch, start from the supplied seed and declare every table and every repository operation the
  frozen topology's stories need. After it is accepted, later batches receive it as
  `DATABASE_compact.md`; cite its access patterns and never emit `DATABASE.md` again.
- Do not emit a deferred artifact. Drydock supplies it in a later bounded batch.
- Do not emit or amend `TOPOLOGY.md`; Stage 1 is complete and frozen.
- Do not emit `DECISIONS.json`; it was captured with the topology in Stage 1.
- Do not restate your plan, summarize progress, apologize, or explain the interruption.
- You have no tools and nobody answers questions during planning. Never ask a question,
  request a file, or offer options. Record each open point under the affected Blueprint's
  `## Questions` and emit the batch. Prose reaches no one: a response without artifacts is
  rejected and the same batch is asked again.
- A Current-batch Blueprint you genuinely cannot author is reported in `BLUEPRINT_BLOCKED.txt`
  (see Blocked Blueprints), and the rest of the batch is still emitted.
- Do not emit `MANIFEST.md`; Drydock serializes it from the declaration.
- Use exactly the same delimited block format as before, including the mandatory
  `=== END ARTIFACT ===` line for every file. The name is typed once, at the open; the
  closing delimiter is that constant token and never carries the name.
- An artifact listed as defective must be emitted again in full, corrected. A partial or patched
  version is not accepted.
- Emit each missing artifact under the exact filename the ledger names. A filename that does not
  match its declaration cannot be accepted.
- Each typed Blueprint includes `## Programmatic Acceptance`, `## User Acceptance`, and
  `## Guardrails`, in that order. Preserve applicable source constraints under Guardrails;
  use `- None.` only when User Acceptance or Guardrails has no applicable content.
- Compute numeric expectations from fixture inputs using the source formula and rounding;
  never guess formatted decimal answers. Put Requires declarations inside each AC block.
  Before returning, count the open and close artifact lines; counts match, and the final nonblank
  line is exactly `=== END ARTIFACT ===`, including its trailing equals signs.
  Derive ordered expectations from fixture inputs and declared sort keys, including tie breakers.
  Import every referenced name inside each AC, declare every external import and test transport,
  and use a bounded endpoint/port readiness probe for server-start criteria.
  Cite only owned or shared database patterns and derive their DTO fields from DATABASE.md.
- Acceptance observes the delivered application through its declared interfaces. Never replace
  it with a local implementation or a standalone language expression inside the criterion.
  For a Go CLI report criterion, use `drydock_go.cli_runner`, assert its exit code, parse its CSV output, and
  compare the observed fields with expectations derived from the supplied fixture inputs.
  The application need not exist during planning; author its invocation for Build to execute.
- A story's criteria exercise only capabilities available in its own build block or earlier.
  Follow the frozen topology's Provides and dependency order. Test lower-level functions through
  their own interfaces; for Go use drydock_go.run_test with an exact native test name. Keep CLI
  integration criteria on a later story after every command they invoke exists. A filter story
  that precedes report implementations tests filtering directly; the later reports also verify
  the filters through their CLI output. Never replace product execution with a local substitute,
  drop end-to-end coverage, or introduce a dependency cycle to make an early gate pass.

## Acceptance authoring review

For each criterion, identify the delivered interface, required setup, source-derived expectation
and failure diagnostics before writing code. Keep imports and tooling declarations inside the
criterion. Close it with `=== END AC <id> ===`; that token never closes an artifact.

For staged corpus checks, follow `BLUEPRINTS_CONTRACT.md`: declare `Suite: scoped`, a supported
listing `Probe:` and its `Probe Count:` protocol. Use literal runner arguments or literal string
bindings, including the product and corpus paths. With `import os`, canonical
`os.path.abspath("program")` is also supported. Do not construct probe arguments with getcwd
f-strings, dynamic imports or runtime expressions. Drydock runs listing probes; you author them
without tools and never invent counts. Print captured output before asserting the runner's exit.

A nonempty listing proves selection, not prerequisite availability. Inspect the selected cases
in the supplied source: a section name can include interactions with capabilities scheduled later.
Preserve the current batch obligations repeated in the ledger, especially instructions assigning
cross-feature cases to a later integration. Do not turn a whole section into an early gate merely
because its title matches the story. Select only the supported cases using documented runner
options. If the runner cannot express that boundary, test this story's own interface directly
without copying corpus examples, and run the mixed section on a later integration after all its
required capabilities exist. Keep every deferred case covered there before the terminal gate.
Never make the earlier story implement the later feature or introduce a dependency cycle.

The frozen topology is the availability contract. A criterion must not require an undeclared
later capability merely because the same executable eventually exposes it. Author direct checks
for this story's interface and preserve cross-feature coverage on its declared integration story.

## Blocked Blueprints

Report a Blueprint only when its inputs contradict each other, or do not define the behavior it
must specify, and no reasonable assumption recorded under `## Questions` can bridge the gap.
Never report: having no tools, response length, accepted Blueprints being absent from this
context (author against the frozen topology's `Provides` lines), or an input that is present
above. Drydock checks every claim against this context and returns its finding to the next batch
as `Prior run error type` and `Prior run error details`. Answer each refuted claim by authoring the
Blueprint.

Emit one `BLUEPRINT_BLOCKED.txt` block after the Blueprints you did author, with one entry per
blocked Blueprint:

```text
=== BEGIN ARTIFACT BLUEPRINT_BLOCKED.txt ===
Blueprint: {Current-batch filename}
Error type: {missing-input|conflict|insufficient-specification|other}
Cited input: {exact input file and section}
Details:
- {what the cited input says or lacks, and why it blocks this Blueprint}
Required action:
- {the product decision or source correction that unblocks it}
=== END ARTIFACT ===
```

## Budget

Author the Current batch one Blueprint at a time. For each Blueprint, emit its opening delimiter,
its complete file body, and its matching closing delimiter. Only after the closing delimiter is
written may the next Blueprint's opening delimiter be emitted.

A whole artifact is progress; a truncated one is not. Never pre-emit opening delimiters, outline
several files at once, nest one artifact inside another, or use one closing delimiter for several
files. If the whole Current batch cannot fit, finish and close the current artifact, then end the
response. Drydock retries every unproduced artifact from the same batch.

The only legal sequence is:

```text
=== BEGIN ARTIFACT FIRST-NAME ===
{complete first file}
=== END ARTIFACT ===
=== BEGIN ARTIFACT SECOND-NAME ===
{complete second file}
=== END ARTIFACT ===
```
