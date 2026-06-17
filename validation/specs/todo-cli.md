# VALIDATION CASE: todo-cli

## Goal

Build a stateful Python TODO CLI that supports `add`, `list`, and `done` while
preserving state across invocations.

## Input Contract

The CLI must accept a database path, create local state when needed, and update
task status without requiring a service or network dependency.

## Build Steps

- Copy the candidate project into an isolated workspace.
- Run a build sanity step.
- Execute a sequence of `add`, `list`, `done`, and `list` commands against one database file.
- Run the project tests and one invalid-command check.

## Required Artifacts

- todo.py
- tests/test_todo.py

## Assertions

| ID | Type | Weight | Subject | Expectation | Evidence |
|----|------|--------|---------|-------------|----------|
| TODO-A1 | artifact | 2 | todo.py | The CLI entry file exists. | artifacts_present contains todo.py |
| TODO-A2 | behavior | 4 | add/list | Added tasks appear in list output. | verify stdout log |
| TODO-A3 | behavior | 4 | done/list | Completing a task persists and appears on the next list run. | verify stdout log and db state note |
| TODO-A4 | artifact | 2 | state file | The database/state file is created locally. | output note |
| TODO-A5 | test | 3 | pytest | `python -m pytest -q` exits 0. | verify stdout log |
| TODO-A6 | behavior | 3 | invalid command | An invalid subcommand exits non-zero and does not corrupt state. | negative-path note |
| TODO-A7 | artifact | 1 | tests/test_todo.py | A project test exists for the stateful workflow. | artifacts_present contains tests/test_todo.py |

## Scoring

- Minimum score: 85
- Partial credit: `pass=1.0`, `partial=0.5`, `fail=0.0`
- Band thresholds: `SEAWORTHY=90`, `SEA_TRIALS=75`, `TAKING_WATER=60`

## Gap Rules

- missing-artifact: Required files are absent.
- behavior-mismatch: Stateful command behavior diverges from the contract.
- missing-test: The project lacks a proving test or its tests fail.
- runtime-failure: The build or verification command exits non-zero.
- contract-drift: The CLI shape differs from the benchmark contract.

## Notes

This benchmark proves multi-step behavior and persistence instead of one-shot
output.
