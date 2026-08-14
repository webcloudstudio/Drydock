# Changelog

All notable changes to Drydock are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Drydock follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the version remains `0.x`, the
command surface and Typed Specification contract are unstable and may change between releases.

## [Unreleased]

### Changed

- 2026-08-14: `drydock score release` grades the finished tree by observing it, and the verdict
  vocabulary collapses to three words. A run is `PASSED`, `FAILED`, or `ERROR`; a criterion is
  `MET`, `NOT MET`, or `MANUAL`. `PENDING MANUAL VERIFICATION` is retired: it was doing two
  unrelated jobs — a criterion no machine can ever settle, and a project that is not built yet —
  and one word for both is how a finished, correct project came to be reported as though it had
  open questions. The first is `MANUAL`, which attests and never blocks; the second is `NOT MET`,
  because an unbuilt criterion gets an F. `NOT MET` still requires the grader to have looked and
  to cite what it saw, so a verdict with no citation degrades to `MANUAL` rather than failing a
  build nobody examined.

  Score no longer reads what the build recorded. An assertion that passed at block 3 is a
  statement about the tree as it stood at block 3, so AC outcomes, block states, and the Manifest
  are history and reach no verdict. The governed gate is executed rather than inherited, every
  `Command:` a trial names is run against the final tree, and the grader is handed the build
  directory with tools so it can read the source and write an **ephemeral probe** for behavior no
  command covers. Probes live in `.drydock-probe/` inside the build tree and are deleted after
  grading whether or not the grader tidied up. The console prints the whole listing — every
  criterion and what was observed of it — and `evidence/score-release.json` moves to schema
  version 5 with `verdict`, `verdict_line`, `statement`, and `observations`. `SCORECARD.md` is now
  a release scorecard rather than a completion gate. Exit codes are unchanged: `PASSED` exits 0,
  `FAILED` and `ERROR` exit 1, with the two distinguished in the record — UAT now reads the
  recorded verdict instead of the exit code, so a run Drydock could not grade is an execution
  fault rather than a product failure.

- 2026-08-14: Sea Trials are referenced by nothing. `Sea Trials:` proof tags on Programmatic
  Acceptance blocks, `Verification:` as a mechanism selector, and the plan-time coverage gates are
  all retired: plan no longer validates `accepts:` targets, proof-tag targets, or that required
  trials are covered, and neither scorer looks up a criterion's verdict from which assertion
  claimed it. `accepts:` survives as human-readable traceability that gates nothing.

  What this closes: ReadingList run `20260814.001652` built a complete, correct product and was
  refused five times because `plan` and `score release` read the same coverage contract
  differently — `plan` accepted an `accepts:` field *or* a proof tag, `score` counted proof tags
  only. Every blocked criterion carried a grader rationale asserting it was met beside an evidence
  line reading `no code-bound proof references this criterion`. A grammar with two readers has one
  of them wrong.

### Added

- 2026-08-13: Artifact blocks carry an invariant closing boundary.
  `=== BEGIN ARTIFACT <name> ===` … `=== END ARTIFACT ===` is now the emitted form in
  `analyze`, `plan`, `document generate`, `survey import`, and `import compass`. The artifact name
  is typed once, at the open; the close is a constant token with nothing to recall and nothing to
  collide with, which is MIME multipart discipline. Both parsers accept the named form
  (`=== NAME ===` … `=== END NAME ===`) unchanged, so no recorded response stops parsing, and the
  `=== AC <id> ===` proof containers are deliberately excluded — there the id in both markers is a
  real checksum binding a criterion to its identity.

  The failure this prevents: a Toml `analyze` run died because the model closed `COMPASS.md` with
  `=== END COMPASS ===`. The only artifact that closed wrongly was the only one whose first
  heading restated its filename stem, twenty-five lines above the close. Any artifact whose
  content restates its filename is exposed to the same collision, and the close delimiter was the
  one place the protocol asked the model to reproduce a variable from memory.

### Fixed

- 2026-08-14: `drydock status <Target> --ready` checks the actual buildable frontier instead of
  deriving readiness from verification completeness. A Target whose stories are terminal
  `closed/implemented` but not `closed/verified` now stops the build loop immediately rather than
  issuing empty builds until UAT exhausts its pass budget. `status --check` remains the separate,
  read-only verification-completeness check; UAT records that result without using it to gate
  final-tree release scoring.

- 2026-08-13: The `plan` repair prompts state the artifact grammar instead of demonstrating a
  different one. Both repair prompts are assembled in Python rather than under `prompts/`, so the
  invariant-boundary migration never reached them: each asked for a "fully paired block" without
  saying what one looks like, then supplied the original body inside `<original-topology>` or
  `<original-artifact name="…">` tags. The model mirrored the only syntax it was shown. In Toml
  run `20260813.234757` a topology coverage repair the model performed correctly was discarded
  unread — twice — and `drydock plan` refused the run on `DECODER-002`, the analyzed story the
  discarded repair had covered, after Stage 2 had authored ten Blueprints against the declaration
  already known to be defective.

  `artifact_blocks` now owns the emission contract (`artifact_open`, `wrap_artifact`,
  `emission_contract_lines`), rendered from the delimiter constants so no prompt hand-types a
  boundary, and both repair prompts supply their input wrapped in the same grammar they ask for.
  A single `_read_repair_blocks` replaces the two independent readers in the coverage and
  continuation repair loops. The XML fallback survives as recovery for replies already in flight
  and additionally accepts `<NAME>…</NAME>` for filename-shaped names, refusing a reply that mixes
  forms. A repair Drydock cannot use is now reported with its reason rather than silently
  returning the uncorrected declaration on four separate paths.

- 2026-08-13: Every check that reasons over raw artifact delimiters now reads both boundary
  grammars. Adopting the invariant close taught the two parsers a second grammar but left five
  callers counting named `=== END <name> ===` lines, and the invariant close carries no name to
  count: `drydock plan` read an undamaged Stage 1 response as wholly unpaired, discarded the
  topology it had just parsed, and died `KeyError: 'TOPOLOGY.md'` in the continuation loop
  (Toml run `20260813.231738`). The same blindness made `plan_shape.check_delimiters` report
  every artifact unclosed and every close an orphan, and made `plan conform` silently find no
  spec in a well-formed response.

  Pairing is now computed once, positionally, by `artifact_blocks.pair_artifact_delimiters`, and
  shared by `planning_session` and `plan_shape`; it mirrors the parser's own recovery rules, so a
  structural check can no longer disagree with what the parser extracted. The duplicate delimiter
  regexes in `plan_shape` are deleted, and `plan conform` extracts through the shared parser
  rather than a name-backreferencing regex that the invariant close cannot satisfy.

- 2026-08-13: A malformed artifact block no longer discards the artifacts beside it. Both the
  `analyze`-path parser (`artifact_blocks`) and the `plan`-path parser (`planning_session`) now
  reject per artifact: a block whose name is not allowed, or whose boundaries could not be
  resolved, is dropped by name with its reason, and the command proceeds on what it did accept.
  Callers state which artifacts they require — `analyze` requires `ANALYSIS.md`, `document
  generate` requires its four standard sections — so a missing required artifact is still fatal,
  but it now fails naming the artifact rather than naming a block the model never opened. Only a
  response from which nothing survived is rejected whole. Four of twenty recorded UAT runs died
  this way, one of them discarding nineteen Blueprints and eight LLM calls over a single
  malformed block.

- 2026-08-13: A closing delimiter that names the wrong artifact is read as a close, not as a new
  block. Both parsers recognise the close by position — a name-mismatched close whose successor is
  another delimiter, or the end of the response, terminates the open block — and report the name
  disagreement naming both markers. A mismatched close whose successor is real content is still
  read as the boundary the model transposed. The names are never fuzzy-matched: the close's name
  is a checksum on the open, and matching them loosely would discard the property that makes an
  unclosed container detectable at all. Previously the parser invented a block named after the
  marker, then failed the allow-list on a name the model never opened, producing a diagnostic that
  pointed at the wrong artifact.

- 2026-08-13: A UAT fixture declares the verdict it expects. `uat.json` accepts
  `"expect": {"verdict": "PASSED|PENDING|FAILED|ERROR"}`, defaulting to `PASSED`, and every
  shipped kit declares one. `result.json` gains `expected_verdict` and `observed_verdict`, and a
  kit's `status` is now a comparison of the two rather than a copy of the observed one: a fixture
  carrying a known product defect that Drydock correctly reports as `FAILED` is a UAT pass. The
  observed verdict folds the run's two existing status views — an infrastructure fault is `ERROR`
  and never satisfies an expected `FAILED`, because a run that could not execute has said nothing
  about the product. This changes what `drydock uat` measures: it asks whether Drydock reached the
  correct conclusion about the fixture, not whether the fixture project passed. Eight recorded runs
  of a fixture with a real defect produced no signal about Drydock at all, because each read as
  Drydock failing.

- 2026-08-13: A story acceptance criterion binds only to an oracle it could not have invented.
  `acceptance.retyped_expectations` reads each criterion's AST and reports every expected string
  literal the author typed a second time rather than deriving; `ProgrammaticAcceptance.binding` is
  false when any exists. A binding criterion that misses its expectation fails its block as
  before. A non-binding one settles `DISPUTED` — run, graded, reported on the console, in the
  attempt summary, and in `score ac` — and is charged to nothing. Legal expected values are a
  staged suite's exit status, a status code, a value the criterion supplied as input, and an
  identifier-shaped contract token such as `"integer"` or `"application/json"`; illegal ones carry
  something that must be escaped correctly twice, once building the input and once stating the
  expectation.

  The failure this addresses is the dominant one in UAT. A criterion supplied the TOML literal
  string `'C:\\Users\\nodejs'`, whose backslashes a literal string preserves verbatim, then
  asserted the decoded value equalled `r"C:\Users\nodejs"`. The decoder was correct; the
  criterion was wrong; nothing downstream could tell which. That run cost 2.1M tokens and ended
  `degraded`. The adjacent basic-string assertion in the same criterion was re-typed too and
  happened to be right, which is the shape of the problem: a coin flip per assertion. Measured
  against the stored fixtures the rule admits 24 of 25 Toml criteria and 29 of 33 CommonMark
  criteria; the five it holds back are the one that failed wrongly and four renderer transforms
  whose output cannot be derived from their input and which a staged conformance suite already
  covers.

### Changed

- 2026-08-13: Drydock's own bookkeeping no longer blocks a release. `score` and `score release`
  report a dirty build directory, a missing Git code identity, and stale applied Blueprint
  specifications as warnings rather than blockers. The case that settled it: a run passed all 8
  Sea Trials and all 26 programmatic assertions, then failed the release with
  `BLOCKER: Build directory has uncommitted changes` — the uncommitted change being an SQLite
  file the project's own test suite created when Drydock ran it. Drydock ran the tests, the tests
  wrote a file, and Drydock refused the release because a file was present. The governing rule: a
  gate may only block on a fault domain it can distinguish, and a dirty worktree cannot
  distinguish a defective product from tidy housekeeping. Operators who relied on `score release`
  failing on an uncommitted build tree now read that condition from the warnings.

- 2026-08-13: The minimum-assertion gate is deleted. A story declaring a programmatic surface no
  longer has to carry at least two `=== AC ===` criteria, and `_MIN_ASSERTIONS_PER_STORY`, its
  imported-suite exemption, and the bare-`- None.` emission failure go with it. Quantity is not a
  gate: forcing a story to reach a count makes the model author criteria it has no oracle for, and
  every invented criterion is a fresh chance to predict an expected value wrongly. The Toml
  evidence is exact — 15 suite-bound criteria all passed, and 10 hand-authored criteria covering
  nothing the conformance suite did not already cover supplied 100% of the failures. Coverage is
  measured by an authoritative suite or by the project's own test suite, graded at the Sea Trials
  level. `drydock plan` no longer fails on a Blueprint whose acceptance section is empty.

- 2026-08-13: The release grader may reason toward `PASS` and may not reason toward `FAIL`.
  `prompts/score_release.md` (V5) states the asymmetric evidence rule: absence of evidence is
  `INCONCLUSIVE`, never `FAIL`, and a `FAIL` must cite a specific artifact that exhibits the
  failure. The guardrail special case is removed — a prohibition is judged by the same rules as
  any other criterion — along with the instruction never to infer that a guardrail held and the
  stale claim that `UNPROVEN` "fails the gate exactly as a breach does", which stopped being true
  when unproven guardrails became manual-verification attestations. That instruction was
  observably biasing the grader: a recorded run's rationale was a verbatim restatement of it.

- 2026-08-13: The authoring contract addresses tests to two destinations.
  `prompts/BLUEPRINTS_CONTRACT.md` (V12) separates story AC — few, gating, authored before the
  code exists, so every expectation in one is a prediction — from the project's own test suite,
  authored beside the finished code, where expectations are observed and coverage is unbounded.
  Patterns 1, 4, 6, 9, and 10 govern AC blocks; patterns 2, 3, 5, 7, and 8 are stated as suite
  discipline. The contract now also states what each criterion is worth — blocking, consultative,
  advisory, or void — so an author can aim: a hand-typed expectation does not merely risk being
  wrong, it demotes the criterion to advisory and leaves the story with no gate at all.
  `prompts/build.md` (V6) gains the matching obligation to grow the project's suite as it writes
  the code, including test isolation, so a test run leaves no residue in the build directory.

- 2026-08-11: A criterion that raises `TypeError` in its own frame reports UNVERIFIED and is not
  charged to the build. `TypeError` joins `NameError`, `SyntaxError`, and their neighbors in
  `acceptance._MALFORMED_EXCEPTIONS`: a criterion that dies on argument passing never reached the
  code under test, so grading it FAIL closed a block that no implementation could reopen. A build
  measures pass and fail verdicts; an exception in the harness is charged to the harness, stated
  by id in the block evidence and the build summary. Attribution remains by traceback frame — the
  same `TypeError` raised inside the built code is still a genuine red. The known trade: a
  `TypeError` a correct implementation would have avoided also stops gating, visibly rather than
  silently.

- 2026-08-12: Sea Trials are the sole input to the completion gate. `score` and `score release`
  report unclosed Manifest work as a warning instead of a blocker, so a release whose every
  required Sea Trial passes completes even when a story sits at `closed/failed` or `pending`.
  Both modules already documented this contract — "story acceptance is reported, never an input
  to the release decision" — while `blockers.append("Manifest work is not closed/verified: ...")`
  contradicted it, making a per-story acceptance criterion a release gate transitively: a failed
  criterion closes its story `closed/failed`, which failed the release. A TOML run passed all four
  required Sea Trials and the full external toml-test suite (205 valid, 474 invalid, 0 failed) and
  still scored `INCOMPLETE`, because one generated criterion asserted the wrong JSON shape and took
  four stories down with it. The backstop that Manifest closure stood in for — a contract satisfied
  by work nobody did — remains a blocker and tests the contract directly: a required Sea Trial with
  no implementation or proof coverage fails the gate. `drydock status --check` is unchanged and
  still reports the terminal pipeline state from Manifest closure, so the build loop continues to
  stop on unclosed work.

- 2026-08-13: Governed acceptance commands decide block and release state. `ACCEPTANCE.json` in
  the Target root declares a `full` gate and optional per-story `stages`, each an argv array
  Drydock executes directly. It is Commander-owned; no LLM-assisted command writes it, and
  `drydock uat` seeds it from the fixture's `acceptance` block so UAT and ordinary operation
  consume one target-level contract rather than diverging.

  This exists because authority cannot be inferred from an artifact the model wrote. The same
  model authors the criterion, its input, its expected value, and the code meant to satisfy them;
  when they disagree, nothing recovers which is wrong. A criterion declaring `Suite:` or naming a
  path under `sources/` proves nothing, because a model can type either string. So the oracle now
  comes from data outside the model-authored artifact, and Drydock runs the argv rather than
  inspecting a wrapper the model generated.

  Precedence: a governed gate outranks a model-authored criterion, and a model-authored criterion
  outranks nothing at all. Where a stage gate covers a story its verdict is the verdict and the
  criteria are diagnostic — the console reports criteria that stayed red where the gate passed,
  against the criteria rather than the product. Where no gate covers the story, a binding
  criterion is still the only evidence available and still fails the block; discarding it would
  leave a project without a conformance suite, which is most projects, with no failure signal at
  all. A story finishing under a declared contract but outside its coverage closes `implemented`
  rather than `closed/verified`, with an advisory saying so, because "verified" is a claim about
  an oracle. That distinction is drawn only for a project that has opted into governance.

  The gates run inside the repair loop, on every attempt, and their output is fed to the next
  agent call. A gate that reported only after the budget was spent would drive no repair at all —
  the block would simply fail with every pass unused — so a red gate is classified repairable and
  is the signal the loop steers by.

  `build_plan.FINISHED_STATES` lets `implemented` satisfy a dependency, so an ungoverned story no
  longer stalls the blocks behind it. Gate execution is classified three ways and the distinction
  is load-bearing: exit zero is a product PASS, a non-zero exit from a command that ran is a
  product FAIL, and an absent executable, timeout, signal, or unusable build directory is ERROR —
  evidence about the kit, never charged to the build. Each result records argv, exit code, stdout,
  stderr, duration, timeout classification, and a digest of the built tree, so a verdict names the
  artifact and the command that produced it. `drydock score release` runs the `full` gate and
  records it in `evidence/score-release.json`.

  The Toml fixture declares six stage slices of the installed toml-test suite plus
  `sh sources/full_test.sh` as the release gate, and stages a `stage_test.sh` that builds the
  decoder and runs one slice.

- 2026-08-13: `drydock uat` reports `execution_status` and `acceptance_status` separately, and the
  headline status passes only when both do. A product test failure is not an infrastructure
  error, but an infrastructure error must still stop a run reading as a pass — which a single
  status derived from the final command's exit code allowed whenever an orchestration failure or
  a skipped stage was followed by a weak command that happened to exit zero.

- 2026-08-13: An acceptance criterion that cannot execute no longer discards the plan. A single
  criterion that failed to compile raised `SpecificationError` from `drydock plan`, throwing away
  every Blueprint and Manifest artifact the run had produced — five LLM calls of correct work lost
  to one bad snippet, with no way to restart from where the run stood. The criterion was never
  dangerous: it raises in its own frame, which the runtime classifier reads as a malformed check
  and settles UNVERIFIED, so it gates nothing and costs its story nothing.

  The plan is now written, the defect leads the warning list, and each one becomes a blocking
  `DECISIONS.json` record against the owning story. `severity: blocking` gives both modes what
  they need from one mechanism: interactively the operator is asked whether the criterion is
  salvageable before that story builds, and under `--override` the run proceeds with the record
  intact for review. Bad stories and bad Sea Trials are outside Drydock's control; a bad
  acceptance criterion is generated by a command Drydock runs against a contract Drydock owns, so
  a pipeline that cannot process one cleanly is a pipeline defect rather than a modelling
  accident.

- 2026-08-13: `closed/implemented` joins the Manifest state vocabulary for a story whose work
  finished with no governed command able to judge it. It is terminal and satisfies a dependency,
  so an ungoverned story does not stall the blocks behind it, and it renders as `[unverified]`
  rather than `[done]`. The existing `implemented` state was not reused: it is a mid-flow state in
  the child-`ac` taxonomy meaning "built, acceptance not yet run", where a dependent must *not*
  build on it, and conflating "not verified yet" with "nothing will ever verify this" broke
  dependency scheduling in both directions. `drydock status --check` still counts only
  `closed/verified` toward completion, because runnability and completion are different
  questions.

### Removed

- 2026-08-13: The acceptance prediction layer is deleted — 2664 lines. Six analyzers in
  `proof_integrity.py` predicted from a criterion's text that it would fail: mis-authored
  literals, unbound names, shell escapes, swallowed output, runner-tally vocabulary, and
  staged-script invocation. Each was added in response to one observed failure, the space of bad
  assertions is not enumerable, and every entry carried its own false-positive rate against
  legitimate snippets. Two had already been retracted after they began failing fixtures that had
  passed for weeks; accumulating the rest is how the fixtures degraded. Removed with them: the
  plan-time authoring and staged-setup fatals, the unbounded-suite and zero-skipped fatals, the
  build-time quarantine and its advisory Manifest finding, and the `validate specification`
  advisories, which now report the one surviving authoring signal instead. Vacuity analysis
  (`analyze_proof`) and the compile gate survive: the first only withholds credit rather than
  assigning blame, and the second asks whether a criterion parses, which is a fact about the file
  rather than a judgement about the assertion.

- 2026-08-13: `drydock score release` and `drydock build score` no longer compute a technical
  score. The seven model-emitted 0..100 dimensions, their average, the `< 80` and `< 60`
  completion blockers, and the `_coverage_penalty` discount are gone, along with the `score` and
  `dimensions` fields on `BuildScoreResult`, the `technical_score` key in the evidence record
  (`schema_version` 4), and the "Technical quality" table in `SCORECARD.md`. The gate is now every
  required Sea Trial's verdict and nothing else, so a project satisfying every criterion its
  Commander wrote can no longer be refused by an opinion — or by a different opinion on the next
  run. A release gate has to be reproducible. The model still judges `evidence` and `llm`
  criteria, which are the criteria that genuinely need judgement; `proof` and `measurement`
  criteria remain deterministic. This also removes the divergence in which `score release` applied
  a hardcoded rubric while `build score` resolved the `SEA_TRIALS.md` policy block.

- 2026-08-13: An agent's `AC_BROKEN` claim no longer terminates the repair loop. A criterion
  reaches the point of failing only when its oracle is derivable, so the agent's claim that the
  criterion is at fault is the less likely explanation, and a build in which the party under test
  can end its own examination is not a gate. The claim is still detected and reported as
  "recorded, not accepted"; the loop keeps its budget and stops on the ordinary stall rule.

### Fixed

- 2026-08-13: A governed acceptance gate exiting 2 is a kit fault, not a product failure.
  `run_gate` classified every non-zero exit as `FAIL`, so a gate script reporting a usage error —
  an unset variable, a bad argument, a conformance harness that is not the version the run named —
  was recorded as the product failing a test that never ran. Exit 2 now classifies as `ERROR`
  alongside an absent executable, a timeout, and a signal: it does not block, it is never charged
  to the build, and `score release` reports it as `Governed acceptance gate could not run` rather
  than `failed`. This follows `diff` and `grep`, where 1 is a legitimate negative answer and 2 is
  trouble, and it is the contract Drydock's own commands already state. A Commander-supplied
  command that means something else by 2 is now read as a kit fault, which is the safe direction:
  a kit fault never fails a release.

- 2026-08-13: The Toml UAT fixture's conformance harness runs. `sources/run_conformance.sh` probed
  the suite's identity with `toml-test -version`, which is not a flag the harness accepts: it
  printed general help, exit 0, and the version guard compared that help text against the expected
  `v2.2.0` and refused to run. The probe now uses the `version` subcommand, as
  `setup_harness.sh` already did. Every governed gate in the fixture routes through this script,
  so the failure surfaced as three failed layout acceptance criteria, `test` exiting 2, and a
  release blocked on `full: FAIL (exit 2)` — none of which concerned the decoder under test. The
  guard itself is unchanged: a harness that is genuinely the wrong version is still refused.

- 2026-08-12: A missing project-local executable in a pre-build acceptance observation no longer
  parks a finished story on an unanswerable authorization. `_MISSING_EXECUTABLE_RE` in
  `acceptance_requirements` excluded `/` from its capture but not the newline, so stderr naming a
  relative path — the artifact under construction, absent by definition before the build — forced
  the engine to backtrack past its own quotes and capture the following traceback as the tool
  name. `discover_missing_requirement` returned `AcceptanceRequirement("executable", <traceback
  text>, "test")`, which `record_requirement_decision` persisted as a blocking `DECISIONS.json`
  record; `synchronize_manifest_question_gates` then re-asserted that gate on every later pass and
  dragged the story back to `blocked/questions` from `closed/verified`, after the repair pass had
  driven both its checks green. A CommonMark run finished 655 of 655 conformance examples and its
  sole project acceptance criterion, then scored `INCOMPLETE` on `Manifest work is not
  closed/verified: block-quotes`. The capture is now confined to the failing line and
  `discover_missing_requirement` returns a requirement only for a bare command token, applying the
  rule `visible_external_usage` already used for declared commands: an executable starting with
  `.` or `/` is project-local, not external tooling a Commander must authorize. A genuine missing
  tool is still discovered and still blocks.

- 2026-08-11: `drydock plan` integrity validation reads acceptance criteria in the format the
  planning prompt mandates. `planning_session._acceptance_status` counted Markdown ` ```python `
  fences, which the delimited `=== AC <id> ===` container replaced, so every story scored zero or
  one criterion however many it actually carried and `plan` failed its own `Plan integrity check`
  with `N Programmatic Acceptance assertion(s)` on output that satisfied its own template — a
  CommonMark run wrote 10 of 10 Blueprints carrying 2 to 5 criteria each and was rejected at the
  gate. Every plan-time inspection of acceptance content now goes through
  `acceptance.parse_programmatic_acceptance_text`, the same authority the build engine executes,
  via a single `_acceptance_checks` helper: the criterion count, the imported-suite exemption
  (`_drives_external_suite`), and the unbounded-suite gate (`_invokes_unbounded_test_suite`).
  The unbounded-suite gate now judges one parsed criterion at a time against its own `Suite:`
  declaration instead of guessing scope from a line window, which had misread any proof body
  containing a fence or a heading. A test asserts the shipped `BLUEPRINTS_CONTRACT.md` example
  clears the validator's own `_MIN_ASSERTIONS_PER_STORY` minimum.
- 2026-08-11: A truncated diagnostic states what it hid. `errors._safe_detail` cut at a character
  offset, so an integrity failure enumerating one finding per story ended mid-word and gave no
  indication that further findings existed. The cut now lands on a line boundary and appends
  `… (N more lines truncated)`. The criterion-count message also names the specification files it
  measured rather than referring to "its implemented spec(s)".
- 2026-08-11: `drydock plan` no longer rejects every Blueprint batch that carries an acceptance
  criterion. The `=== AC <id> ===` proof block introduced with the delimited-criterion container
  reuses the `=== NAME ===` line grammar the artifact envelope already used for whole files, and
  the envelope parsers are flat — so a nested proof delimiter was read as an artifact boundary,
  orphaning its `=== END AC <id> ===` marker and failing the batch as `Rejected: malformed
  artifact response`. Because `BLUEPRINTS_CONTRACT.md` instructs the model to place criteria
  inside the Blueprint, every batch for every project failed deterministically and no retry
  budget could recover: a CommonMark run accepted `TOPOLOGY.md`, then rejected all three Stage 2
  passes with 0 of 19 Blueprints written. The envelope grammar now reserves the `AC` namespace
  via `artifact_blocks.RESERVED_BLOCK_NAMESPACE`, applied to every envelope pattern in
  `artifact_blocks`, `planning_session`, and `refit`; an artifact is a file, and no file is named
  `AC something`. A test parses the worked example out of the packaged `BLUEPRINTS_CONTRACT.md`
  and asserts it round-trips as one artifact holding two criteria, so the format the prompt
  mandates and the format the parser accepts can no longer drift apart. The guard covers every
  envelope pattern, not only the two that parse the response: `_HEADER_ANYWHERE_RE` decides
  whether a parsed body absorbed another artifact, and `plan_shape` measures response shape, so
  a Blueprint could parse cleanly and still be discarded as damaged. The reserved-namespace
  pattern absorbs an optional `END` itself, because a pattern spelling the end marker as
  `(?:END )?` backtracks that group to empty and otherwise matches `=== END AC <id> ===` under
  the name `END AC <id>`.

### Changed

- 2026-08-11: A UAT report states when the run happened in local time. The per-kit `README.md` and
  the aggregate summary carry a `Ran:` window rendered from `environment.started_at` /
  `finished_at` in the reader's timezone, alongside the UTC run id. A run id alone reads hours
  away from the wall clock the operator watched the run on, which made a report impossible to
  match to a session by eye.
- 2026-08-11: A build block's repair loop is bounded by progress rather than by a fixed call
  count. A pass that raises the deterministic acceptance score — a newly green criterion, or a
  non-regressing case tally that improves — earns another pass; consecutive passes that move
  nothing end the block. `config.max_consecutive_stalls()` is 1 interactively, so the first flat
  pass still ends a block, and 2 under `drydock uat`, where a single flat pass is often noise
  between two productive ones. This replaces `repair_through_stall()`, under which a UAT ignored
  stalls entirely and always spent its whole budget. The stall count is now the only behavior
  `DRYDOCK_UAT` changes inside the repair loop; no error class is suppressed for UAT that would
  gate interactively, and a test enforces that `is_uat_run()` has no other consumer.
- 2026-08-11: `drydock uat` allows a block 6 repairs, up from the interactive default of 3, and
  accepts `--repair-attempts` to change it. The bound is per build block, not per story: the
  repair loop runs once per `BuildUnit`. The previous fixed budget cut off converging work — in
  the CommonMark UAT, block 3 went 3/8 → 4/8 → 4/8 → 6/8 criteria and 83 → 101 → 109 → 126
  conformance cases across four calls without one stalled pass, exhausted its budget while still
  climbing, and left blocks 4 and 5 unbuilt because the build frontier is strict Manifest order.
  `full_test.sh` was therefore never written and the run's own test command failed to open it,
  so the conformance measurement the UAT exists to produce was never taken.
- 2026-08-11: A repair loop stops when every failing criterion is a kit fault — malformed check,
  absent declared tool, unavailable acceptance environment, exhausted memory or time — and names
  the ids. A repair pass rewrites the implementation, never the criterion or the machine it runs
  on, so these can never be driven green and the budget spent on them was always wasted.
  `acceptance.TERMINAL_FAILURE_PREFIXES` and `is_terminal_check_failure()` hold the
  classification beside the prefixes they name.
- 2026-08-11: A block that passes its acceptance only after more than four calls reports a
  `sizing:` advisory naming the block and its call count. Repeated repair to reach green is a
  decomposition signal about the Manifest rather than a build failure, so it is reported and
  never gated.
- 2026-08-11: Programmatic Acceptance criteria are authored in explicitly delimited
  `=== AC <id> === … === END AC <id> ===` blocks, replacing the inferred Markdown boundaries.
  The previous container extracted criteria with a non-greedy ` ```python ` regex, so a proof
  body containing a Markdown fence truncated at the inner fence and discarded the criterion
  after it; the fragment then raised `SyntaxError` in its own frame, which classifies as a
  malformed check, settles UNVERIFIED, and costs the story nothing — the criterion stopped
  gating and its story still closed verified. The criterion id now lives in the delimiter rather
  than being slugified from a nearby heading, declarations are the leading `Key: value` lines,
  and the body runs verbatim to the end marker, so a fence, a `##` line, a `###` line, or a
  `Requires:` line inside a string is inert. Blocks are scanned document-wide, so a `##` line in
  a proof can no longer close the `## Programmatic Acceptance` section. An unterminated block, a
  mismatched end id, a stray end marker, and a duplicate id are hard errors. The Markdown form
  still parses, so Blueprints authored before this change keep working. `BLUEPRINTS_CONTRACT.md`
  states the new form.
- 2026-08-11: `drydock score ac` reports a fourth verdict, `~ PREPASSED`, for a criterion that
  runs green but was also green at its block's baseline — before that block's code existed. Such
  a criterion has not shown that the story's work is what satisfies it; in the CommonMark UAT
  four of them (`leaf-blocks`, `containers`, `character-line-endings`, `character-insecure`)
  selected no conformance examples, exited zero, and printed `✓ PASS`, making the reported score
  12/28 where the proven score was 8/28. The build records its per-block baseline to
  `evidence/prepassed-acceptance.json` because only the build takes a baseline. It is reported
  and never gated: a criterion that exercises nothing and one measuring a deliverable that
  legitimately already existed are indistinguishable from the baseline alone, so failing on it
  would break correct builds. `PREPASSED` does not affect the exit code.
- 2026-08-11: A Programmatic Acceptance criterion that does not compile now fails
  `drydock validate` and `drydock plan` instead of warning. Whether a criterion is Python is a
  fact about the file, in the same class as a container parse error, and it is deliberately
  separate from the unsatisfiability analyzers, which stay advisory because they predict that a
  well-formed assertion cannot pass and that prediction carries a false-positive rate.
- 2026-08-11: `group_blocks` bounds a build block by the number of acceptance criteria it owes
  as well as by assembled token cost, capped at `DEFAULT_BLOCK_ACCEPTANCE_LIMIT` (5). Cost alone
  is a poor proxy for how much a block has to prove: the cheapest merge on offer is often two
  stories that each carry a full conformance section. In the CommonMark UAT that merged leaf
  blocks (4 criteria) with containers-and-lists (4) into one block owing 8 against a flat repair
  budget of 3; it reached 6, stopped third of five, and starved every block behind it, so the
  run produced no `full_test.sh` and every downstream verification step failed as a consequence.
  A story whose own criteria exceed the ceiling still builds as its own block — a marker, never
  a refusal — matching the existing `limit_tokens` behavior. Previously observed block shapes
  are unchanged.
- 2026-08-11: Imported source material reaches a prompt byte-for-byte. `prompt_chunks` sliced
  files at raw character offsets, cutting 15 of 17 chunk boundaries in `spec.txt` mid-line and
  delivering each severed line as two unrelated lines in two separately fenced blocks; the
  fenced-part builders in `prompt_assembly` called `.rstrip()`, destroying trailing spaces that
  are a CommonMark hard line break; and they emitted a fixed three-backtick fence against a file
  carrying 1427 lines that open with three or more backticks, including 655 thirty-two-backtick
  example openers that closed the wrapper early. Chunking now splits on existing line
  boundaries, and a fence is always longer than the longest backtick run in the body. Content
  without a three-backtick run still gets exactly three, so existing prompts — and their cache
  prefixes — are unchanged.
- 2026-08-10: UAT lifecycle inputs are explicit and reproducible. Kits may declare `sea_trials`
  and `technology_stack` paths in `uat.json`; discovery applies the same containment and existence
  checks as source/update paths, validates both artifacts before a run, seeds them after `init`,
  and preserves them under each run's `inputs/` proof bundle. Undeclared root filenames are no
  longer discovered implicitly, so omission delegates artifact generation to `analyze`. The three
  shipped kits now keep both declarations under `inputs/`, and generated reports inventory and
  link that bundle. CommonMark now has one blocking, deterministic project criterion: the complete
  supplied conformance suite, run by `sh full_test.sh`, must exit successfully.

- 2026-08-10: Every artifact a UAT report links is reached through a styled viewer instead of raw
  text. A report previously handed the reader off to the browser's own rendering the moment they
  opened a log, a transcript, or a Markdown document. `build_case_kit` and `write_kit_index` now
  generate a viewer page per linked text artifact under `view/`, mirroring the artifact's path,
  sharing one generated `assets/kit.css`: Markdown is rendered, anything else is shown as source,
  and each viewer links its raw file and the report it came from. Rendering is done by a new
  dependency-free `drydock.markdown_render`, which supports headings, fenced code, GitHub tables,
  nested lists, block quotes, rules, and inline markup, and keeps consecutive `Field: value` lines
  on their own lines so Drydock's typed artifacts survive rendering. `view/` and `assets/` are
  generated output: excluded from `SHA256SUMS` and the evidence manifest, and replaced on every
  rebuild. A published kit grows by roughly the size of its text artifacts.

- 2026-08-10: A UAT kit's `index.html` is a project page, and every completed run refreshes it.
  The kit landing page previously listed only the runs and hardcoded links to `README.md` and
  `uat.json`. It now inventories the governed documents actually present at the kit root
  (`SEA_TRIALS.md`, `TECHNOLOGY_STACK.md`, `USER_NOTES.md`, `LICENSE`, and any other kit file,
  excluding dotfiles), lists the `sources/` and `updates/` bundles with sizes, and links the newest
  run above the run table. A kit only ever links what it ships, so the page stays valid when
  published as its own repository. `drydock uat` now calls the new
  `uat_report.write_kit_index(<kit>)` after each run, so a run appears on its project page without
  a separate `drydock uat --report`; `--report` still rebuilds every run receipt and the page.

- 2026-08-10: An unproven project guardrail qualifies a release instead of failing it.
  `drydock score release` and `drydock build score` previously blocked completion on a guardrail
  whose verdict was `UNPROVEN`, conflating "evidence showed the prohibition violated" with
  "no evidence settled it either way". Only `BREACHED` blocks now. An unproven guardrail is
  reported as an attestation — a named check a human owes before release — and the gate reports
  a third state, `COMPLETE — MANUAL VERIFICATION REQUIRED`, exiting 0. Both scorers emit a new
  `attestations` list and `qualified` flag in `evidence/score-release.json` and
  `evidence/build-score.json` (`schema_version` 2 → 3), `SCORECARD.md` gains a
  `## Manual verification required` section, and the CLI prints `ATTESTATION REQUIRED:` lines
  distinct from `BLOCKER:`. `drydock uat` harvests the list from the Target's score evidence into
  `result.json` and renders it in the run `README.md` and `index.html`; run status is unchanged,
  because an unproven prohibition was never a failure of the run. Related: `score release` no
  longer counts a proof-verified guardrail toward required implementation/proof coverage, which
  restores the rule that guardrails require no story or proof reference. Guardrails are now
  graded on what their author claimed about them: `Verification: evidence` or `llm` declares the
  prohibition unprovable and carries no weight in `acceptance_criteria_coverage`, while
  `Verification: proof` or `measurement` declares it provable and is graded like any other
  assertion, so leaving it unbound scores as model opinion until a Programmatic Acceptance
  `Sea Trials:` reference reaches it. The motivating case was a ReadingList UAT run that built and
  tested clean, passed 27 of 27 acceptance criteria, and was failed at the release gate solely
  because no acceptance check declared `Sea Trials: st-003`.

- 2026-08-10: A story whose acceptance criteria were quarantined closes `closed/failed`, not
  `closed/verified`. Quarantine excludes a criterion from grading so no repair call is spent on
  something no implementation can satisfy, but the criterion was *removed*, not satisfied —
  closing the story verified counted it toward `manifest.verified`, which release scoring gates
  on, so a Blueprint defect could buy a release for a story nothing verified. The story now
  carries a `UNVERIFIED: acceptance criterion defective: <ids>` finding naming the Blueprint as
  the defect rather than the implementation, and the step result fails to match. `--ungate` does
  not recognise the marker: it records an operator decision to release a real red, while this
  one records a defect only a Blueprint repair can clear. `drydock uat` no longer runs its
  refit stages after a degraded build — a refit over a terminal partial build measures nothing,
  and its required steps could raise and rewrite the run as `failed`, destroying the degraded
  verdict. The staged-asset invocation rules moved from `prompts/plan_create.md` to
  `prompts/BLUEPRINTS_CONTRACT.md` so every prompt that authors or rewrites Programmatic
  Acceptance carries them.

- 2026-08-10: Three further classes of unsatisfiable acceptance criterion are caught
  statically, closing the defect family that failed the Toml UAT build on five consecutive
  runs. `proof_integrity.analyze_invocation` reports an `env=` dict literal carrying no
  `**os.environ` unpacking: it replaces the child environment rather than extending it, so the
  check runs with no `PATH` and grades a missing tool. A new `analyze_staged_invocation` reads
  the staged asset a criterion invokes, extracts the environment variables the asset's own
  unset-guard exits on, and reports a call that omits one — the requirement comes from the
  script, not from configuration, so the rule holds for any harness the Analysis stages. A new
  `analyze_shell_escapes` reports `printf '%s'` handed arguments containing `\n`: the format
  copies its argument verbatim, so the program under test is graded on input the author never
  wrote. `plan` strips all three, and `plan_create.md` now states the staged-asset invocation
  contract so fewer are authored in the first place.

- 2026-08-10: An unsatisfiable acceptance criterion is quarantined at build time rather than
  refusing the build. `build` previously raised `SpecificationError` and exited 1 on the first
  such criterion, which is unrecoverable in an unattended run: a repair pass may not rewrite a
  staged acceptance asset, so every rerun failed identically. The criterion is now excluded
  from the graded set, named on the console and in the failure report under `quarantined:`,
  and carried on the step result as `quarantined_acceptance`. A criterion that proved nothing
  no longer fails the block that owns it, and a Blueprint defect is no longer reported as an
  implementation defect.

- 2026-08-10: `drydock uat` continues past a failed build and reports the run as `degraded`
  instead of aborting it. A build that exhausts its repair budget has reached a terminal
  state, and the partial application, the scores over it, and the test command's verdict are
  the only record of how far Drydock got — discarding them lost the measurement the run
  exists to take. `UATResult` gains a `degraded` tuple naming each stage that fell short;
  `result.json`, the run receipt, and the kit index render `DEGRADED` as its own verdict,
  neither a pass nor a failure. A clean build whose test command fails is still a failed run,
  and its scores now run before the verdict is recorded.

- 2026-08-10: `proof_integrity.analyze_output_assertions` now reads the regular-expression form
  of an output assertion, not only `in` / `not in` comparisons. Its own remediation advice
  recommends rewriting a pinned tally as `re.search(r"\b0\s+failed\b", result.stdout)`, which
  moved the assertion into a call none of the existing rules could see. Two defects are caught
  in that form: a pinned nonzero count (`re.search(r"\b205\s+passed\b", ...)`) is reported as a
  hardcoded tally, and requiring a count of errors, skips or warnings in captured stdout
  alongside an exit-status assertion is reported as a *speculative tally* — only passes and
  failures are reliably tallied, and a runner with none of the others prints no such line at
  all, so `re.search(r"\b0\s+errors?\b", ...)` is false on a clean run. Both are fatal: planning
  strips the criterion and a build against an already-authored one refuses to start.
  `prompts/BLUEPRINTS_CONTRACT.md` no longer instructs the planner to require zero errors on a
  scoped suite or zero skips on the terminal full suite; the failure count is the only tally an
  assertion may require.

- 2026-08-10: A programmatic-acceptance failure report carries the output the check printed.
  The Block → Story → AC chain stated the failing assertion and the exit code but not the
  runner's own account of the run, so a reader could not distinguish a broken assertion from
  broken code without opening the evidence file. Up to twelve lines of captured stdout now
  follow the assertion under `observed output:`. The terminal renderer for a post-LLM failure
  also stops reflowing indented lines, which had been splitting the failing assertion across
  two lines mid-regex.

- 2026-08-09: Every surface that reports token usage — the per-call console line, the
  `drydock build` report table and its totals, the UAT run summary, and the UAT receipt —
  states `cached` and `uncached` instead of a total input with a cached subset. That is the
  split providers bill, so the two numbers a reader cares about no longer have to be derived
  by subtraction. Cache-hit rate and the Claude cache-write figure are unchanged.

- 2026-08-09: A UAT run identifier is now `20260809.204459` (UTC, to the second) rather than
  `20260809T204459.901240Z`. Two runs of one kit cannot start within the same second, so the
  microseconds bought nothing and cost legibility. Run ordering compares identifier digits, so
  directories written under the retired format still sort chronologically beside new ones and
  `--run` continues to accept them.

- 2026-08-09: The UAT receipt files the run's evidence as four directory trees — Build,
  Evidence, Sources, Workspace — one per directory a run writes, with paths stated relative to
  the kit (`runs/<run-id>/…`) and unprocessed output (`evidence/provider_raw/`,
  `evidence/prompt_outputs/`, `workspace/logs/`, `*.raw.jsonl`) marked `raw`. The workspace is
  now inventoried whole rather than only the Target subtree, so `SHA256SUMS` covers what the
  run actually left behind. Digests moved out of the page and stay in `SHA256SUMS`. A command
  or LLM result renders as an `OK` or `FAIL <code>` stamp instead of a printed exit code, the
  header names the directory the build delivered into, and the kit register carries the model
  each run used.

- 2026-08-09: The Toml UAT kit ships its scoring entry point instead of asking the build agent to
  transcribe it. `sources/full_test.sh` is a declared kit source, staged and hash-verified like the
  conformance harness it invokes, and `uat.json` scores with `sh sources/full_test.sh`. Staged
  assets land under the build directory's fixed `sources/` root, which is why the path moved off
  the application root. The kit loses an entire LLM block, the "path corrections are the only
  permitted edit" escape hatch, and the surface on which a build could weaken its own score — a
  modified entry point is now restored before grading rather than caught by review. The kit's
  Definition of Done no longer asserts absolute case totals (`210 valid, 499 invalid`, stale against
  the 205/474 the installed suite supplies); it requires every supplied case to pass with zero
  failed, errored, and skipped. `drydock uat` also asserts that a kit declaring a `sources/` scoring
  command ships that asset. The CommonMark kit keeps an agent-authored `full_test.sh`: its command
  names the program the build chooses, so it cannot be a static asset.

- 2026-08-09: `drydock uat --report` renders the run receipt (`uat/<kit>/runs/<run>/index.html`
  and the kit landing page) as a printed acceptance report rather than a web page: a white
  monospaced sheet with the Drydock mark inlined as a data URI, an APPROVED or REJECTED verdict
  stamp keyed to the recorded status, and the evidence filed into tabs — Steps, Error, LLM, Code,
  Sources, Blueprint. The Error tab appears only when a command exited nonzero, the LLM tab only
  when the run recorded an execution, and command logs are no longer inventoried a second time
  under their own table. A captured stream is linked only when it holds bytes, so an empty
  `stderr` renders as a dash: `stderr` carries provider progress on successful commands and its
  existence never implied a failure. Every evidence link opens in a new tab. Rendering only —
  the inventory, `SHA256SUMS`, and `result.json` contracts are unchanged, and an old run can be
  re-rendered in place.

### Added

- 2026-08-09: A build agent can end its own repair budget with an `AC_BROKEN: <check-id>` line
  when a declared acceptance criterion cannot pass however the code is written. Staged acceptance
  assets are restored before grading, so the agent is structurally unable to repair a broken
  assertion; without an escape hatch it spends every remaining call re-failing identically. The
  token is read from the response independently of `RESULT`, because the case that motivates it —
  correct code failed by a wrong assertion — is one the agent may legitimately report as `SUCCESS`.
  An unrecognized or absent id claims every currently failing check; a check that passed cannot be
  claimed. Drydock stops with `stop_reason` "acceptance criterion reported defective" and directs
  the operator to the assertion's source specification. The pre-existing prose inference remains as
  a fallback, now also reading `BLOCKERS` and recognizing "always fails", "cannot be satisfied",
  and "incorrectly reject".

- 2026-08-09: `proof_integrity.analyze_output_assertions` rejects an acceptance snippet that
  asserts a literal never appears in a command's captured output when that literal is tally
  vocabulary (`failed`, `error`, `skipped`, `warning`, and inflections). A test runner prints
  `N passed, M failed` on a clean run, so `assert "failed" not in result.stdout.lower()` is false
  on correct code and no implementation can move it. These fail `drydock validate` and are dropped
  as unsatisfiable before a build spends a repair pass. A substring assertion on any other literal
  beside an exit-status assertion warns instead: the exit status is already the verdict, and the
  substring models an output format the author may never have observed. Assertions tracked through
  a binding (`out = result.stdout`) are covered; a substring check that is the proof's only gate is
  left alone.

- 2026-08-09: `drydock uat --stage <stage>` resumes an existing run instead of starting a new one,
  re-entering the lifecycle at `import`, `analyze`, `plan`, `build`, `refit`, `test`, or `score`.
  A run directory already owns its Drydock workspace and build tree, so a lifecycle that failed
  late is retried without paying for the earlier LLM passes again. The newest run of each selected
  kit is resumed by default; `--run <run-id>` selects an older one and requires `--stage`. Resuming
  past `import` leaves the source bundle as the prior attempt left it, evidence log numbering
  continues past the existing files rather than overwriting them, and the earlier attempt's
  commands are carried into `result.json`. A resumed run records `resumed_from` and its receipt
  states the re-entry stage rather than claiming every command exited `0`, because a resumed run
  reuses prior state and is not a clean-room measurement. Each stage declares the Target artifact
  it consumes, so a resume into a stage the prior attempt never reached fails immediately with the
  missing artifact and the stage that produces it — `--stage build` after a failed `plan` reports
  the absent `MANIFEST.md` and directs the operator to `--stage plan` rather than running a status
  check and a completion gate to discover the same thing.

- 2026-08-09: A UAT fixture declares its own technology stack by shipping a `TECHNOLOGY_STACK.md`
  in its fixture directory. `drydock uat` seeds that file into the Target between `init` and
  `analyze`; because `analyze` never overwrites an existing Technology Stack, the declaration
  becomes the decision of record and `plan` reads it as the sole stack authority. The stack is
  configuration rather than a command-line argument — there is no `--stack` flag. Fixture
  discovery validates the declaration against the Rigging catalog and fails with exit `2` on an
  unknown Rigging filename or an empty table, so a typo surfaces before the run spends tokens. A
  fixture with no such file behaves exactly as before and lets `analyze` propose the stack.

- 2026-08-08: `drydock uat` now emits a self-contained, verifiable proof kit for every run. Each
  project case gains an `index.html` receipt that links every lifecycle command to its own captured
  stdout and stderr, quotes the failing stage's output verbatim, and tabulates each LLM execution
  beside the exact prompt, model output, and raw provider transcript that produced it. A run-level
  `index.html` states the aggregate verdict and links to each case. `SHA256SUMS` covers the
  delivered code, imported sources, Blueprint, command logs, and LLM evidence, so a checked-in kit
  is validated with `sha256sum -c SHA256SUMS`. The verdict is derived from recorded exit codes, so
  a failed lifecycle renders as `FAILED` and cannot present as a clean run.
- 2026-08-08: `drydock uat --report [<run>|all]` rebuilds the proof kit for a completed run without
  re-executing it, which also backfills receipts for runs recorded before this capability existed.

### Changed

- 2026-08-09: `drydock uat` streams each child command's output to the console as it is produced
  instead of reporting one stage name per step. The runner replaced `subprocess.run(capture_output)`
  with a `Popen` tee: raw bytes go to the evidence log unaltered while decoded text reaches the
  terminal on every read, so a run that takes minutes per step shows progress rather than silence.
  Child output is reproduced faithfully — carriage-return redraws and lines without a trailing
  newline pass through, since the `│` (stdout) / `!` (stderr) gutter is inserted only at a line
  start. Each step is framed by a header carrying the kit, stage, argv, and wall clock, and a
  footer carrying the exit code and elapsed time; the run ends with the per-kit summary that was
  previously written but never displayed. Children run with `PYTHONUNBUFFERED=1` so pipe buffering
  cannot withhold output until exit. `--quiet` restores the previous stage-name-only reporting.
  Evidence content is unchanged either way.

- 2026-08-09: The TOML conformance fixture is a Go project. Its `TECHNOLOGY_STACK.md` names
  `go.md` and `common.md`; `full_test.sh` compiles `./cmd/toml-decoder` as a step distinct from
  scoring, so a compilation failure and a conformance failure are separable in the evidence; and
  `run_conformance.sh` now requires `DECODER` instead of defaulting to a Python command, which
  removes the implementation language from the scoring instrument. The Go toolchain was already a
  prerequisite because the upstream `toml-test` harness is written in Go, so the deliverable and
  the instrument now share one toolchain. `Rigging/stack/go.md` sets Go 1.22 as a hard floor with
  a verification snippet and instructs the builder to stop and report a blocker rather than
  degrade the code to compile on an older toolchain; 1.22 changed loop-variable scoping, so an
  older compiler changes behavior silently rather than failing to build.
- 2026-08-08: UAT reports are portable. `result.json`, `summary.json`, and `SUMMARY.md` now record
  paths relative to the run or case directory instead of the generating machine's absolute paths,
  and `evidence/manifest.json` carries the artifact inventory and run provenance. Each result
  records the Drydock version, repository commit, provider, model, effort, Python version, platform,
  and start and finish timestamps. Regenerable `__pycache__` and tooling caches are pruned before a
  kit is inventoried, so a run directory can be committed to another repository as delivered
  evidence.

### Removed

- 2026-08-08: Deleted the last executable remnants of the Blueprint Markdown question surface. The
  Build Compass no longer parses `## Questions` sections or renders per-question "Save answer"
  controls, so the compass step card presents a Blueprint source editor directly instead of hiding
  it behind a question group that only appeared for documents containing questions. The retired
  `POST /api/build-question/answer` and `POST /api/plan-feedback` endpoints, which returned HTTP 410
  since the `DECISIONS.json` cutover, are gone along with their request models and client scripts;
  callers must use the `DECISIONS.json` endpoints. The `drydock.questions` and
  `drydock.plan_feedback` modules, whose only remaining consumers were that dead renderer and their
  own tests, are removed. `drydock.question_gates` — which projects blocking `DECISIONS.json`
  records onto Manifest story states — is unaffected.

### Fixed

- 2026-08-10: `sha256sum -c SHA256SUMS` verifies a UAT run receipt cleanly. `build_case_kit`
  rewrote `evidence/manifest.json` after taking its checksum, so verification reported that one
  file `FAILED` on every kit Drydock has published. The manifest is now written before the
  inventory is sealed and re-hashed afterwards, and it no longer lists its own digest among its
  artifacts — a file cannot index itself.

- 2026-08-09: A build step whose observed file delta is empty no longer skips acceptance grading
  when the block declares Programmatic Acceptance. `_written_files` compares content hashes, so a
  step that rewrites an already-correct deliverable with identical bytes reported zero changes and
  was classified `no build files written` — a terminal status that short-circuited the acceptance
  run, which in turn discarded the agent's `AC_BROKEN` report, the one signal that ends a repair
  loop against a criterion nothing can satisfy. The classification is now advisory whenever the
  block has criteria to measure: the deterministic gate decides, and a defective-criterion claim
  stops the loop on the first call instead of consuming the budget behind a misleading cause. With
  no criteria, an agent that changed nothing still fails terminally. Observed on `drydock uat Toml`,
  where a correct decoder and a correct scoring script were reported as an unpersisted artifact.

- 2026-08-09: `proof_integrity.analyze_output_assertions` now also rejects the positive form of the
  tally defect: an acceptance snippet requiring an exact runner tally to appear in captured stdout,
  such as `assert "valid tests: 210 passed, 0 failed" in result.stdout`. The case count belongs to
  the installed suite rather than to the specification, and runners column-align their summaries
  (`valid tests: 205 passed,  0 failed` carries two spaces), so the literal is false on correct code
  as soon as either drifts, for two independent reasons. The defect is fatal: `drydock validate`
  reports it, planning strips the criterion, and a build refuses to start rather than spend its
  repair budget on it. Only a literal carrying a tally is rejected — an ordinary required substring,
  the same literal asserted against stderr, and a whitespace-tolerant regular expression are all
  left alone. `prompts/BLUEPRINTS_CONTRACT.md` now teaches `re.search(r"\b0\s+failed\b", ...)` in
  place of `assert "0 failed" in result.stdout`.

- 2026-08-09: The Programmatic Acceptance declaration gate no longer treats the POSIX shell and the
  Python interpreter as undeclared external tooling. `visible_external_usage` flagged every literal
  `subprocess` executable, so a conformance check that shelled out through `sh` failed planning with
  `undeclared executable=sh` even though `shutil.which` would have authorized it instantly. `sh`,
  `bash`, `env`, `python`, and `python3` are now baseline substrate and require no `Requires:`
  declaration; every other executable still must be declared and Commander-authorized.

- 2026-08-09: Build-asset staging is now closed over what the staged files reference. Previously
  only the sources the Analysis marked `stage` reached `<build_dir>/sources/`, so a conformance
  harness whose declared dependency was classified `prompt-only` arrived on disk without the
  installer it shells out to, and the build failed at its first story with a missing input.
  `declared_build_assets` now scans each staged file for the names of its non-Markdown siblings
  and stages the transitive closure, enforcing in code the rule `prompts/analyze.md` had asked of
  the model. Markdown remains prompt material and is never staged. Scoring inherits the closure
  unchanged, since staging and score-time verification read the same declaration.

- 2026-08-09: The build prompt now names the files present on disk in the build directory. The
  staged set was computed but never surfaced, leaving the agent to infer its own working directory
  from imported prose; an agent that read "the imported source files are placed in a `sources/`
  subdirectory" reported its own fenced Markdown context as missing inputs and halted. Both the
  per-story and per-block prompts carry a `Files on disk in the build directory` block listing the
  staged paths and stating that every other file named in the prompt is context, not a missing
  input. The block is omitted when nothing is staged.

- 2026-08-09: `drydock uat` now spends the full `--repair-attempts` budget on a block whose
  acceptance score stops improving. Interactively, one repair pass that moves no acceptance
  criterion still ends the block — the operator should not pay for a model that is spinning — but
  a UAT measures what Drydock delivers at the full budget, and a fixture that would converge on a
  later call was being scored as a methodology failure. `drydock uat` marks every child command
  with `DRYDOCK_UAT`; the build reports the flat pass on the console and continues rather than
  recording a stop reason. A criterion the agent reports as defective remains terminal in both
  modes, because staged acceptance assets are restored before grading and no later pass can move
  it.

- 2026-08-08: Plan integrity now rejects `Suite: scoped` Programmatic Acceptance that requires
  `0 skipped`. A scoped conformance invocation deliberately excludes tests owned by other stories;
  only the terminal `Suite: full` story may use zero skipped as whole-suite completion evidence.

- 2026-08-07: Restored a green verification run. The test suite still asserted the Blueprint
  Markdown question surface retired on 2026-08-02, so 27 tests described behavior that no longer
  existed; gate, authorization, build-decision, and Commander-guidance coverage is now expressed
  against `DECISIONS.json`, and the Sea Trials question projection is asserted as retired. Three
  further CI-only failures are closed: `pyproject.toml` declares `pythonpath = ["."]` so tests that
  import sibling test helpers work under `uv run`, the `logs/` replay fixture consumed by the
  MANIFEST parser test moved to `tests/fixtures/` because `logs/` is not committed, and
  `validation/bin/*.sh` carry the executable bit in Git so `validation/bin/run_validation.sh` finds
  its case scripts on a clean checkout.

### Changed

- 2026-08-07: GitHub Actions verification now uses one Ubuntu/Python 3.12 job instead of repeating
  the full suite across three Python versions and two operating systems. The single job retains
  lint, formatting, tests, and clean wheel installation checks while removing unenforced coverage
  collection and the slow Windows compatibility matrix from every push and pull request.

### Added

- 2026-08-08: `drydock uat` now writes a per-fixture `evidence/` bundle on both successful and
  failed runs. It preserves every lifecycle command's stdout and stderr, copies LLM prompts,
  prompt outputs, provider-raw transcripts, and `llm.jsonl`, and indexes those artifacts with
  relative paths, byte counts, and SHA-256 hashes in `evidence/manifest.json`. The lifecycle also
  captures `build status <Target>`, `status <Target>`, and workspace-wide `status` views after
  planning, refitting, and each completed build stage so the evidence shows state transitions as
  well as command outcomes.

- 2026-08-08: UAT fixtures can declare fixture-local source files and a deterministic post-build
  `test_command` in `uat.json`. Fixtures now declare a nonempty source bundle and ordered updates
  explicitly instead of relying on `spec_N.md` filename semantics. Drydock assembles a flat,
  isolated import root so nested fixture organization cannot alter the build's `sources/<basename>`
  contract; updates replace that staged source before the real `import --update` and refit flow.
  The CommonMark fixture carries its complete upstream conformance kit and gates the completed
  application by running `sh full_test.sh` from its root. Vendored UAT inputs are excluded from
  Drydock's Ruff scope so project lint does not rewrite or impose local style on upstream test kits.

- 2026-08-07: `drydock uat [<Project>]` runs known project fixtures as isolated, timestamped,
  unattended builds using one configured model and provider. Ordered `tests/uat/<Project>/spec_N.md`
  inputs exercise both the initial lifecycle and subsequent `import --update` → `refit --sources`
  incremental rebuilds; the first fixture is ReadingList, derived from the prior helper scripts.
  Each run preserves child-command transcripts and emits Markdown/JSON summaries with wall time,
  LLM time, token/cache usage, build-pass counts, and advisory `score ac`, `score build`, and
  `score release` results. Score failures are reported but do not mask whether the build lifecycle
  itself completed.

- 2026-08-07: `drydock plan --override` and `drydock build --override` waive the gates that wait
  on a human answer — unanswered Analyze questionnaire decisions marked `required_before_plan`,
  blocking `DECISIONS.json` records that park a story at `blocked/questions`, and acceptance
  prerequisites awaiting Commander authorization. Each waiver is recorded rather than skipped: the
  command prints an `OVERRIDE SUMMARY` naming every bypassed gate, and the Target's `METADATA.md`
  gains `override: true` and `override_waivers: <n>` so a waived run cannot later be mistaken for
  a governed one. A blocked analysis (`BLOCKERS.md`, `Quality: Blocked`) is deliberately not
  waivable, because on a source the author controls that verdict is a regression signal about the
  source rather than an interruption. The flag takes no sub-options; a selectable severity list
  would make the flag itself part of the test surface. Note that an override build may reach for
  an undeclared external prerequisite and is therefore not hermetic.

- 2026-08-07: `drydock config env [<Target>]` prints resolved paths as shell `KEY=value`
  assignments for `eval "$(drydock config env <Target>)"` — `DRYDOCK_WORKSPACE`,
  `DRYDOCK_TARGETS_ROOT`, `DRYDOCK_BUILD_DIRECTORY`, and, when a Target is named,
  `DRYDOCK_TARGET`, `DRYDOCK_TARGET_DIR`, and `DRYDOCK_TARGET_BUILD_DIR`. The Target need not
  exist, so a driver that clears and regenerates one can learn its paths first. Like
  `status --check/--ready`, the output is masthead-free; values are shell-quoted.

- 2026-08-07: `helpers/autotest_ReadingList.sh` drives the full pipeline unattended as a
  pre-release regression build: it clears the Target and build directory, runs
  init → import → analyze → plan → build with `--override`, loops `build` under a
  `status --ready` guard with a pass cap, and asserts completion with `status --check`. It
  hardcodes no paths, taking them from `config env`, so a copy covers another Target.

- 2026-08-07: `drydock status console` reports how the current terminal was classified — platform,
  stream encoding, `TERM`, console host, resolved glyph tier, colour — and prints a sample line of
  every tier past the tier wrapper, so a terminal that cannot render a glyph shows it. One command
  and one screenshot now diagnose any icon complaint.

- 2026-08-07: `drydock --glyphs <emoji|text|ascii|auto>` and `DRYDOCK_GLYPHS` override console
  detection by naming a tier. `--ascii` and `--unicode` remain as aliases for the bottom and top
  tiers. An override replaces the terminal heuristic but never the encoding limit: forcing emoji
  onto a `cp437` stream would reintroduce the `UnicodeEncodeError` the detection exists to prevent.

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

- 2026-08-07: Status icons and shell markers now render correctly on terminals that previously
  showed boxes or escape sequences. Four defects, each independently sufficient to break output:
  the MSYS/MinGW rule was gated on `isatty()`, which is false for a Git Bash terminal under a
  native Windows Python, so the rule never fired for the host it was written for; console output
  defaulted to its richest form on any unrecognized terminal, and a UTF-8 encoding is not evidence
  of an emoji font, so unknown hosts got glyphs they could not draw; an auto-detected downgrade was
  never published to the environment, so subprocesses and the LLM runner rendered differently from
  their parent; and ANSI colour was written whenever stdout was a terminal, which prints a literal
  `←[32m` on a Windows console without virtual terminal processing enabled.

  Output is now resolved to the richest of three tiers the terminal is *known* to support — `emoji`
  (`✅`), `text` (`✓`, the default for any unrecognized host), or `ascii` (`v`) — capped by what the
  stream's encoding can carry. Nearly every glyph Drydock prints is a single-width symbol that
  survives at the `text` tier, so the icons stay.

- 2026-08-07: Subprocess output is decoded as UTF-8 rather than as the system locale encoding.
  `text=True` without `encoding=` decodes with `cp1252` on Windows and `ascii` under `LANG=C`, so a
  streamed LLM transcript containing any non-ASCII character arrived as mojibake or raised
  `UnicodeDecodeError` — before any console handling could apply. Fixed at every call site, with a
  contract test that fails if a new one omits it.

- 2026-08-06: Standoff diagnosis no longer calls an LLM for deterministic operating-system
  exceptions. Missing files, denied permissions, incorrect path types, existing destinations, and
  related `OSError` failures now return their direct error immediately; unexpected programming
  exceptions and opaque post-LLM failures remain eligible for diagnosis.

- 2026-08-06: Three defects that together made a source change silently vanish between
  `import --update` and the Manifest. `refit --relineage` marked every version it replayed from git
  `consumed`, but `import --update` commits the snapshot it imports, so a version awaiting a refit
  sat in history and relineage claimed it had produced work it never produced; replay now preserves
  the pending state the existing `LINEAGE.json` records, and only genuinely unknown versions
  default to consumed. `refit --sources` injected the compact Blueprint into the routing prompt
  while validating amended section names against the authored Blueprint — the compact form is a
  prose digest carrying no headings, so an `amending` story could only invent a heading and fail
  the whole refit with `Ticket amends sections absent from <Blueprint>`; the authored headings are
  now injected as a `sections` attribute the model copies from. Routed stories land in a new
  computed block, and `refit --sources` did not update the Manifest `blocks:` count, leaving the
  Manifest it had just written unloadable with `Manifest blocks count does not match computed
  blocks`; the count is now recomputed before save.

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

- 2026-08-06: Programmatic Acceptance validation now caches installed Python distribution
  metadata, Target environment package inventories, dependency manifests, Technology Stack text,
  and parsed Blueprint acceptance for the duration of a Drydock workflow. Target package
  inventory is explicitly invalidated after `uv sync --locked`; `DECISIONS.json` remains
  live-read. This removes repeated high-latency metadata and specification traversal during Plan,
  Build, and Score, particularly on Windows-mounted filesystems under WSL.

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
