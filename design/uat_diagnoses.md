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
| 2026-10-21 | LayersTesting | 20261021.195808 | 2e121e4 | claude-haiku-5-5 | build rc=1 | Plan wrote `account-delete-in-use-refused` against seed account `DRAWER1` it never loads, with unasserted setup calls; both rules are prompt-only | `plan_verify.py` acceptance checks | b7ea20b | unverified |
| 2026-10-21 | LayersTesting | 20261021.213934 | ac34b6e | claude-haiku-5-5 | plan rc=1 | Batch 4 `DATABASE.md` (headingless patterns, no tables) refused, but `_render_ledger` filters the defect by tranche so no batch saw it; Features accepted against the bare template, Haiku refused batches 6–8 | `planning_session.py` `_render_ledger` DATABASE defect routing | 42252b1 | unverified |
| 2026-10-21 | LayersTesting | 20261021.231950 | 0643de2 | claude-haiku-5-5 | plan rc=1 | Continuation says emit the Current batch and "nothing else" while `DATABASE.md` additions sit outside it as a conditional aside; Haiku added no update/delete patterns, then refused `FEATURE-TxnAmend.md` three times rather than cite an undeclared `transactions.update` | `prompts/plan_continue.md` + `planning_session.py` `_render_ledger` / `_continue_short_plan` retry DATABASE additions | 9b83447; 48764ad | unverified |
| 2026-10-22 | LayersTesting | 20261022.121722 | 31c4b63 | claude-haiku-5-5 | plan rc=1 | Stage 2 has no legal refusal channel and never checks a prose refusal's claim; at batch size 1 the retry cannot change the ask, so batches 25–27 refused (no tools, sources absent — false, they are in the prompt) and exhausted the 3-stall budget at 25/27 | `planning_session.py` `_continue_short_plan` no-artifact branch | 35c4da2 | recurred |
| 2026-10-22 | LayersTesting | 20261022.165023 | 6ad18c5 | claude-haiku-5-5 | plan rc=2 | `_refutation` checks claims only for `missing-input`, so Haiku's `FEATURE-Report-Balances.md` blocks stood: batch 4 `other` (accepted Blueprints not in context, a listed never-report reason) and batch 6 `insufficient-specification` whose Required action reads "None needed to unblock"; the 3-stall budget ran out at 11/28 and the standing product block deferred to the Commander | `plan_blocked.py` `_refutation` + `planning_session.py` product-block deferral |  | open |
