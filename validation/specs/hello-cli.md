# VALIDATION CASE: hello-cli

## Goal

Build a Python command-line program that prints the exact text `hello world`
and includes a test proving the behavior.

## Input Contract

The implementation must expose a runnable Python entry file and a test file. No
network access, framework dependency, or interactive input is allowed.

## Build Steps

- Copy the candidate project into an isolated workspace.
- Run a build sanity step.
- Run the program and capture stdout/stderr.
- Run the project tests.

## Required Artifacts

- app.py
- tests/test_app.py

## Assertions

| ID | Type | Weight | Subject | Expectation | Evidence |
|----|------|--------|---------|-------------|----------|
| HELLO-A1 | artifact | 2 | app.py | The main entry file exists. | artifacts_present contains app.py |
| HELLO-A2 | output | 4 | stdout | Running `python app.py` emits exactly `hello world`. | verify stdout log |
| HELLO-A3 | artifact | 2 | tests/test_app.py | A project test exists for the CLI behavior. | artifacts_present contains tests/test_app.py |
| HELLO-A4 | test | 4 | pytest | `python -m pytest -q` exits 0. | verify stdout log and verify_exit_code |
| HELLO-A5 | behavior | 1 | stderr | The program emits no stderr on success. | verify stderr log |

## Scoring

- Minimum score: 85
- Partial credit: `pass=1.0`, `partial=0.5`, `fail=0.0`
- Band thresholds: `SEAWORTHY=90`, `SEA_TRIALS=75`, `TAKING_WATER=60`

## Gap Rules

- missing-artifact: Required files are absent.
- wrong-output: The program emits the wrong stdout or stderr.
- missing-test: The project lacks a proving test or its tests fail.
- runtime-failure: The build or verification command exits non-zero.
- missing-evidence: The runner omits a required check entry.

## Notes

This is the simplest benchmark and should catch trivial scaffolding failures
quickly.
