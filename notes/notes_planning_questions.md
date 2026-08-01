# NOTES: Planning Questions

| Field | Value |
|-------|-------|
| Version | 2026-07-31 V1 |
| Route | analyze, plan, build, QuarterDeck |
| Status | Working notes — not canonical specification |
| Description | Deterministic story-question capture, persistence, replanning, display, and build gating. |
| Pending spec | 0 approved items |
| Pending impl | 0 unimplemented sections |

## Goal

Allow Analyze and Plan to surface human-owned unknowns without blocking unrelated Agile stories,
persist substantive answers across replanning and Blueprint renames, and expose the complete workflow
in QuarterDeck.

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
