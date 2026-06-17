# VALIDATION CASE: file-transform

## Goal

Build a deterministic Python transformer that reads a CSV file, writes a JSON
summary, and fails cleanly when the input is invalid or missing.

## Input Contract

The implementation must accept input and output paths on the command line. The
JSON summary must be deterministic for the seeded fixture input.

## Build Steps

- Copy the candidate project into an isolated workspace.
- Run a build sanity step.
- Execute the transformer on the seeded CSV.
- Compare the produced JSON with the expected output.
- Run the project tests and one negative-path command.

## Required Artifacts

- transform.py
- tests/test_transform.py
- data/input.csv

## Assertions

| ID | Type | Weight | Subject | Expectation | Evidence |
|----|------|--------|---------|-------------|----------|
| TRANSFORM-A1 | artifact | 2 | transform.py | The transformer entry file exists. | artifacts_present contains transform.py |
| TRANSFORM-A2 | output | 4 | out.json | The generated JSON matches the expected deterministic summary. | output comparison note |
| TRANSFORM-A3 | behavior | 3 | CLI contract | The command accepts input and output paths and exits 0 for valid input. | verify logs and verify_exit_code |
| TRANSFORM-A4 | test | 3 | pytest | `python -m pytest -q` exits 0. | verify stdout log |
| TRANSFORM-A5 | behavior | 3 | invalid input | Missing input causes a non-zero exit and no fabricated success output. | negative-path note |
| TRANSFORM-A6 | artifact | 1 | tests/test_transform.py | A project test exists for the transform behavior. | artifacts_present contains tests/test_transform.py |

## Scoring

- Minimum score: 85
- Partial credit: `pass=1.0`, `partial=0.5`, `fail=0.0`
- Band thresholds: `SEAWORTHY=90`, `SEA_TRIALS=75`, `TAKING_WATER=60`

## Gap Rules

- missing-artifact: Required files are absent.
- wrong-output: The produced JSON differs from the expected output.
- behavior-mismatch: The CLI contract or negative path behaves incorrectly.
- missing-test: The project lacks a proving test or its tests fail.
- runtime-failure: The build or verification command exits non-zero.
- shortcut-or-fabrication: The command reports success without producing the required output.

## Notes

This benchmark proves deterministic file I/O and a real negative path.
