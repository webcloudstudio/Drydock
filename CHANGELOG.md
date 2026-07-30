# Changelog

All notable changes to Drydock are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Drydock follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the version remains `0.x`, the
command surface and Typed Specification contract are unstable and may change between releases.

## [Unreleased]

### Fixed

- 2026-07-30: `drydock analyze` now surfaces incompatible definitions across imported sources as
  required QuarterDeck questionnaire decisions. `drydock plan` refuses before invoking an LLM
  while any such decision remains unanswered, preventing late post-LLM conflict failures.
- 2026-07-30: Console output no longer fails with `UnicodeEncodeError` on a terminal that cannot
  encode Drydock's glyphs. Every command detects the console encoding and renders ASCII when
  needed. `--ascii` and `--unicode` override the detection.

- 2026-07-29: `drydock plan` accepts a wildcard source citation in `ANALYSIS.md`
  (`sources/FEATURE-CATALOG-*.md`), expanding it against the imported source material instead of
  demanding a file named after the fragment before the `*`.
- 2026-07-29: Imported prose content is always read. A Markdown or text source is never withheld as
  generated or minified — a withheld specification is a lost story — and a large one is chunked
  rather than summarized. Withholding now applies only to code and data artifacts, judged on line
  structure (one machine-scale line holding most of the file) rather than aggregate newline
  density, which had misclassified ordinary hand-written specifications.
- 2026-07-29: `drydock analyze` warns when any imported file's content was not read, naming each
  file and the reason. Command warnings print on stdout so they appear in the run log; sent to
  stderr they were absent from every transcript.

### Changed

- 2026-07-29: Sea Trials EARS conformance is now a derived `Notation: ears | other` label on every
  criterion rather than an enforced requirement. `Pattern` is optional and never a parse error,
  plain-English criteria are fully valid, and both notations are explained to the judge at scoring
  time. Removes the `drydock analyze` EARS repair pass and the `drydock score release` wording
  gate; the pattern shapes now accept a proper-noun system name.

## [0.1.4] — Unreleased

### Added

- 2026-07-27: `drydock plan` now reports the exact location and a JSON-escaped, 100-character
  preview when a model emits text outside otherwise complete artifact blocks. A batch with no
  structural or plan-integrity defect may use the already-enabled standoff-diagnosis call as a
  narrow semantic waiver: exact approval discards only trivial transition text and resumes the
  original transaction; rejection, malformed judgment, disabled diagnosis, artifact-like text, or
  more than 100 outside characters remains fail-closed and writes no Blueprint or Manifest
  artifacts. The waiver and original plan retain separate execution evidence.

- 2026-07-26: Reasoning effort is controllable across the command surface. `--effort
  <low|medium|high|xhigh|max>` is an invocation-wide override accepted by every command, and
  `drydock config set drydock_effort <level>` sets the standing default. Precedence is the flag,
  then a prompt's declared `effort:`, then the configured level, then the provider's own default.
  The level maps onto what the selected provider and model actually serve: claude takes the ladder
  as-is, codex receives it as `model_reasoning_effort`, with `xhigh` reserved for the codex-max
  model family and clamped to `high` elsewhere. Every rejection names the offending value and lists
  the valid levels.

- 2026-07-26: `drydock score drydock` runs an adversarial self-assessment of Drydock itself. It
  takes no Target: the subject is the Drydock source checkout. Intent is derived from
  `docs/Drydock_Specification.md`, and the methodology is attacked against Agile story
  decomposition, Test Driven Development acceptance, context economy, and governance, including
  coverage gaps for project types Drydock has not been exercised on. The command changes no code —
  it writes ranked feature files, each decomposed into Agile stories with TDD acceptance criteria
  and an implementation plan, to `docs/drydock_planning/`, with an `INDEX.md` ranking every feature
  by impact and complexity. The assessment defaults to the highest available model rather than the
  configured build model, and a previous plan is archived rather than overwritten.

- 2026-07-26: A Programmatic Acceptance check that fails inside its own snippet is now rejected
  rather than built against. Every check runs as its own script in its own process, so a check
  reading a name a sibling check bound raises `NameError` on every run and no implementation can
  turn it green. `drydock validate` and `drydock build` reject an unparseable snippet, and a
  snippet reading an unbound name, before any LLM pass is spent; at runtime such a failure is
  classified `malformed check` rather than reported as a missed assertion. `drydock validate`
  additionally warns when a check captures a test runner's output and never prints it, which
  reduces a failure to a bare assertion with no tally and no failing cases. A failing check now
  prints both of its output streams to the console, and a failed Definition of Done line is
  marked `[!!]` so it cannot be misread as a ticked checkbox.

- 2026-07-25: Programmatic Acceptance runs under a bounded address space in its own process
  group, configured by `drydock config set sandbox_mem_limit <MB>` (default 4096; `0` lifts the
  bound, and JVM or Go toolchains generally need it raised). Built code that allocates
  without bound or never terminates is stopped by the kernel in seconds instead of driving the
  host into swap for the whole timeout window, and the timeout now reaps the check's whole
  process tree rather than orphaning a runaway grandchild. A resource kill is reported as
  `exhausted memory` / `timed out` rather than as a missed assertion, and the repair pass leads
  with that fact so it fixes the non-terminating code instead of tuning output.

- 2026-07-23: The Commander's Chair now publishes a prominent `RUNNING` notice with the command
  and UTC start time while `drydock analyze`, `drydock plan`, or `drydock build` executes, then
  regenerates its terminal state on every exit path. Its new Logs and Run History tabs are live
  QuarterDeck views: Python rereads the workspace log inventory and the active Target's filtered,
  newest-first `logs/history.jsonl` records on every request.
- 2026-07-23: Build repair loop. When a build block fails a deterministic gate in a repairable way —
  a Programmatic Acceptance miss or a surviving agent-reported failure — `drydock build` feeds the
  failure diagnostics back and re-runs the same block against the persisted partial work, iterating
  it toward green rather than restarting. Terminal failures (token or context limit, missing
  sandbox, provider error, dependency-legitimacy block, staged-asset tamper, no files written) never
  loop. The `--repair-attempts <n>` flag sets the budget (default `3`, `0` disables). Repair
  continues only when passing ACs grow without regression or stable ACs show non-regressing
  per-criterion case progress. Feature repair grades verified sibling ACs as regression gates and
  reopens a sibling whose behavior regresses. Normal console output and evidence report each
  attempt's AC and case totals. Model escalation is opt-in and applies only to the final attempt,
  via `--escalate-model` or the `drydock_build_escalate_model` configuration key (unset by default).
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

- 2026-07-28: Normal `drydock build` output identifies the block, active stories, verified sibling
  regression gates, LLM call number, repair position, model, and current failing AC case totals
  before every provider call. Acceptance summaries use one-based call numbering. Suite acceptance
  permits an authoritative exact passed count or a count derived from authoritative suite data;
  runner success remains mandatory.

- 2026-07-24: Every log file is named `<stamp>_<Target>_<command>[_<provider>].<extension>`. The
  stamp is a readable UTC instant, `20260725.004228.288Z`, replacing `20260725T004228288279Z`, and
  `execution_id` shares it. An LLM-assisted command's transcript names the provider in force — the
  `--llm-provider` override when given, otherwise the configured default — so the transcript and
  the evidence files beneath it share one stem; a deterministic command such as `drydock status`,
  `drydock validate`, `drydock build status`, or `drydock score ac` names no provider, because none
  runs. `drydock build`, `drydock status`, `drydock score`, and `drydock document` resolve their
  Target from their operand list, which also fills the Target field they previously left blank in
  `logs/history.jsonl` and directs a standoff diagnosis at that Target's workspace instead of the
  working directory. Drydock no longer leaves empty log files: a transcript that captured no output
  and an unused LLM `.stderr.log` are both discarded on close, and `llm.jsonl` omits the `stderr`
  artifact path when there is no such file.
- 2026-07-23: Drydock no longer creates command or LLM execution `.debug.log` files. The global
  `--debug` option, accepted before or after the command, prints internal Python and LLM execution
  diagnostics to the console for the current invocation. Normal command transcripts and
  reproducible LLM evidence artifacts remain unchanged.

- 2026-07-23: Drydock command logging now writes one timestamped plain-text `.log` containing
  stdout for every command, including report commands such as `drydock status`. The shared rotating
  `run.log` files and redundant `events.jsonl` telemetry are retired; the LLM execution index is
  named `llm.jsonl`.

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
- 2026-07-24: "corpus" is retired throughout. The imported source body is now **source material**
  (`drydock.source_material`, `SourceMaterialFile`, `discover_source_material`) and the conformance
  concept is the **test suite**. The legacy `Corpus:` acceptance marker is removed; a full-suite
  gate declares `Suite: full`. The Plan integrity gate now rejects any non-terminal story that runs
  the whole test suite without `Suite: full`, and the Blueprint prompts direct a harness staging
  story to bound its run with the runner's `--pattern`/`--number` selector.
- 2026-07-22: a deterministic conformance test suite can now gate delivery. `SEA_TRIALS.md`
  measurement criteria accept `Extract:`, a regex capturing the measured value from a harness's
  own stdout, so a harness that reports in human-readable text and exits non-zero on failures is
  measurable without a project-authored wrapper. A single terminal verification story may gate on
  the complete suite by declaring `Suite: full` in its Programmatic Acceptance heading block;
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
