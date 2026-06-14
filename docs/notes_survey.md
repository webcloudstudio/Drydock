# NOTES: Survey

| Field | Value |
|-------|-------|
| Version | 2026-06-14 V2 |
| Route | survey |
| Status | Working notes — not canonical specification |
| Description | Design and implementation reference for drydock survey: scoring model, data layout, AC file format, and feedback loop. |
| Pending spec | 3 recommended items |
| Pending impl | 0 unimplemented sections |

## Goal

Score a Target's build process and its specifications against per-command acceptance criteria,
and emit generalized, actionable fixes the next iteration can apply.

`drydock build score` scores the delivered *product* against the Blueprint (seven dimensions →
`SCORECARD.md`). `drydock survey` scores the *process/spec quality* (five dimensions →
`scores.jsonl`). Same instrument pointed at different things; survey may in time subsume the scorecard.

## Decisions

### Command Surface
`2026-06-13` · `spec:recommended` · `impl:implemented`

```text
drydock survey <Target>                     # render the latest scoreboard (deterministic, no LLM)
drydock survey <Target> --run               # score each command (LLM-assisted) and append results
drydock survey <Target> --import <path>     # re-read a Blueprint/sources dir and regenerate AC files
drydock survey <Target> --command <name>    # filter render/run/score to one command
drydock survey <Target> --raw               # print raw score records as JSON
```

| Flag | Effect |
|------|--------|
| *(none)* | Render the scoreboard from `scores.jsonl`. Cheap, deterministic, safe default. |
| `--run` | Assemble AC + artifacts, run the LLM scorer, compute scores, append one record per command, then render. |
| `--import <path>` | Read `<path>/*.md`, regenerate `survey/ac/SURVEY-<command>.md`, exit. |
| `--command <name>` | Substring filter on the command name; applies to render and run. |
| `--raw` | Emit records as JSON lines instead of the scoreboard. |

Exit codes: `0` success, `1` operational failure (missing AC dir, LLM failure), `2` usage error
(missing `<Target>`).

Implementation note: `--command` uses `dest="command_filter"` — a bare `--command` collides with
the top-level subparsers' `dest="command"` and silently nulls the dispatched command.

### Data Layout
`2026-06-13` · `spec:recommended` · `impl:implemented`

```text
targets/<Target>/survey/
  README.md                    charter + feedback loop
  RUBRIC.md                    human description of the scoring function
  CHECKLIST.md                 phase deliverables, each with a check type and status
  STATE.md                     resume point: scoreboard, top actions, surveyed commit
  scores.jsonl                 append-only score log (one record per command per run)
  ac/SURVEY-<command>.md       per-command acceptance criteria (the standard being scored)
  reviews/SCRUM-<artifact>.md  Scrum Master roadmap ranking
```

`scores.jsonl` is append-only; never rewrite a prior line. Its first line is a
`{"type":"meta",...}` schema marker that readers skip.

### AC File Format
`2026-06-13` · `spec:recommended` · `impl:implemented`

The standard each command is scored against. One file per command.

```markdown
# SURVEY-SPEC: drydock <command>

| Field   | Value |
|---------|-------|
| Command | drydock <command> |

## Goal
<one distilled paragraph — what success means>

## Acceptance Criteria — Code
| ID | Criterion | Dim | Check | Weight | Verify |
|----|-----------|-----|-------|--------|--------|
| STATUS-C1 | … | D1 | A | 2 | how to check |

## Acceptance Criteria — Specification
| ID | Criterion | Dim | Check | Weight | Verify |

## Guardrails
## Open Questions
```

Parser (`survey.parse_ac_file`) keys off the `# SURVEY-SPEC:` H1 for the command name, the
`## Goal` section, and any table row whose first cell matches `^[A-Z][A-Z0-9]*-[A-Z0-9]+$`.
Columns: `ID | Criterion | Dim | Check | Weight | Verify`.
`Check` is `A` (assertion) or `J` (judgment); `Dim` is `D1`–`D5`; `Weight` is a number.

### Scoring Model
`2026-06-13` · `spec:recommended` · `impl:implemented`

Deterministic and owned by the command (`src/drydock/survey.py`). The LLM only judges each AC
(`pass` / `partial` / `fail`) and writes recommendations; the module computes the numbers.

**Five dimensions, fixed weights:**

| Dim | Weight | Measures |
|-----|--------|----------|
| D1 | 0.30 | Behavioral correctness (code AC) |
| D2 | 0.25 | Specification quality (spec/artifact AC) |
| D3 | 0.20 | Process integrity (guardrails, unresolved uncertainty) |
| D4 | 0.15 | Evidence & reproducibility |
| D5 | 0.10 | Contract conformance (names, paths, exit codes) |

- Result value: `pass=1.0`, `partial=0.5`, `fail=0.0`.
- Dimension score = `100 × Σ(weight·value) / Σ(weight)` over that dimension's assessed AC.
- Composite = weighted mean of assessed dimensions, redistributed across only the assessed dimensions.
- `provisional = true` when not every dimension that has AC was assessed.

**Bands:** `SEAWORTHY` ≥ 90 · `SEA_TRIALS` ≥ 75 · `TAKING_WATER` ≥ 60 · `DRY_DOCK` < 60.
A `guardrail-breach` or `regression` flag caps the band at `TAKING_WATER` regardless of score.

**Root-cause flags:** `guardrail-breach`, `unresolved-uncertainty`, `contract-drift`,
`missing-evidence`, `decomposition-defect`, `regression`, `incomplete`.

**`scores.jsonl` record (schema 1):**

```json
{
  "schema": 1,
  "recorded_at": "2026-06-13T00:00:00",
  "command": "drydock status",
  "surveyed_commit": "cae9e8f",
  "run_ref": "<execution_id> | manual",
  "dimensions": { "D1": 75, "D2": null, "D3": null, "D4": null, "D5": 25 },
  "assessed": ["D1", "D5"],
  "score": 62,
  "band": "TAKING_WATER",
  "provisional": true,
  "flags": ["contract-drift", "incomplete"],
  "ac": [{ "id": "STATUS-D2", "result": "fail", "note": "reads BUILD_PLAN.md" }],
  "actions": ["Route plan-state reads through one loader so artifact renames propagate"]
}
```

### Module Internals
`2026-06-13` · `spec:na` · `impl:implemented`

`src/drydock/survey.py`:

| Function | Role |
|----------|------|
| `survey_dir_for(target_dir)` | `<target>/survey` |
| `parse_ac_file` / `load_specs` | Parse AC files → `CommandSpec` (with `AcItem`s) |
| `compute_score(spec, results)` | Deterministic dimension + composite scoring → `Scored` |
| `band_for(score, flags)` | Band with breach/regression cap |
| `append_records` / `load_records` | Append-only JSONL with meta line; readers skip meta |
| `render_scoreboard(records, command)` | Scoreboard text + failing AC + actions |
| `run_survey(target, target_dir, *, command, runner)` | Assemble prompt → run → parse JSON → score → append |
| `import_specs(target, target_dir, source_path, *, runner)` | Regenerate AC files from a spec dir |

`runner` defaults to `llm.run_prompt`, resolved at call time so tests inject a fake — runs spend
no credits and need no network. The model emits text; the module writes every file.

Prompts: `prompts/survey.md` (scoring → JSON), `prompts/survey_import.md` (AC regeneration →
delimited `=== SURVEY-<command>.md ===` blocks). Both obey the frontmatter contract.

### Feedback Loop
`2026-06-13` · `spec:na` · `impl:implemented`

1. **Pre-author** `ac/SURVEY-<command>.md` before the work lands.
2. **Build** happens in another window.
3. **Survey** (`--run`): score against the AC; record flags + generalized actions.
4. **Diagnose**: a flag recurring across commands (e.g. `unresolved-uncertainty`) is a *process*
   defect — fix the prompt or command contract, not one file.
5. **Iterate**: `--import` regenerates the AC from the evolving specification.

Generalized fixes, not line-level patches: prefer "route plan reads through one loader so a rename
propagates" over "edit line 70 to MANIFEST.md".

### Testing State
`2026-06-13` · `spec:na` · `impl:implemented`

- Unit/CLI tests: `tests/test_survey.py` (parsing, scoring math, bands, fake-runner run, render,
  import). Run via `bash bin/test.sh tests/test_survey.py` or `python -m pytest`.
- Soundings: `CLI-029` (IMPLEMENTED).
- Current state: command and deterministic scoring are done. The `drydock status` baseline record
  in `scores.jsonl` was hand-authored from a code read; re-run `--run` for an LLM-scored record.
  Per-command deterministic assertion execution (running each AC's `Verify` automatically) is a
  later enhancement — today assertions are judged by the LLM like judgment AC.

## Acceptance Criteria

- `drydock survey <Target>` renders the scoreboard without LLM; deterministic.
- `--run` scores all commands, appends to `scores.jsonl`, then renders.
- `--import <path>` regenerates AC files from spec dir without scoring.
- `--command <name>` correctly filters without colliding with `dest="command"` in argparse.
- Band cap applies: `guardrail-breach` or `regression` locks band at `TAKING_WATER` or below.
- `scores.jsonl` is append-only; meta line present; readers skip it.

## Guardrails

- `scores.jsonl` is append-only. Never rewrite or delete a prior record.
- The LLM judges only; the module computes all scores. No score arithmetic in the prompt.
- `runner` is injected; tests never spend credits or require network.
- `--command` must use `dest="command_filter"` to avoid argparse collision.

## Open Questions

- Per-command deterministic assertion execution (running `Verify` automatically vs LLM judgment).

## Not in scope yet

- Automatic assertion runner for `Verify` column items.
- Survey subsuming `build score` / SCORECARD.md.
