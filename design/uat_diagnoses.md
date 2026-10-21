# UAT Diagnoses

The memory of `/ddk-uat` (`prompts/uat_diagnostic.md`) across runs: one row per diagnosed run and
root cause. A diagnosis reads it first, to see whether its cause has been seen before and which
fixes already sit in the implicated area.

| Column | Content |
|---|---|
| Area | The file and function where the cause lives; rows in one Area are read together |
| Fix | The commit that addressed the cause; written by the session that commits the fix |
| Outcome | `open` no fix · `unverified` fix committed, no later run has reached past the stage · `fixed` a run on or after the fix passed the stage · `recurred` the same cause stopped a run after the fix |

Rules: append a row per diagnosis, and change only the Fix and Outcome of earlier rows. A fix
in an Area that already holds a `recurred` row revises or removes that fix, not layers beside it.

| Date | Kit | Run | Commit | Model | Stopped | Root cause | Area | Fix | Outcome |
|---|---|---|---|---|---|---|---|---|---|
| 2026-10-21 | LayersTesting | 20261021.034029 | c66b1a5 | claude-haiku-5-5 | plan rc=1 | Batch 1 `DATABASE.md` with a one-table `## Access Patterns` was accepted and found only after batch 7 | `planning_session.py` `_continue_short_plan` DATABASE merge | 3a9199a | fixed |
| 2026-10-21 | LayersTesting | 20261021.034029 | c66b1a5 | claude-haiku-5-5 | plan rc=1 | Seeded `DATABASE.md` read as a truncated Stage 1 artifact and dropped | `planning_session.py` Stage 1 truncation check | 649fae5 | fixed |
| 2026-10-21 | LayersTesting | 20261021.173113 | e1d0630 | claude-haiku-5-5 | plan rc=1 | Stage 2 resent a byte-identical prompt after a no-artifact reply | `planning_session.py` `_continue_short_plan` retry | a3d0e60 | recurred |
| 2026-10-21 | LayersTesting | 20261021.180733 | a3d0e60 | claude-haiku-5-5 | analyze rc=1 | Analyze answered with a question and no artifacts | `artifact_blocks.py` `retry_reply_without_artifacts` | 9397aae | fixed |
| 2026-10-21 | LayersTesting | 20261021.183753 | 9397aae | claude-haiku-5-5 | plan rc=1 | Retry named the refusal but asked for the same five Blueprints; Haiku refused three times | `planning_session.py` `_continue_short_plan` retry | 2e121e4 | fixed |
| 2026-10-21 | LayersTesting | 20261021.195808 | 2e121e4 | claude-haiku-5-5 | build rc=1 | Plan wrote `account-delete-in-use-refused` against seed account `DRAWER1` it never loads, with unasserted setup calls; both rules are prompt-only | `plan_verify.py` acceptance checks | | open |
