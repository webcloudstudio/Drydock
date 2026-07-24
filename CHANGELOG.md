# Changelog

All notable changes to Drydock are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Drydock follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the version remains `0.x`, the
command surface and Typed Specification contract are unstable and may change between releases.

## [Unreleased]

### Added

- 2026-07-23: Build repair loop. When a build block fails a deterministic gate in a repairable way —
  a Programmatic Acceptance miss or a surviving agent-reported failure — `drydock build` feeds the
  failure diagnostics back and re-runs the same block against the persisted partial work, iterating
  it toward green rather than restarting. Terminal failures (token or context limit, missing
  sandbox, provider error, dependency-legitimacy block, staged-asset tamper, no files written) never
  loop. The `--repair-attempts <n>` flag sets the budget (default `1`, `0` disables). Model
  escalation is opt-in and applies only to the final attempt, via `--escalate-model` or the
  `drydock_build_escalate_model` configuration key (unset by default). Evidence records each pass
  under `## Repair attempts`.
- 2026-07-22: Standoff diagnosis. When a command fails in a way its author cannot interpret — a
  post-LLM failure such as `no build files written`, or an unclassified exception — Drydock stops,
  states that a major error has occurred, and has the selected provider and model diagnose it. The
  result is one `CAUSE` line and up to three `DO` lines, printed and appended to the Target's
  `ERRORS.md`. Deterministic failures never trigger it: usage errors, provider authentication and
  rate-limit blocks, and any classification that already carries its own remediation are answered
  without an LLM call. Validation findings now state their own fix instead — a blank
  `short_description` names the file to edit and the command that fills it. `--no-diagnose` and the
  `diagnose` configuration key disable the feature.

### Changed

- 2026-07-23: Drydock command logging now writes one timestamped plain-text `.log` containing
  stdout for every command, including report commands such as `drydock status`. Internal Python
  logger output is isolated in matching `.debug.log` files; LLM execution logger artifacts use the
  same debug suffix. The shared rotating `run.log` files and redundant `events.jsonl` telemetry are
  retired; the LLM execution index is named `llm.jsonl`.

- 2026-07-23: `drydock build` treats a build agent's self-declared failure as advisory, not
  authoritative. When the agent still wrote files and the block carries Programmatic Acceptance
  criteria, Drydock runs the deterministic gate and lets the measured result decide the outcome —
  so an agent can no longer fail a block whose own acceptance criteria it met by editorializing
  about work outside that block's definition of done. The self-report is recorded in evidence under
  `## Agent self-report (advisory)`, distinct from the measured `## Post-build programmatic
  acceptance`. Blocks with no acceptance criteria, and hard execution failures (sandbox, token
  limit, non-zero exit, empty output), remain terminal.

- 2026-07-23: A failed `drydock build` now commits the build directory so the generated artifact is
  preserved for inspection, diagnosis, and the next rebuild instead of lingering as fragile
  uncommitted state that later asset staging can wipe. The commit subject carries a `[FAILED]`
  marker.

- 2026-07-22: Unsatisfiable Programmatic Acceptance assertions are rejected before they cost a
  build. A mis-authored expectation — most often a raw string literal carrying `\n`, which is a
  backslash and a letter rather than a newline — cannot be satisfied by any correct
  implementation, so the step burned a full agent cycle and closed `failed` against working code.
  `drydock validate` now fails on the defect and `drydock build` blocks before the agent runs,
  naming the Blueprint file and check to repair. Acceptance snippets also execute from a real file
  instead of `python -c`, so a failing assertion appears verbatim in evidence rather than as a
  bare `File "<string>", line 3`. The plan prompt contracts state the authoring rule.

- 2026-07-22: `drydock build` now stages declared build assets into the build directory. Analyze
  classifies every imported source with a build disposition; a source marked `stage` is placed at
  `sources/<name>` in the build directory, copied from the immutable import. Previously the
  disposition was parsed and discarded, so an imported test kit never reached the build tree —
  and because acceptance runs there, build agents authored substitutes to satisfy existence
  assertions and then graded themselves against them. Staged assets are digest-checked: a step
  that rewrites one fails and the asset is restored, and `drydock score` reports substitution as a
  release blocker without altering the artifact under judgment.
- 2026-07-22: a deterministic conformance corpus can now gate delivery. `SEA_TRIALS.md`
  measurement criteria accept `Extract:`, a regex capturing the measured value from a harness's
  own stdout, so a harness that reports in human-readable text and exits non-zero on failures is
  measurable without a project-authored wrapper. A single terminal verification story may gate on
  a complete corpus by declaring `Corpus: full` in its Programmatic Acceptance heading block;
  story acceptance remains bounded by default. A Sea Trial `Command:` containing an unresolved
  `<placeholder>` is now rejected rather than silently never running.

- 2026-07-17: reworked scoring to match the specification. `drydock score release` is now an
  LLM-assisted release gate that judges the project criteria in `SEA_TRIALS.md` and writes
  `SCORECARD.md` (prompt contract `prompts/score_release.md`); deterministic proofs, measurements,
  and guardrails still settle mechanically and feed the model. `drydock score ac` remains
  deterministic and is now the sole writer of `SOUNDINGS.md` — `analyze` and `plan` no longer create
  it, so a project has no Soundings until it is scored. The Commander's Chair renders a Scorecard
  section with per-criterion checkmarks.
- 2026-07-17: retired the Ship's Log feature, removed the `drydock shipslog` command and related
  repository tooling, and made `CHANGELOG.md` the only maintained high-level project history.
- 2026-07-17: aligned `drydock document` with its specification by making generated `DOC-*` output
  authoritative for configured sections only, tightening the prompt against invented content, and
  removing stale repository references to non-Target sample acceptance artifacts.
- `drydock import --format compass` now normalizes the intent document into the canonical
  COMPASS.md format with an LLM pass at import time (prompt contract
  `prompts/import_compass.md`), preserving the Commander's vocabulary. It is the only import form
  that runs an LLM and honors `--llm-provider` and `--model`. The written COMPASS.md is final and
  Commander-owned; an existing COMPASS.md is preserved unless `--force` is given, and
  `drydock analyze` no longer performs deferred normalization for compass imports.

## [0.1.1] — 2026-07-08

### Added

- Drydock Blueprint Methodology vocabulary across the product specification, documentation, and CLI.
- Sole authoritative product specification at `docs/Drydock_Specification.md`.
- Project foundation: single-sourced version, packaging metadata and classifiers, `py.typed` marker.
- Continuous integration (GitHub Actions) across Python 3.11–3.13 on Linux and Windows, with a wheel
  build and installed-CLI smoke test.
- Static type checking (mypy) and coverage reporting (pytest-cov).
- `pre-commit` configuration (whitespace, YAML/TOML, and ruff hooks).
- `nox` sessions for lint, type, tests, and build.
- Contributor guide and this changelog.
- `drydock rigging compact` — the first LLM-assisted command and general compaction entry point —
  with a versioned prompt contract (`prompts/<command>_<subcommand>.md` + required YAML frontmatter).
- Canonical product specification packaged in the wheel at
  `drydock/resources/docs/Drydock_Specification.md`.

### Changed

- Renamed the `INTENT.md` Typed Specification file and `INTENT` FileType to `COMPASS.md` /
  `COMPASS`, the `## Intent` body section to `## Compass`, and the `BUILD_PLAN_INTENT.md` planning
  inventory to `BUILD_PLAN_COMPASS.md`. "Compass" is the nautical term for the product's
  direction-setting document.
- Renamed the `drydock iterate` command to `drydock refit`, aligning the verb with the canonical
  SAIL Loop "Refit" concept. The `<BOTH|BLUEPRINT|TGT>` modes are unchanged.
- Replaced the public `drydock log` commands and shared target-project capture rules with the
  Drydock-only agent process in `AGENTS.md` and repository-local `bin/ships_log.py`.
- Renamed the public Blueprint root contract to `BLUEPRINT_DIRECTORY` and `blueprint_directory`;
  legacy specification-directory names remain accepted as deprecated migration aliases.
- Renamed the public CLI project argument from `<Spec>` to `<Blueprint>` and the iterate-side mode
  from `SPEC` to `BLUEPRINT`; `SPEC` remains accepted as a deprecated migration alias.

### Known Limitations

- This is an alpha release. Command contracts and Typed Specification contracts may change during
  the `0.x` series.
- LLM-assisted commands require an authenticated local `claude` or `codex` CLI.

## [0.1.0] — Unreleased

### Added

- Installable `drydock` CLI with `config`, `init`, and `validate` commands.
- Subscription-authenticated LLM execution foundation.
- Source-tree launchers and packaged Rigging resources.
