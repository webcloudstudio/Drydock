# DESIGN: drydock report

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Route | report |
| Modules | `report.py`, `report_render.py`, `llm_report.py`, `build_report.py` |
| Prompts | — |
| Tests | `tests/test_report*.py`, `tests/test_llm_report.py` |
| Topics | — |
| Pending spec | 0 |
| Pending impl | 0 |

## Behavior

### Purpose

Present existing Target state and evidence through a common, named report interface.

### Syntax

```text
drydock report help
drydock report <name> <Target>
drydock report --all [<Target>]
```

Names, in registry order: `status`, `manifest`, `run`, `build`, `history`, `llm`, `token`,
`scores`.

### Rules

`2026-10-05` · **Reports derive from recorded facts.** Each report function reads the existing
Manifest parser, workflow state, build evidence, command history, LLM accounting, or score
summary. It does not execute a build, acceptance check, model, or UAT run. Cost when broken: a
report changes the fact it claims to describe or spends model credits unexpectedly.

`2026-10-05` · **One registry names every report.** The registry supplies help rows, selection,
and the `--all` order. Cost when broken: advertised reports and executable reports drift.

`2026-10-05` · **Artifacts live under the selected Target.** A named report writes
`reports/<name>.txt`; `--all` covers every initialized Target unless one is named. For each
Target, all reports render before any are persisted. A workspace sweep continues after a Target
failure and returns nonzero. The CLI displays paths relative to the caller's directory when
possible. Cost when broken: output is hard to find, an error hides another Target's reports, or a
failed report leaves a partially refreshed set.

`2026-10-05` · **The Manifest report summarizes the work graph.** It shows plan state, counts,
groups, step states, failures, and the buildable frontier through `build_status()`. It does not
reproduce QuarterDeck's editing controls or context-cost presentation. Cost when broken: a
console report becomes coupled to a browser renderer or claims a different frontier.

`2026-10-13` · **The token report lists every LLM call.** One row per execution in start order:
stage, call, model, prompt bytes, estimated prompt tokens, run time, and status. It includes
failed and incomplete calls, since a failed call still spent the prompt. Cost when broken: the
largest prompts and slowest calls hide inside per-stage roll-ups.

### Mechanism

1. Resolve one initialized Target or enumerate every initialized Target under the workspace.
2. Select one registry entry or all entries in registry order.
3. Render text from existing projections and evidence readers.
4. Write `targets/<Target>/reports/<name>.txt` and print the resulting paths.

### Exit codes

| Code | Condition |
|---|---|
| `0` | Every selected report written. |
| `1` | A report failed for any Target (the sweep continues), or no initialized Targets exist. |
| `2` | Unknown report name, or a Target that is not a name under the targets directory. |

### Spec divergence

- The specification does not document `drydock report`.

## Decisions

-

## Open Questions

-

## Open Actions

-

## Working Notes

-
