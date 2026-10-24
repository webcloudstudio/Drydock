# MEMORY: drydock import

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Description | Bring the Commander's source material into the Target as a read-only snapshot under `blueprint/sources/`, and optionally normalize an intent document into `COMPASS.md`. |
| Route | import |
| Modules | `import_markdown.py`, `import_source.py`, `import_speckit.py`, `source_refit.py`, `compass_sources.py`, `lineage.py` |
| Prompts | `import_compass.md` |
| Tests | `tests/test_import_*.py`, `tests/test_compass_sources.py` |
| Topics | — |
| Pending spec | 0 |
| Pending impl | 0 |

## Intent

Bring the Commander's source material into the Target as a read-only snapshot under
`blueprint/sources/`, and optionally normalize an intent document into `COMPASS.md`. The external
authoring tree stays the product's source of truth; the snapshot is Drydock's working copy and
changes only on an explicit import.

## Guardrails

- None.

## Details

### Syntax

```text
drydock import <Target> <Source> [--format auto|markdown|source|speckit|compass|intent] [--force]
drydock import <Target> --update
```

`--format auto` (default) requires a file and detects its format; a directory needs `markdown` or
`source`. `--force` applies only to Compass imports.

### Rules

`2026-08-04` · **The snapshot is the Drydock source item.** Commands read
`blueprint/sources/`, never the external tree. Each import commits the Target repository and
records `IMPORTED`. Cost when broken: a silent edit to the external tree changes what the next
build means.

`2026-06-10` · **Copy imports never call a model.** `markdown`, `source`, and `speckit` copy files
verbatim, preserving relative paths. Imported files must be UTF-8; a file that fails decoding is
not analyzed. Cost when broken: an import that paraphrases the specification it is meant to
preserve.

`2026-08-04` · **`--update` refreshes from the recorded root and takes no `<Source>`.** It compares
the recorded source root with the snapshot, copies added and changed files, leaves unchanged files
untouched, reports added, changed, deleted, and unchanged counts, and records a new source version
in `LINEAGE.json`. It never opens the Manifest. Cost when broken: a refresh that rewrites unchanged
files and dirties every consumer.

`2026-08-04` · **Compass-owned sources are immutable after setup.** A changed Compass-classified
source fails `--update` with the file names and the statement that a replan is required; it is
never copied and `COMPASS.md` is never modified. Classification comes from the `ANALYSIS.md`
source-role table; unlisted files are ordinary material. Cost when broken: a hard architectural
constraint silently becomes a no-op.

`2026-08-04` · **A deletion is recorded, never applied.** A file in the snapshot and absent from the
recorded root is marked deleted in `LINEAGE.json`; the local copy is retained so a refit ticket can
cite what was withdrawn, and the refresh is not blocked. Drydock never deletes a Blueprint
automatically. Cost when broken: a feature removed because a file moved.

`2026-10-21` · **A reply without artifacts is retried once, with the reason.** A successful reply that holds no artifact delimiter — prose, a question, a refusal — prints
`[import] response without artifacts, retrying once with the reason: "<excerpt>"` and reruns the
unchanged prompt with an appended `Artifact retry` block that quotes the reply and forbids asking,
refusing, or explaining (`--format compass` only). A second such reply fails the ordinary parse. Shared mechanism:
`artifact_blocks.retry_reply_without_artifacts`. *Broken:* LayersTesting `20261021.180733`
ended at analyze when Haiku asked which output form to use instead of emitting.

`2026-07-29` · **A Compass import is one normalization call.** `--format compass` (alias `intent`)
reads one non-empty file, normalizes it into `COMPASS.md` at the Target root with its guardrail,
and refuses an existing `COMPASS.md` unless `--force`. Cost when broken: Commander guidance
overwritten by a re-import.

### Mechanism

1. Resolve the Target; `--update` branches to `source_refit.update_import`.
2. Resolve the format (`auto` detects from a file).
3. Copy into `blueprint/sources/` (or normalize to `COMPASS.md`).
4. Commit the snapshot, record `IMPORTED`, print the imported paths.

### Exit codes

| Code | Condition |
|---|---|
| `0` | Imported or refreshed. |
| `1` | Missing or empty source, changed Compass source on `--update`, existing `COMPASS.md` without `--force`, unavailable recorded root, LLM failure. |
| `2` | Usage error: no `<Source>`, `<Source>` with `--update`, `auto` on a directory, unknown format. |

### Spec divergence

- The specification omits the `intent` alias for `compass`.
- The specification says `--update` "records a new source version"; it does not state that a
  changed Compass source fails the update or that deletions are reported, not applied.

## Decisions

-

## Questions

-

## Actions

-

## Working Notes

-
