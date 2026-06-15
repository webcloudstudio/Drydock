# Blueprint Analysis: Drydock
generated: 2026-06-14
blueprint: /mnt/c/Users/barlo/projects/Drydock/targets/Drydock/blueprint

## Project Summary
Drydock is a specification-driven software design and delivery methodology. The Blueprint
currently consists almost entirely of unpopulated template stubs; no `METADATA.md` is present, so
name, description, and stack cannot be read from the canonical source. COMPASS.md contains a
single free-text charter sentence rather than the typed methodology spec.

## Project Type
type: web
SCREEN-Example.md is present and both SCREEN and ARCHITECTURE declare HTTP routes (`GET /example`,
`GET /`), the defining signals for `web`.

## Dependency Graph
| File | Type | Depends On | Provides | Phase |
|------|------|------------|----------|-------|
| ARCHITECTURE.md | ARCHITECTURE | — | — | — |
| DATABASE.md | DATABASE | — | — | — |
| FEATURE-Example.md | FEATURE | — | — | — |
| HOMEPAGE.md | HOMEPAGE | — | — | — |
| SCREEN-Example.md | SCREEN | — | — | — |
| UI.md | UI-GENERAL | — | — | — |
| UI-Component-Example.md | UI-GENERAL | — | — | — |
| COMPASS.md | COMPASS (non-conformant) | — | — | — |
| ACCEPTANCE_CRITERIA.md | non-conformant | — | — | — |

## Coverage Assessment
| Check | Status | Notes |
|-------|--------|-------|
| METADATA.md present | gap | File absent from Blueprint. |
| COMPASS.md present | gap | Present but a single charter line; missing `## Compass`, `## Constraints`, `## Success Criteria`. |
| ARCHITECTURE.md present | pass | Template; Modules/Routes tables empty. |
| README.md with `## Intent` | gap | File absent from Blueprint. |
| FEATURE-*.md (web) | warn | Only FEATURE-Example.md template; no real feature. |
| SCREEN-*.md (web) | warn | Only SCREEN-Example.md template; no real screen. |
| DATABASE.md (persistence) | pass | Template; placeholder `table_name` only. |
| `## Acceptance Criteria` sections | warn | Present in conformant files but all `- None.` |
| `## Guardrails` sections | warn | Present but all `- None.` |
| `## Open Questions` sections | pass | Present in all conformant files. |
| Stack declared | gap | No METADATA.md to read `stack:` from. |

## Gaps
- METADATA.md is missing; no `stack:`, name, or description source.
- README.md with `## Intent` is missing.
- COMPASS.md is non-conformant: lacks the typed header and the required `## Compass`,
  `## Constraints`, `## Success Criteria` sections.
- ACCEPTANCE_CRITERIA.md has no typed header table and no real criteria (`(add criteria here)`).
- All FEATURE/SCREEN/DATABASE/UI/ARCHITECTURE files are unpopulated templates; no product
  behavior is specified.
- No acceptance criteria authored anywhere; SOUNDINGS has nothing to derive.

## Open Questions
- None.

## Stack Assessment
stack: not declared
METADATA.md is absent, so no stack field exists to evaluate.

## Readiness Verdict
verdict: blocked
METADATA.md and README.md are missing, COMPASS.md lacks its required structure, and every spec
file is an empty template — the Blueprint cannot yet support plan creation.

## Notes
COMPASS.md and ACCEPTANCE_CRITERIA.md are non-conformant (no typed header table). The remaining
files carry valid headers but no `Depends On`/`Provides`/`Phase` values, so all are build roots
and the dependency graph is flat. The Blueprint is at template-scaffold stage.
