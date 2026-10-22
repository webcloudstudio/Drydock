# DESIGN: drydock diagnose

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Route | diagnose |
| Modules | `diagnose_command.py`, `diagnose.py`, `diagnose_evidence.py`, `diagnose_report.py`, `diagnose_apply.py`, `diagnose_repair.py`, `diagnose_ladder.py`, `diagnose_console.py`, `diagnose_html.py`, `ac_repair.py` |
| Prompts | `diagnose_report.md`, `diagnose_ac_repair.md`, `diagnose.md` (inline post-failure) |
| Tests | `tests/test_diagnose*.py`, `tests/test_ac_repair.py` |
| Topics | [acceptance_criteria](../topics/acceptance_criteria.md) |
| Pending spec | 0 |
| Pending impl | 0 |

## Behavior

### Purpose

Explain why the latest run stopped, separate a real defect from retry exhaustion, and hand back a
repair-grade Incident Report plus applyable amendments. The report must be complete enough for
another agent to repair from alone. It is the operator-invoked superset of the inline
post-failure diagnosis in `diagnose.py`.

### Syntax

```text
drydock diagnose [<Target>] [--run <stamp>] [--apply | --no-apply]
```

| Mode | Behavior |
|---|---|
| default | Confirm each amendment `[y/N]` when interactive |
| `--apply` | Apply every verified amendment |
| `--no-apply` | Apply nothing; record amendments as `recommended` decisions |

`<Target>` defaults to the last active Target.

### Rules

`2026-10-19` · Acceptance repair includes the selected language compact in its specification-only context. Missing language resources raise a resource error. Breaking this rule repairs criteria against the wrong runtime.

`2026-08-30` · **Free facts first, then exactly one diagnosis call.** The milestone ladder (`INIT`,
`ANALYZE`, `PLAN`, `BUILD`, `SCORE`; `pass`, `fail`, or `[--] not run`) prints before anything is
spent. Then one model call, verification, write, confirm, apply — no retry loop, no second pass.
Cost when broken: an operator pays for a diagnosis of facts Drydock already recorded.

`2026-08-30` · **A recorded deterministic failure is not diagnosed.** When the error record
classifies a failure the inline diagnoser would skip (rate limit, context limit, timeout, provider
error), the command prints it and exits `1` without a model call. Programmatic acceptance failures
are always diagnosed. Cost when broken: paid calls to restate "usage limits".

`2026-08-30` · **Supersession is named, never positional.** `project_status.SUPERSEDES` says which
rung answers which: `PLAN REPAIRED` answers `PLAN CREATED`, `BUILT` answers `BUILDING`, a passing
`SCORE RELEASE` closes the scores beneath it. An unanswered earlier failure stays the frontier.
Cost when broken: a passing observational `SCORE BUILD` retires a failed acceptance gate.

`2026-10-12` · **Broken criteria are repaired before the run is diagnosed.** `DISPUTED` and
malformed criteria are selected deterministically and repaired first (`diagnose_ac_repair.md`);
default mode confirms each repair, `--apply` keeps all. A repaired Blueprint loses its compact and
resets every consuming block. A Target with nothing to repair spends nothing. Cost when broken:
the diagnosis blames code for a criterion that could never pass.

`2026-08-30` · **Log files are cited, never inferred.** The report's Log Files section lists each
execution's prompt, output, raw, log, and records paths from `logs/llm.jsonl` and
`logs/history.jsonl`, with a sha256 each. Cost when broken: a report another agent cannot repair
from.

`2026-08-30` · **Amendments are verified unified diffs.** Permitted targets are `COMPASS.md`,
`PLAN_COMPASS.md`, `ANALYZE_COMPASS.md`, `MANIFEST.md`, and `blueprint/` files (`2026-09-10`), whose
edits must pass acceptance-repair validation. A diff that does not apply cleanly is reported and
never offered. Applied amendments are logged in `DECISIONS.json` (`2026-09-11`) and committed in
the Target repository. Cost when broken: an authored `COMPASS.md` silently appended to.

`2026-08-30` · **Every exit names the next command.** Missing Target → `drydock init`; nothing run →
`drydock analyze`; no provider → `drydock config set llm-provider`; malformed output → rerun;
recorded but unapplied amendments → `--apply`; no Target resolvable → `drydock status`. Cost when
broken: an accurate report that leaves the operator stuck.

`2026-10-13` · **A historical success cannot hide unfinished work.** After diagnosis the exit is `1`
whenever a stop is recorded or the execution state is not `complete`. Cost when broken: the build
loop `build || diagnose --apply` ends early on a stalled Target.

### Mechanism

1. **Resolve** — Target and run (`--run` or latest) from `PROJECT_STATUS.jsonl` and
   `logs/history.jsonl`.
2. **Ladder** — collect the evidence bundle and print the banner and milestone ladder.
3. **Gate** — stop on a deterministic recorded failure or an unavailable provider.
4. **AC repair** — repair selected `DISPUTED` and malformed criteria.
5. **Diagnose** — one call; the module writes `diagnostics/<stamp>_INCIDENT.md` and `.html`:
   Header, Stage Ladder, Break Point, Reason, Not A Real Failure, Blockers and Decisions,
   Evidence, Log Files, Recommended Amendments.
6. **Apply** — verify each diff, confirm or apply per mode, log decisions, reset consumers of
   repaired Blueprints, commit, print the next command.

### Exit codes

| Code | Condition |
|---|---|
| `0` | No stop recorded and execution `complete`. |
| `1` | Findings, a stop, incomplete execution, malformed diagnosis, or a recorded deterministic failure. |
| `2` | Usage (`--apply` with `--no-apply`), and also: no Target, unknown Target, nothing run, no provider. |

### Spec divergence

- The specification shows `drydock diagnose <Target>` with a required Target and does not describe
  the default confirm mode, AC repair, or the Incident Report surfaces.

## Decisions

-

## Open Questions

-

## Open Actions

- `2026-10-22` · A test whose stubbed command raised reached the crash diagnosis in
  `diagnose.py`, which started a real `claude/sonnet` call from pytest
  (`tests/test_cli.py` plan-override test, before its stub was fixed). Tests must never reach a
  provider: disable crash diagnosis under pytest or behind an injectable runner.

## Working Notes

-
