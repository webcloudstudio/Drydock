# Drydock Changes: July 5–August 4, 2026

## Changelog effectiveness

`CHANGELOG.md` is effective as a high-level product changelog. It captures the major behavioral
changes and architectural decisions, especially from July 17 through August 3. The entries are
technically specific and generally explain user-visible behavior, affected commands, and important
constraints.

It is not a complete account of the repository's activity during the period.

Evidence:

- The repository recorded 423 commits from July 5 through August 4.
- The changelog contains approximately 39 dated entries in that interval.
- Meaningful dated changelog coverage begins on July 17, omitting most work from July 5–16.
- The repository contains release tags `v0.1.1` through `v0.1.5`, while the changelog still
  presents `0.1.4` as `Unreleased` and does not clearly reconcile the tagged releases.
- Several substantial areas are absent or underrepresented: workspace and Target initialization
  gating, release and packaging work, release-video and presentation work, Claude/Codex skill
  provisioning, white-paper consolidation and publishing, early QuarterDeck and stack-questionnaire
  work, build-frontier changes, and evidence-bound completion gates.

The changelog answers this question well:

> What major Drydock product capabilities changed recently?

It answers this question less well:

> What significant work happened in the repository during the entire last 30 days?

Assessment:

- Approximately 8/10 as a product-behavior changelog.
- Approximately 5/10 as a complete 30-day project-history summary.

Structural issues identified:

- `### Changed` appears twice under `[Unreleased]`.
- Changelog release headings are not aligned with the repository's release tags.
- The current organization makes it difficult to distinguish shipped behavior from unreleased
  work.

## What happened

The work moved Drydock from a mostly LLM-orchestrated planning and build workflow toward a
governed, evidence-producing delivery system:

```text
LLM authors judgment
        ↓
Drydock verifies structure and integrity
        ↓
Drydock executes deterministic acceptance
        ↓
Drydock records evidence and recovery state
        ↓
Commander governs unresolved decisions
```

### July 5–16: project foundation, release, and workflow hardening

- Added required workspace configuration and Target initialization gates.
- Added and revised release and installation documentation.
- Created the release announcement video, presentation material, and launch-oriented README
  content.
- Added Claude Code and Codex skill provisioning.
- Added or refined stack guidance, environment and secrets guidance, uv, Ruff, and TypeScript
  stack files.
- Improved build dry-run diagnostics, build-frontier behavior, Manifest ordering, block
  atomicity, and failed-build recovery.
- Tightened the planning contract around one story per Blueprint file, mandatory acceptance, route
  coverage, dependency ordering, and typed specifications.
- Improved QuarterDeck Manifest presentation and status rendering.

### July 17–21: acceptance, scoring, and governance model

- Made `drydock score ac` the deterministic acceptance scorer and sole writer of `SOUNDINGS.md`.
- Made `drydock score release` an LLM-assisted release gate over Sea Trials.
- Added evidence-bound completion and dependency-legitimacy gates.
- Added EARS notation and Sea Trials guardrail behavior.
- Added per-assertion Soundings and improved acceptance traceability.
- Added Target blocker persistence, QuarterDeck blocker handling, and the Analyze-to-Plan handoff.
- Added Rigging manifest registration.
- Retired the Ship's Log feature and established `CHANGELOG.md` as the maintained high-level
  history.
- Refined public specification and documentation surfaces.

### July 22–25: deterministic build gates, repair, and execution evidence

- Added deterministic full-suite conformance gating.
- Added staged build assets with digest verification and substitution detection.
- Added `Extract:` measurements for harness output.
- Rejected unsatisfiable or malformed Programmatic Acceptance before spending an LLM build pass.
- Added standoff diagnosis for opaque failures.
- Added the build repair loop with bounded attempts and optional model escalation.
- Changed build acceptance to rely on measured results rather than an agent's self-report.
- Added process-group and memory limits for acceptance checks.
- Improved handling of timeouts, memory exhaustion, malformed checks, and failed subprocesses.
- Reworked command and LLM logging into Target-qualified, timestamped transcripts and evidence
  artifacts.
- Added live QuarterDeck run status, logs, run history, status gates, and build reports.
- Improved build recovery commands and failure attribution.

### July 26–29: planning resilience, self-assessment, and acceptance robustness

- Added `drydock score drydock`, an adversarial self-assessment of Drydock itself.
- Added invocation-wide reasoning-effort controls.
- Added typed Manifest graph validation and integrity gates.
- Added bounded artifact waivers and recovery from malformed or transposed plan delimiters.
- Added continuation and repair handling for plans that exceed one LLM response.
- Added monotonic build-repair progress checks and acceptance progress reporting.
- Improved malformed acceptance diagnostics and isolated each acceptance check in its own process.
- Added deterministic post-build scoring.
- Changed Sea Trials EARS from an enforced syntax requirement to derived notation.
- Made imported prose always readable and warned when imported files were withheld.
- Added wildcard source-citation support.
- Improved console encoding behavior for ASCII-only terminals.
- Added a QuarterDeck Build Report tab.

### July 30–August 4: planning architecture and decision governance

- Replaced the stack questionnaire with `TECHNOLOGY_STACK.md`.
- Made QuarterDeck questionnaires durable Commander-owned input.
- Added conflict detection and required planning decisions during Analyze.
- Added `DECISIONS.json` as the decision surface for Plan, Build, acceptance authorization, and
  QuarterDeck review.
- Retired Markdown question sections from Blueprints and Sea Trials.
- Made Analyze the completeness and product-owner session.
- Added story-local planning questions and durable answer revisions.
- Split model authorship from deterministic Drydock verification.
- Reworked `drydock plan create` around a transient `TOPOLOGY.md` declaration.
- Made Drydock compute graph validation, ordering, block grouping, stack assignment, and Manifest
  serialization.
- Replaced feature grouping with phase-, topology-, and stack-aware build blocks.
- Added plan continuation scoring and bounded continuation attempts.
- Added raw-source specification conformance scoring through `drydock score spec`.
- Added QuarterDeck Markdown directory views and a nautical favicon.
- Allowed builds with human-edited Compass files.
- Added governed external acceptance-tool authorization.
- Added `drydock build --ungate`, which can release selected Programmatic Acceptance failures as
  explicitly `UNVERIFIED` nodes while retaining hard gates for execution, dependency, and provider
  failures.
- Improved build diagnostics, structured error preservation, Blueprint-edit handling, and
  Commanders Chair flag visibility.

## Overall interpretation

The defining change of the period was the separation of judgment from verification. The model now
authors specification content, acceptance intent, conflict resolution, and questions. Drydock
owns deterministic graph verification, ordering, block construction, stack assignment, artifact
shape validation, acceptance execution, evidence, and recovery state. Commander-owned decisions
provide the governance boundary for unresolved product and tooling choices.

The existing changelog communicates this transition well, but a complete project-history record
should add a concise July 5–16 summary and reconcile the release headings with the actual tags.
