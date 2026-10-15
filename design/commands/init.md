# DESIGN: drydock init

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Route | init |
| Modules | `init_target.py`, `standard_artifacts.py`, `metadata.py`, `target_git.py`, `skills.py` |
| Prompts | — |
| Tests | `tests/test_init_target.py`, `tests/test_init_specification.py` |
| Topics | — |
| Pending spec | 0 |
| Pending impl | 0 |

## Behavior

### Purpose

Create the specification-independent baseline for a Target: its workspace directories,
`METADATA.md`, standard QuarterDeck artifacts, and its own Git repository. Idempotent.

### Syntax

```text
drydock init <Target> [--display-name <name>] [--description <text>]
```

### Rules

`2026-06-10` · **Init never overwrites.** Each baseline file is written only when absent; existing
files are counted as preserved. A rerun on an initialized Target reports nothing to do. Cost when
broken: Commander edits to `METADATA.md` or `console.yaml` erased by a routine rerun.

`2026-06-10` · **Target names are single, safe path segments.** Empty names, separators, `..`,
reserved characters, control characters, and names over 200 characters are refused. Cost when
broken: a Target written outside the targets root.

`2026-10-05` · **Every Target is its own Git repository.** Init runs `git init` when the directory
is not already a repository; build lineage and checkpoints depend on it. Cost when broken: no
lineage and no recoverable checkpoints.

`2026-09-22` · **Skills are synced best-effort.** Init installs or upgrades Drydock's shipped
skills (e.g. `/ddk-refit`) in the workspace by version. A sync failure never fails init. Cost when
broken: a skill-provisioning error blocks project creation.

### Mechanism

1. Validate the name.
2. Create `blueprint/sources`, `blueprint/changes`, `evidence`, `logs`, `QuarterDeck/data`, each
   with `.gitkeep`.
3. Write `METADATA.md` (display name, description), standard artifacts, `QuarterDeck/console.yaml`.
4. Initialize the Target Git repository.
5. Sync workspace skills; record `INITIALIZED` (pass or failure).

### Exit codes

| Code | Condition |
|---|---|
| `0` | Initialized, or already initialized. |
| `1` | Invalid name, filesystem failure, or Git initialization failure. |
| `2` | Usage error. |

### Spec divergence

- The specification does not state that init creates a Git repository or syncs skills.

## Decisions

-

## Open Questions

-

## Open Actions

-

## Working Notes

-
