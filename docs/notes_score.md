# NOTES: score

| Field | Value |
|-------|-------|
| Version | 2026-08-21 V1 |
| Route | score |
| Status | Working notes — not canonical specification |
| Description | Closing out `build_score` and reshaping `drydock score`'s five commands into a stamped, self-approving final gate persisted on `SCORECARD.md`. |
| Pending spec | 5 approved items |
| Pending impl | 2 unimplemented sections (state ladder dropped, superseded by per-command stamps) |

## Goal

Understand and redesign the project close-out workflow: what each `drydock score` sub-command
verifies, retire the dead `build_score` path, and make every score command stamp an approval onto
a single shared `SCORECARD.md` that becomes the project's retrospective and final release gate.

## Decisions

### Remove `build_score` entirely
`2026-08-21` · `spec:approved` · `impl:implemented`

Implemented with a twist on the original plan: rather than keeping `build_score.py` as a module of
surviving primitives, Ed asked that they move into `score.py` (their only remaining caller) and
`build_score.py` be deleted outright. Done: `score.py` now defines `MEASUREMENT_TIMEOUT`,
`CompletedRun`, `RunnerFn`, `TextCallback`, `MeasurementResult`, `CriterionResult`, `_sha`, `_git`,
`_code_identity`, `_compare`, `_measurement_payload`, `_compare_measurement`, `_evidence_fact`,
`_parse_json` directly. `build_score.py`, `prompts/build_score.md`, and `tests/test_build_score.py`
are deleted. `cmd_build_score`, the `drydock build score <Target>` CLI branch, and the "Build score
evidence" line in `drydock build status` are removed. `README.md` updated to match.

Confirmed dead: never run by the user, and prompt comparison shows `score_release.md` (V6) is a
strict evolution of `build_score.md` (V4) — same verdict shape, same `notation` clause, guardrail
handling deliberately simplified in `score_release`, staleness handling and citation discipline
added. Nothing in the old prompt is missing from the new one; this is a straight removal, not a
merge.

Remove:
- `cmd_build_score`, `score_target`, `gate_label`, `score_evidence_state` (`src/drydock/build_score.py`, `cli.py`)
- the `drydock build score <Target>` CLI branch (`cli.py` ~3912-3924)
- `prompts/build_score.md` (and its `prompts.json` registry entry)
- the `Build score evidence: none/stale/current` line in `drydock build status` (`cmd_build_status`,
  `cli.py` ~3071-3073) — its only reader, now gone
- `evidence/build-score.json` production

Keep: `build_score.py`'s deterministic primitives (`CriterionResult`, `MeasurementResult`,
`_sha`, `_compare_measurement`, `_evidence_fact`, `_measurement_payload`, `_parse_json`,
`_code_identity`, etc.) — `score.py` imports these directly and they have no dependency on the
removed LLM path.

### Score command roles (help text)
`2026-08-21` · `spec:approved` · `impl:implemented`

Rewrote `drydock score --help` for `spec`, `ac`, `build`, `release`, `report`. Note: `score build`
still exits 1 on missing evidence or unverified blocks — Ed confirmed leaving that as-is rather
than making it purely informational; the help text describes current pass/fail behavior, not the
"not pass/fail, just present" framing originally drafted in this note.

Fix the definitions of each `drydock score` sub-command in its `--help` text:

| Command | Role |
|---|---|
| `ac` | Sum of story-level acceptance criteria; may include a final project-AC verify step |
| `release` | Sea Trials; definitely includes a run of the project AC |
| `build` | Informational LLM usage report — not pass/fail, just present |
| `report` | Publishes the build evidence (`drydock_receipt/`) |
| `spec` | Finds flaws in the imported spec and asks questions |

### State ladder for close-out
`2026-08-21` · `spec:na` · `impl:na`

Dropped. Ed: the ladder is superseded by each score command's own stamped state (see "Every score
command issues a stamped approval" below) — no separate ladder field is needed.

Progressive states beyond today's bare `PLAN CREATED` / `FAIL` / attempt-N line:
`build complete` → `build/ac complete` → `build/delivered` (release approved).

**Open:** whether this ladder is a field stamped onto the retrospective document itself, or
replaces/augments the target's `State:` line that `drydock score <target>`'s dashboard prints
today. Not resolved this session — see Open Questions.

### Every score command issues a stamped approval
`2026-08-21` · `spec:approved` · `impl:unimplemented`

Reframe `release`'s output from a single gate verdict into a **retrospective**: project type,
scorecard notations for failed ACs and other flagged areas, material drawn from `DECISIONS.md`
(`decisions.py`, `DECISIONS_FILENAME` — a real existing Target artifact, not new).

Beyond `release`, every score command (`spec`, `ac`, `build`, `release`) issues its own approval
and stamps it onto the shared document with attribution, verb, and timestamp — e.g.
`released\nscore release · 2026-08-21 20:14`. Reuse `report_render.py`'s existing `.stamp`
CSS/`_letterhead` mechanics, extended from one verdict per document to multiple stamps.

Ordering: `SCORECARD.md` need not exist for the build to proceed, but it must be written before
`report` publishes the receipt over it, and an unwritten `SCORECARD.md` cannot be a final
approval.

### `SCORECARD.md` becomes a fully-regenerated render
`2026-08-21` · `spec:approved` · `impl:unimplemented`

Resolved fork: `SCORECARD.md` is the single persisted document (the only other candidate,
`ACCEPTANCE.json`, was rejected — plain markdown sections, kept clean). Today only `score_release`
writes it, wholesale (`score.py:930`, `_render_release_scorecard` takes no existing-file input —
confirmed this would silently clobber any other command's section under the old plan).

Chosen design instead: **`PROJECT_STATUS.jsonl` stays a thin, unchanged, append-only fact log**
(label, passed, at, detail, command, attempts — its current shape, one line per lifecycle rung).
`SCORECARD.md` is never hand-appended by individual commands; instead every score command run
**fully regenerates** `SCORECARD.md` from the journal (which stamps ran, when, pass/fail) plus
each command's own evidence file (`evidence/score-release.json`, AC evidence, build evidence,
`DECISIONS.md`) for the rich content — narrative, notations, project type. Same pattern
`drydock_receipt/` already uses (assemble fresh from many sources each run), so no merge logic is
needed and no writer can lose another writer's section.

`score report`'s write target is unchanged: `drydock_receipt/` (index.html, workspace snapshot,
record JSON). It continues to read `SCORECARD.md` as one embedded input, not write it. Its current
two independent verdict channels — the `LABEL_LADDER`/`_workflow_state()` stamp and the separate
`_receipt_checks()` exit-code table — are unaffected by this change unless revisited separately.

## Acceptance Criteria

- `drydock build score` no longer exists as a CLI command; `drydock build status` no longer prints
  a "Build score evidence" line.
- `drydock score --help` and each sub-command's help text state the five roles above accurately.
- Every score sub-command run (`spec`, `ac`, `build`, `release`) leaves a stamped entry
  reconstructable in `SCORECARD.md` the next time any score command regenerates it.
- `SCORECARD.md` regeneration never loses a stamp or section contributed by a run of a different
  score command, because it is rebuilt in full from `PROJECT_STATUS.jsonl` + evidence files rather
  than partially overwritten.

## Guardrails

- Do not extend `PROJECT_STATUS.jsonl`'s schema to carry narrative content — it stays a thin fact
  log; rich content lives in each command's own evidence file, joined at render time.
- Do not give `SCORECARD.md` a hand-merge/append write path — full rebuild only.

## Open Questions

- Does the `build complete` / `build/ac complete` / `build/delivered` state ladder live as a field
  on the retrospective document, or does it replace/augment the `State:` line
  `drydock score <target>`'s dashboard prints today (i.e. does reaching `build/delivered` change
  what every future `drydock score` call shows at the top, not just the retrospective)?

## Not in scope yet

- Whether `score report`'s two independent verdict channels (`LABEL_LADDER` state vs.
  `_receipt_checks()`) get unified now that `SCORECARD.md` carries richer stamped state.
- Exact rendering/layout of the tab-style, stamp-per-section `SCORECARD.md` — deferred to
  implementation; "keep it clean, normal markdown sections" is the only constraint set so far.
