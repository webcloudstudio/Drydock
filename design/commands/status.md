# DESIGN: drydock status

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Route | status |
| Modules | `status.py`, `project_status.py`, `console.py` |
| Prompts | — |
| Tests | `tests/test_project_status*.py`, `tests/test_status*.py`, `tests/test_console.py` |
| Topics | — |
| Pending spec | 0 |
| Pending impl | 0 |

## Behavior

### Purpose

Orient the operator and drive batch loops. Without flags it is a read-only dashboard; with
`--check` or `--ready` it is a gate whose exit status is the verdict.

### Syntax

```text
drydock status                      dashboard of all Targets
drydock status <Target>             validation summary and plan state
drydock status <Target> --check     completion gate: exit 0 / 1 / 2
drydock status <Target> --ready     build-loop guard: exit 0 while buildable
drydock status console              terminal capability report and glyph samples
```

Flags may precede or follow `<Target>`. `console` is a reserved operand.

### Rules

`2026-08-13` · **Completion and buildability are separate observations.** `--check` reports
completion: `COMPLETE` (0) when every executable block is `closed/verified` and no blocking
decision is open; `RETRYABLE` (1) when the Manifest is approved and work is pending, implemented,
failed, or a `DISPUTED` criterion awaits repair; `BLOCKED` (2) for no, unparsable, draft, or empty
Manifest, or a verified Manifest with open blocking decisions. `--ready` reports only whether a
build can advance the frontier: `0` when buildable, `1` when complete or not ready.
`closed/implemented` ends scheduling but is incomplete under governed verification. Cost when
broken: a build loop that never ends on a stalled Target, or ends on an unverified one.

`2026-08-15` · **A gate verdict is a successful report.** Every `--check` and `--ready` outcome
prints one line to stdout; the exit status carries the verdict and stderr is reserved for command
failures. Cost when broken: loop scripts misread a verdict as an error.

`2026-08-30` · **The standing state honors named supersession.** The dashboard reads project status
through `project_status.standing_state`, so an unanswered earlier failure remains the frontier
(see [diagnose](diagnose.md)). Cost when broken: the dashboard shows progress past a failed gate.

`2026-06-10` · **Status never mutates the Target and never calls a model.** Cost when broken: an
orientation command changes what it reports.

### Mechanism

1. Separate `--check`/`--ready` from operands; reject both together.
2. `console` → terminal report; no operand → workspace dashboard; `<Target>` → validation summary,
   plan state, analysis quality, and next step.
3. Gates read `completion_check` / `execution_state` and print one verdict line.

### Exit codes

| Code | Condition |
|---|---|
| `0` | Dashboard printed; `--check` `COMPLETE`; `--ready` buildable. |
| `1` | `--check` `RETRYABLE`; `--ready` complete or not ready. |
| `2` | `--check` `BLOCKED`; usage error, including an unknown Target with a gate flag. |

### Spec divergence

- The specification does not give the `--check` exit codes, the `--ready` semantics for a complete
  Target, or `status console`.

## Decisions

-

## Open Questions

-

## Open Actions

-

## Working Notes

-
