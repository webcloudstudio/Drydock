# MEMORY: drydock run

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Description | Start a Drydock service. |
| Route | run |
| Modules | `quarterdeck_run.py`, `quarterdeck_state.py`, `standard_artifacts.py`, `manifest_edit.py`, `QuarterDeck/app.py`, `lifecycle.py` |
| Prompts | — |
| Tests | `tests/test_quarterdeck*.py`, `tests/test_manifest_edit.py`, `tests/test_lifecycle.py` |
| Topics | [process_stops](../topics/process_stops.md), [lifecycle](../topics/lifecycle.md) |
| Pending spec | 0 |
| Pending impl | 0 |

## Intent

Start a Drydock service. The one service is the QuarterDeck: the web console where the
Commander reads analysis, answers questionnaires, edits Compass files, and reviews or regroups the
Manifest, and where agents put anything that needs a human. `QuarterDeck/README.md` documents the
page types and `console.yaml`.

## Guardrails

- None.

## Details

### Syntax

```text
drydock run quarterdeck [<Target>] [--host <host>] [--port <port>]
drydock run builder <Target> [--infile [<format>=]<file>]... [--indir [<format>=]<dir>]...
        [--max-build-passes <n>] [--repair-attempts <n>] [--diagnose-attempts <n>]
        [--repair-stall-limit <n>] [--capture-output-limit <MB>] [--sandbox-mem-limit <MB>]
        [--plan-override-model <model>] [--model <model>]
```

`<Target>` defaults to the most recently updated Target; `--port` defaults to `quarterdeck_port`
config or `8080`; `--host` to `127.0.0.1`.

### Rules

`2026-10-25` · **`run builder` starts or continues one Target through to a complete build.** It
runs the [lifecycle](../topics/lifecycle.md) in place, with the UAT step console, and ends in a
box: `BUILD COMPLETE` (exit 0), `BUILD INCOMPLETE`, `BUILD STOPPED`, or `BLOCKED` (exit 1), or
`NO SOURCES` (exit 2). `--infile` (default format `auto`) and `--indir` (default `markdown`)
repeat, accept a `<format>=` prefix (`compass=INTENT.md`), run in command-line order as one
`drydock import` each, and apply only while the Target has no imported sources. A bad path is a
usage error. `--diagnose-attempts` defaults to 3. `drydock_runner.sh` is a deprecated shim that
forwards `<target> <model>`; `drydock_build_loop.sh` is removed, and `DRYDOCK_RUNNER_MAX_BUILDS`
is no longer read. `Import_Marina.sh` is the import-list form: it builds `--infile` arguments and
execs `drydock run builder Marina "$@"`. Cost when broken: two workflows that drift apart.

`2026-10-19` · QuarterDeck renders max-one Rigging types as radios, including None for optional types, and excludes them from table choices. Draft saves return and display shared validation errors. Language or database changes clear approval; approval rejects invalid selections. Breaking this rule approves an incoherent stack.

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

`2026-10-18` · The technology selector uses database and language radios; optional database selection includes None. Approval refuses a missing language. Cost when broken: the selected stack and generated runtime disagree.

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

## Questions

-

## Actions

-

## Working Notes

-
