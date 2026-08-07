# Changelog

All notable changes to Drydock are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Drydock follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the version remains `0.x`, the
command surface and Typed Specification contract are unstable and may change between releases.

## [Unreleased]

### Added

- 2026-08-06: `LINEAGE.json` at the Target root records which source version produced which work.
  The unit is a *source version*, not a parsed fragment of prose: import copies the file and lets
  git record it, so a version is a `(content hash, commit)` pair and a delta is a git diff. A
  version stays `pending` until `plan` or `refit` consumes it, and consumption appends the
  requirements found and the stories they became without rewriting any earlier version — the
  versioned history that previously did not exist, because refit overwrote the prior hash on
  success. Requirements point at Manifest story ids and never at Blueprints, since stories already
  carry `implements`. Each version also records the `METADATA.md` release identifier.

- 2026-08-06: `drydock refit <Target> --relineage` rebuilds `LINEAGE.json` for a Target that
  predates it. The deterministic half replays every source version from the Target's git history
  with its commit and date; the judgement half attributes existing Manifest stories to the
  requirements they implement, as a closed-set match. A story matching no requirement is recorded
  `origin: plan` and left unattached rather than failing — planning legitimately invents
  foundational work no sentence asked for. Requires a Target git repository and says so plainly
  when one is absent.

### Fixed

- 2026-08-06: `drydock refit --sources` now runs. It resolved a changed source to Blueprints
  through `MANIFEST.md` `source_lineage.files[].blueprints`, whose only writer attributed a source
  to a Blueprint when the Blueprint text literally contained the source filename — something no
  LLM-authored Blueprint does. The field was empty on every Target, so the command always failed
  with `Changed source has no lineage candidate Blueprint`. Routing is now one LLM call that
  decomposes the diff into stories seated on existing Blueprints, symmetric with planning:
  `plan` decomposes the whole source, `refit --sources` decomposes what changed. Every gate runs
  before the first write — unknown Blueprint, unknown or cyclic dependency, unrouted requirement —
  and any later failure restores the Manifest, the lineage record, and `blueprint/changes/`, then
  prints the commit to recover from. A requirement that seats on no existing Blueprint fails with
  `replan required`; refit never creates a Blueprint.

- 2026-08-06: A change ticket no longer claims authority over its whole parent Blueprint. Every
  ticket previously declared `Supersedes: <parent>` and "governs in case of conflict", so a
  one-sentence addition superseded assertions it never mentioned and that had already been proven.
  Tickets now carry `Scope`: `additive` supersedes nothing and leaves every parent assertion in
  force, `amending` supersedes only the sections listed under `## Amended Sections`, each
  validated against the parent so a ticket cannot amend a section that does not exist.

### Changed

- 2026-08-06: Both refit paths write one ticket format,
  `blueprint/changes/TICKET-NNN-{Name}.md` with `Version`, `Description`, `Amends`, `Depends On`,
  `Scope`, `Origin`, `Created` and `Stories`. `refit --sources` previously invented an undocumented
  `<Blueprint>_refit_N.md` table that appeared nowhere in `BLUEPRINTS_CONTRACT.md`; `build`
  consumed both only through the Manifest `implements:` field, so the divergence went unnoticed.
  The development workflow (machine-authored from a diff) and the production workflow
  (human-authored through an enterprise change process) now emit and consume the same artifact.
  The `Stories` row is load-bearing: `drydock refit` reprocesses every ticket on every run, and
  without the declared ids the model invents new ones and stories are duplicated rather than
  replaced in place. A ticket's `Depends On` remains computed from the parent Blueprint — inherited
  edges are never routed by the model. Stories gain optional `origin:` and `created:` fields.

- 2026-08-06: `refit --sources` reports blast radius from the existing `provides:`/`consumes:`
  edges, with no LLM. A change to a foundational story's *contract* lists the downstream stories
  that consume it, records them under `## Downstream Impact` in the ticket, and proceeds — the
  classification is model judgement and is not stable between runs, so the Commander decides
  whether to rebuild or defer. Deleting a provision another live story still consumes blocks
  before any file is written, because no ticket can repair a build that no longer has the service
  it uses. Source-driven refit also refuses non-text sources rather than routing a contentless
  delta.

- 2026-08-06: Retired two legacy lineage stores. `blueprint/sources/.drydock-import` is absorbed
  into the `LINEAGE.json` import record, keeping its rule against narrowing a directory root to a
  single file. `MANIFEST.md` `source_lineage:` is read once for migration and then removed, with
  its broken `blueprints` list discarded and reported. Migration runs at most once per Target and
  succeeds with neither file present. `import --update` no longer opens the Manifest at all, so it
  works on a Target that has not been planned. All Target git invocation moves behind
  `target_git`; the lineage commit sha is stamped by a follow-up commit rather than an amend,
  because amending would rewrite the very commit the record points at.

- 2026-08-06: QuarterDeck items that require a Commander answer can now be approved as proposed.
  Discovery questionnaires and the Technology Stack carry an `Approve` action in the page header;
  approving a questionnaire sets its state to `approved` without requiring answers, and approving
  the Technology Stack writes a dated `**Approved:**` marker into `TECHNOLOGY_STACK.md`. Editing
  an approved item never revokes the approval, and `approved` counts as a closed questionnaire
  state everywhere open questionnaires are counted (Analyze summary, Commanders Chair). The
  Technology Stack now also flies the sidebar action icon — red `✗` until approved, green `✓`
  after — so an unreviewed stack is as visible as an unanswered questionnaire.

### Fixed

- 2026-08-06: Programmatic Acceptance validation now discovers installed Python distribution
  metadata once per Drydock process instead of rescanning the environment twice per acceptance
  check. This removes repeated high-latency package metadata traversal during planning,
  particularly when the environment resides on a Windows-mounted filesystem under WSL.

- 2026-08-06: Text-only LLM-assisted commands no longer run with a writable codex sandbox.
  `llm.run_prompt(allow_tools=False)` suppressed tools on the `claude` path only; the `codex`
  branch never consulted the flag and ran with the configured sandbox, which defaults to
  `danger-full-access`. Commands that are contractually text-in/text-out — `rigging compact` among
  them — therefore had full filesystem and git write access to the invoking repository, and were
  observed editing their own output file, committing the result, and returning a narrative summary
  that the module then wrote over the file the model had just written. `allow_tools=False` now
  forces `--sandbox read-only` for codex, overriding `DRYDOCK_CODEX_SANDBOX`, the configuration
  file, and the `--codex-sandbox` flag, so the floor cannot be configured off. The forced path
  skips `_preflight_codex_sandbox`, which rejects `read-only` on Linux hosts lacking
  `codex-linux-sandbox`; codex enforces `read-only` natively and needs no helper. `drydock build`
  is unaffected — it passes `allow_tools=True` and keeps its configured sandbox and preflight.

- 2026-08-06: Corrected the SQLite connection-ownership pattern in the Rigging stack guidance.
  `stack/persistence.md` §1 previously prescribed a `Database` that opened one
  `sqlite3.Connection` in `__init__` and passed it to every table class. A `sqlite3.Connection`
  is bound to its creating thread, so generated web applications built the connection on the main
  thread during `create_app()` and raised
  `sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same
  thread` on the first request. Single-threaded unit suites never exercised the failure, so
  affected builds completed green and 500'd on first use. The guidance now requires one
  connection per thread held in a `threading.local()` and owned by `Database`; table classes
  receive a connect provider rather than a connection. `stack/sqlite.md` gains a Threads section
  naming `check_same_thread=False` as a non-fix, and `stack/flask.md` records that objects
  constructed in `create_app()` are shared across request threads. Compacts regenerated.
  Applications generated before this change need the same correction applied to their persistence
  module.

- 2026-08-04: `drydock import <Target> --update` now runs. `<Source>` is optional and rejected
  outright with `--update`, which refreshes from the root recorded in
  `blueprint/sources/.drydock-import`. Importers no longer narrow that recorded root: importing a
  single file out of a directory that was already imported keeps the directory as the refresh
  root, so `--update` stops reporting every sibling as a deletion. Snapshot comparison now uses
  the shared visible-source enumeration, so `.gitkeep` and other hidden bookkeeping never register
  as an added or deleted source.

### Changed

- 2026-08-03: `drydock build --ungate` releases prior programmatic acceptance failures as
  explicitly `UNVERIFIED` Manifest nodes and continues with the next buildable step; execution,
  dependency, and provider failures remain gated.

- 2026-08-02: Retired Blueprint and Sea Trials Markdown question sections. Plan, Build,
  acceptance authorization, and QuarterDeck Commander review now use `DECISIONS.json`; unanswered
  blocking decisions gate only their affected stories.

- 2026-08-02: `drydock build` no longer gates on the managed Build Write Guardrail in the
  human-editable `COMPASS.md`; Analyze and Compass creation continue to inject the guardrail.

- 2026-08-02: Plan and Build now govern external Programmatic Acceptance tooling through typed
  `Requires:` declarations and story-local Commander authorization questions. Commander answers
  become durable Target guidance, undeclared build-time prerequisites block without spending a
  repair attempt, and Python/uv acceptance executes through the Target `.venv` with locked uv
  provisioning instead of Drydock's interpreter.

- 2026-08-02: `drydock plan` resumes a planning response that ran out of output budget instead of
  discarding it. A deterministic score measures the artifacts returned against the run's own
  `TOPOLOGY.md` declaration, and continuation passes append a bounded instruction to the unchanged
  prompt prefix so the cached input is not re-billed. The loop stops when the accepted count stops
  increasing or the attempt cap is reached, and reports the score as numbers. Accepted stories are
  frozen; a continuation pass may still split a pending one. `--continue-attempts <n>` (default 3,
  `0` disables).

- 2026-08-01: `drydock score spec <Target>` independently inventories imported raw sources,
  extracts only cited Markdown facts in bounded subscription-authenticated LLM passes, and writes
  an advisory deterministic conformance report to `SPECIFICATION_SCORECARD.md` before Analyze.

- 2026-08-01: `drydock plan` recovers artifact responses whose opening delimiters were transposed
  onto the `=== END NAME ===` line, and accepts a byte-identical repeat of an artifact instead of
  discarding the run. Duplicate blocks with conflicting content, and delimiters appearing inside a
  parsed body, remain contract failures.

- 2026-08-01: `drydock plan` is restructured around authorship versus verification. The model
  authors the four jobs requiring judgment — specification content, programmatic acceptance
  alongside it, conflict resolution by precedence, and questions — and declares each story's type,
  phase, relationships, and stack. Drydock now owns the deterministic remainder in
  `plan_graph`, `plan_topology`, `plan_shape`, and `plan_stack`: graph verification, ordering,
  block grouping, builder/consumer stack-mode assignment, and output-contract shape checking. The
  Manifest becomes a list of stories typed `foundational`, `service`, or `feature`; `spike` and
  `ac` are retired as node types, acceptance becomes a field the story owns, and `Phase` moves out
  of the Blueprint header into the Manifest. Blocks replace feature grouping as the context
  optimization, never crossing a phase, topology type, or stack. Story sizing is a
  single-build-pass token ceiling and the ~100-story cap is removed. A phase/edge two-topology
  disagreement is now a deterministic error instead of a silent defect. The single-build-pass
  size limit is a target, not a gate: over-target stories and blocks are measured, marked in the
  Manifest, reported as warnings, and planned as-is, because an irreducible specification makes
  every story implementing against it over target by construction.
- 2026-08-01: `drydock plan create` asks the model for a `TOPOLOGY.md` declaration instead of a
  finished `MANIFEST.md`. The declaration has no way to express a position, so the model cannot
  assert an order it has not computed; Drydock verifies the declared graph, orders it, packs it
  into blocks, and serializes the Manifest itself. The declaration is transient and never reaches
  the Blueprint. The reuse and Spec Kit prompts continue to emit `MANIFEST.md` directly.
- 2026-07-31: Analyze now acts as the Team Lead/Product Owner completeness session, records
  Commander expectations as assertions, and emits an ASCII-safe crew handoff. Plan receives every
  readable imported source and treats Analyze's story map as a proposal: governed Markdown is
  authored from unconstrained source material, while non-Markdown assets are projected byte-for-byte
  without modifying source provenance. Structural validation enforces one specification per story
  and one owner per specification; preview and execution grouping both separate screen work from
  feature/service work. Blueprint decisions carry Low, Material, or Blocking severity, with only
  Blocking questions gating work. Commander answer revisions persist as replan history, and the
  Shipyard Crew can report bounded implementation decisions into only the owning Blueprint. MSYS,
  MinGW, and Cygwin terminals default to ASCII-safe output so status glyphs remain legible.
- 2026-07-31: `drydock run quarterdeck` accepts an optional Target and defaults to the most
  recently updated initialized Target in the configured workspace.
- 2026-07-30: `TECHNOLOGY_STACK.md` replaces the stack questionnaire as the technology decision of
  record. It maps each technology to the Rigging file governing it, or to none, so a target can
  name technologies Rigging does not document. `drydock analyze` proposes it once and never
  overwrites it; `drydock plan` reads it to assign per-story `stack:` guidance; QuarterDeck edits
  it as rows with a Rigging selector seeded by name similarity. The technology stack no longer
  gates planning, and `plan` resolves an input disagreement by a stated precedence order instead of
  deferring to the Commander. An answered `discovery-stack.json` migrates into rows on first use
  and is archived.

### Fixed

- 2026-07-30: QuarterDeck questionnaires are durable Commander-owned input. Answers survive every
  re-run of `drydock analyze` and feed the analysis as authoritative decisions alongside
  `drydock plan`; only the Commander edits them, in the QuarterDeck. Concurrent autosaves no
  longer corrupt a questionnaire file.
- 2026-07-30: `drydock plan` challenges a model-declared product conflict once before deferring.
  A recovered artifact batch proceeds through normal validation; a confirmed conflict is recorded
  in `ERRORS.md`, appears as pending BIG ERRORS and in the Commander's Chair, and prints its full
  diagnostic, required action, and execution evidence. `PLAN_COMPASS.md` remains human-owned.
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
