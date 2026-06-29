# ARCHIVE: survey
Archived from notes_survey.md

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
