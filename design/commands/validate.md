# DESIGN: drydock validate

| Field | Value |
|---|---|
| Version | 2026-10-15 V1 |
| Route | validate |
| Modules | `validate_specification.py` |
| Prompts | — |
| Tests | `tests/test_validate*.py` |
| Topics | — |
| Pending spec | 0 |
| Pending impl | 0 |

## Behavior

### Purpose

Structurally validate a Target's Blueprint without a model: required files for the current SAIL
phase, `METADATA.md` fields, naming, typed headers, relationships, and Programmatic Acceptance
syntax.

### Syntax

```text
drydock validate <Target> [--verbose]
```

`--verbose` also prints passing checks.

### Rules

`2026-10-22` · `VERIFICATION.md` is a standard release-verification Blueprint name. Cost when broken: a generated release gate produces a spurious naming warning.

`2026-06-10` · **Required files are gated by phase.** The phase is read from the filesystem:
Set Up (empty Blueprint), Arrange (content, no `MANIFEST.md`), Implement (Manifest exists).
`METADATA.md` is required in every phase; `README.md` and `ARCHITECTURE.md` only from Implement.
Cost when broken: a new Target fails validation for files no step has produced yet.

`2026-06-10` · **Findings are PASS, WARN, or FAIL, and only FAIL gates.** Each failure states its
own remediation; deterministic single-cause findings never reach standoff diagnosis. Cost when
broken: warnings block work, or a failure gives no next action.

`2026-08-10` · **Facts fail; predictions do not.** A Programmatic Acceptance snippet that does not
parse is a failure. Predicting that a snippet would fail is not done here: the analyzers that did
were retracted after false positives, and a snippet that cannot exercise the code reports
`UNVERIFIED` when it runs. The one authoring signal kept is a re-typed expected value, reported and
never gated. Cost when broken: specifications that validated for weeks begin failing on a
judgment.

`2026-10-18` · Stack-file validation resolves language bundles as well as stack guidance. Cost when broken: valid language resources are omitted or acceptance evidence is misclassified.

### Mechanism

1. Reject forbidden Blueprint files; check directories.
2. Determine the phase; check required files.
3. Check `METADATA.md` fields, naming conventions, template leftovers, terminal sections.
4. Parse Programmatic Acceptance snippets; check typed headers and relationship consistency.
5. Print findings; exit on failures.

### Exit codes

| Code | Condition |
|---|---|
| `0` | No `FAIL` findings. |
| `1` | Any `FAIL`, or the Target is missing. |
| `2` | Usage error. |

### Spec divergence

- The specification does not document `drydock validate`.

## Decisions

-

## Open Questions

-

## Open Actions

-

## Working Notes

-
