# DESIGN: drydock run

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Route | run |
| Modules | `quarterdeck_run.py`, `quarterdeck_state.py`, `standard_artifacts.py`, `manifest_edit.py`, `QuarterDeck/app.py` |
| Prompts | — |
| Tests | `tests/test_quarterdeck*.py`, `tests/test_manifest_edit.py` |
| Topics | — |
| Pending spec | 0 |
| Pending impl | 0 |

## Behavior

### Purpose

Start a Drydock service. The one service is the QuarterDeck: the web console where the
Commander reads analysis, answers questionnaires, edits Compass files, and reviews or regroups the
Manifest, and where agents put anything that needs a human. `QuarterDeck/README.md` documents the
page types and `console.yaml`.

### Syntax

```text
drydock run quarterdeck [<Target>] [--host <host>] [--port <port>]
```

`<Target>` defaults to the most recently updated Target; `--port` defaults to `quarterdeck_port`
config or `8080`; `--host` to `127.0.0.1`.

### Rules

`2026-07-03` · **QuarterDeck owns no project state and makes no decisions.** It renders the plain
files named in `console.yaml` and persists only into them: questionnaire answers, edited document
source, approvals, direct decisions, and constrained `MANIFEST.md` structure edits. Cost when
broken: a second source of truth an agent cannot read back.

`2026-07-03` · **Runtime from the package, state in the Target.** The FastAPI app runs from the
installed package or source tree; `QUARTERDECK_DIR` and `QUARTERDECK_PROJECT_ROOT` point it at
`<Target>/QuarterDeck/`. Cost when broken: every Target carries a stale copy of the console.

`2026-07-03` · **Missing console state is regenerated, never invented.** An absent `console.yaml`
is rewritten from `standard_artifacts.render_console` when `METADATA.md` marks the directory an
initialized Target; any other directory is refused. Cost when broken: a failed command makes
blocker recovery impossible.

`2026-07-03` · **One Build Compass over `MANIFEST.md`.** A single renderer shows the live work graph
with costs, state chips (`Built`, `Ready To Build`, `review`, `failed` with its `finding:`), and the
Definition of Done per block. The retired `plan_decision` and `build_plan` views do not return.
Cost when broken: three partial views that disagree about the same graph.

`2026-07-03` · **Structure edits are topology-validated before write.** `manifest_edit.apply_edit`
supports group move, regroup, rename (header label only; block `id:` untouched), new empty group,
and split group (new groups inserted after the original). Order within a group is not editable
because a group builds as one unit. No edit fabricates a story. Cost when broken: a dependent
pushed ahead of what it consumes, or a story with nothing to build.

`2026-07-03` · **Group cost is not additive.** Each step's Story Points are its full assembled
prompt in the running model's tokens (see [build](build.md)); shared context recurs across steps,
so the group header reads "Combined Story Points". Cost when broken: a group appears to cost the
sum of its steps.

### Mechanism

1. Resolve the Target directory and port.
2. `ensure_quarterdeck_state` restores missing console state and refreshes the Commanders Chair.
3. Run `python -m uvicorn QuarterDeck.app:app` with the state environment; block until it exits.

### Exit codes

| Code | Condition |
|---|---|
| `0` | Server exited normally. |
| `1` | Uninitialized Target or missing runtime; otherwise the server's own exit status. |
| `2` | Usage error. |

### Spec divergence

- The specification says `drydock init` enables the QuarterDeck; `run quarterdeck` also restores
  missing console state for any initialized Target.

## Decisions

-

## Open Questions

-

## Open Actions

-

## Working Notes

-
