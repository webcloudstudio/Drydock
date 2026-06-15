# Surveyor — State

**Updated:** 2026-06-13
**Surveyed commit:** `cae9e8f`
**Phase:** Foundational (init · import · analyze · plan create · status)

Read this first on every wake. Re-survey only commands whose source changed since the surveyed
commit: `git log --oneline cae9e8f..HEAD -- src/drydock/<module>.py`.

---

## Current scoreboard

| Command | Soundings | Latest score | Band | Flags | Surveyed |
|---------|-----------|--------------|------|-------|----------|
| status | DONE | 62 (provisional) | TAKING_WATER | contract-drift, incomplete | code-read |
| plan create | IMPLEMENTED | — | not surveyed | — | — |
| analyze | STUBBED | — | not surveyed | — | — |
| import | DONE | — | not surveyed | — | — |
| init / config | DONE | — | not surveyed | — | — |

Phase-done gate: all five at SEAWORTHY (≥90), no breach/regression, plus a clean Scrum Master
review of `MANIFEST.md`. **Not met.**

---

## Top actions for the implementation window

1. **status** — history limit 5 → 10, filtered by target; add the 11-record test (STATUS-C3).
2. **status** — replace `BUILD_PLAN.md` / `parse_build_plan` with `MANIFEST.md` / `load_target_plan`
   (STATUS-D2 contract-drift). Affects `status.py` lines 70, 82, 228, 230–233.
3. **analyze** — still STUBBED; build against `docs/SPEC_ANALYZE.md` + `prompts/analyze.md`.
4. **plan create** — IMPLEMENTED but no MANIFEST exists for target `Drydock`; produce one so the
   Scrum Master pass (PLN-D5) can run.

---

## Tooling status

- `drydock survey` is **built** (`src/drydock/survey.py`, `tests/test_survey.py`, Soundings CLI-029).
  Run `drydock survey Drydock` to render this scoreboard from `scores.jsonl`;
  `drydock survey Drydock --run` to re-score (LLM); `--import <dir>` to regenerate the AC files.
- The `status` baseline record was hand-authored (code-read). Re-run `--run` once an LLM survey is
  desired; the deterministic render already reads it.

## What I have not yet done

- No survey of import / init / config / analyze / plan create (only `status` from code-read).
- No `MANIFEST.md` exists at `targets/Drydock/` → Scrum Master review pending (reviews/ empty).

## Next survey plan

1. When `status.py` changes: re-run STATUS-* assertions, especially the 11-record history test and
   the MANIFEST grep. Expect band to move toward SEAWORTHY.
2. When a `MANIFEST.md` lands: run PLN-* assertions, then the Scrum Master ranking → `reviews/SCRUM-MANIFEST.md`.
3. When `analyze.py` lands: run ANL-* assertions against a temp Blueprint with an injected gap and
   a cleared stack.
4. Append one `scores.jsonl` record per command surveyed; then update this scoreboard and the
   surveyed commit.

## Observations to recheck

- `targets/Drydock/blueprint/ACCEPTANCE_CRITERIA.md` removed (artifact; acceptance lives in
  SEA_TRIALS.md + SOUNDINGS.md). Build-window follow-up: drop its references in
  `plan_compass.py:13` and `validate_specification.py:60,88`, and stop the scaffold creating it.
- `logs/history.jsonl` currently holds one record; STATUS-C3 needs a seeded multi-target fixture
  to test the 10-limit honestly.
