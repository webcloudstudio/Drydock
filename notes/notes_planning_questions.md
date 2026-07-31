# NOTES: Planning Questions

| Field | Value |
|-------|-------|
| Version | 2026-07-31 V1 |
| Route | analyze, plan, build, QuarterDeck |
| Status | Working notes — not canonical specification |
| Description | Deterministic story-question capture, persistence, replanning, display, and build gating. |
| Pending spec | 6 approved items |
| Pending impl | 6 unimplemented sections |

## Goal

Allow Analyze and Plan to surface human-owned unknowns without blocking unrelated Agile stories,
persist substantive answers across replanning and Blueprint renames, and expose the complete workflow
in QuarterDeck.

## Decisions

### Canonical Questions section
`2026-07-31` · `spec:approved` · `impl:unimplemented`

Every question-bearing Markdown artifact uses the exact heading `## Questions`. Alternate structural
headings such as `## Open Questions`, `## Question`, and bare `QUESTIONS:` are invalid. In a Typed
Blueprint, `## Questions` is the first `##` section after the title and typed metadata table. The
section remains present when empty and contains `- None.`.

Each question uses a deterministic, human-readable record:

```markdown
## Questions

### Q-001: State Changer

- Origin: plan
- Status: open

#### Question

Which state model governs this workflow?

#### Answer
```

Origins include `plan` and `analyze-questionnaire`. Status values include `open` and `answered`.
An answered record requires a non-empty answer. Sea Trials uses the same section syntax.

### Story-local build gate
`2026-07-31` · `spec:approved` · `impl:unimplemented`

An open Blueprint question marks the owning Manifest story `Blocked Questions`. The story and its
transitive dependents are not buildable. Independent frontier stories remain buildable. Answering
every question automatically ungates the story; no additional approval is required.

The Manifest clearly projects question counts and the `Blocked Questions` state. A Commander may
approve an unanswered story in the current Manifest. That approval ungates the current plan but is
not a substantive answer and does not survive Manifest replacement or feed a future Plan run.

### QuarterDeck question editing
`2026-07-31` · `spec:approved` · `impl:unimplemented`

QuarterDeck groups Build Questions by Blueprint and provides an answer textarea and Save action for
each question, in addition to full Blueprint editing. Saving writes directly to the Blueprint,
changes the question to `Status: answered`, preserves its stable ID, origin, and text, and dirties the
Blueprint normally.

QuarterDeck also exposes the persistent Plan Feedback artifact. When the originating Blueprint
exists, the persistent record is read-only and the Blueprint question interface owns editing. When
the originating Blueprint no longer exists, QuarterDeck may edit the persistent record directly.

### Persistent Plan feedback
`2026-07-31` · `spec:approved` · `impl:unimplemented`

A substantive answer is promoted into a persistent Plan feedback store. The durable decision has a
stable semantic identity independent of Blueprint filenames and story decomposition. A source
Blueprint path is provenance only.

The record retains the stable decision ID, origin, semantic subject, original question, answer,
answer timestamp, source Blueprint provenance, and current disposition. The Blueprint is the
authority while it exists; the feedback store preserves continuity across Blueprint replacement.

### Replan decision realization
`2026-07-31` · `spec:approved` · `impl:unimplemented`

Before replacing Blueprints, Plan harvests answered Blueprint questions into persistent feedback and
injects all active feedback into the Plan prompt. A resolved decision is written into normal Blueprint
content, not reproduced under `## Questions`.

Plan classifies every injected decision as `applied`, `retained`, or `retired`. Applied decisions name
their current realization. Retained decisions remain future Plan feedback. Plan may retire a decision
only because a product scope change makes it irrelevant, and it records the reason. Missing, renamed,
split, merged, or replaced Blueprint files never justify retirement.

The Manifest records the current run's feedback disposition and realization without becoming the
authoritative decision store.

### Analyze-to-Plan closure
`2026-07-31` · `spec:approved` · `impl:unimplemented`

Analyze questionnaires remain persistent pre-Plan human-decision sources. Plan consumes their answers
and creates the owning Blueprint with the decision applied to normal specification content. Provenance
is retained in persistent Plan feedback.

When additional human-owned unknowns arise during Blueprint creation, Plan emits them under the owning
Blueprint's `## Questions` section instead of deferring the entire Plan. Only a question that prevents
coherent story decomposition may stop Plan before Blueprints exist.

## Acceptance Criteria

- Every generated Typed Blueprint and Sea Trials artifact uses the canonical `## Questions` syntax.
- Structural question parsing is deterministic and rejects alternate headings in governed artifacts.
- An open question blocks only its owning story and transitive dependents.
- QuarterDeck answers are written to the owning artifact and automatically remove its question gate.
- Current-Manifest approval ungates without creating durable Plan feedback.
- Answered decisions survive Blueprint filename and decomposition changes.
- Replan applies answered decisions to normal specification content and never silently discards them.
- Analyze questionnaire answers enter the same persistent Plan feedback lifecycle.

## Guardrails

- Do not use Blueprint filenames as durable decision identity.
- Do not treat Manifest approval as an answer.
- Do not retire feedback because a file was renamed or replaced.
- Do not block unrelated frontier stories because another story has open questions.
- Do not silently discard answered questions during replanning.
- Do not maintain competing editable copies of an answer.

## Open Questions

- None.

## Not in scope yet

- General-purpose ticket or workflow management beyond planning questions.
- Automatic resolution of questions without a Commander answer.
