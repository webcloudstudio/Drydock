# Build Instructions: TOML 1.0.0 Parser

## Objective

Build a TOML v1.0.0 parser that conforms to the specification in
`sources/toml-v1.0.0.md`. Correctness is measured by the upstream `toml-test`
conformance suite. The goal is to pass every test: 210 valid and 499 invalid
cases at TOML 1.0.

Rejecting invalid input is scored as heavily as accepting valid input. A parser
that is merely permissive fails roughly 70 percent of the suite.

## Interface Contract

The program is a filter: read TOML from **stdin**, write tagged JSON to
**stdout**, exit `0`. On invalid TOML, write a diagnostic to **stderr** and exit
non-zero. No arguments, no config, no side effects.

Minimal shape (`mytoml.py`):

```python
#!/usr/bin/env python3
import sys, json

def decode(text: str) -> dict:
    ...  # your implementation; returns the tagged structure

if __name__ == "__main__":
    try:
        result = decode(sys.stdin.buffer.read().decode("utf-8"))
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
    json.dump(result, sys.stdout)
```

### Tagged JSON encoding

- TOML tables become JSON objects. Empty tables become `{}`.
- TOML arrays become JSON arrays. Empty arrays become `[]`.
- Every TOML **value** becomes `{"type": "<TOML_TYPE>", "value": "<TOML_VALUE>"}`.
- `TOML_VALUE` is always a JSON string, including for integers, floats, and booleans.
- `TOML_TYPE` is one of: `string`, `integer`, `float`, `bool`, `datetime`,
  `datetime-local`, `date-local`, `time-local`.
- Offset datetimes are encoded as RFC 3339. Local datetimes are RFC 3339 without
  the offset. Local dates are the date part; local times are the time part.

| TOML | JSON |
|---|---|
| `a = 42` | `{"a": {"type": "integer", "value": "42"}}` |
| `a = true` | `{"a": {"type": "bool", "value": "true"}}` |
| `a = ["a", 2]` | `{"a": [{"type":"string","value":"a"}, {"type":"integer","value":"2"}]}` |
| `[tbl]`<br>`a = 42` | `{"tbl": {"a": {"type": "integer", "value": "42"}}}` |

## Test / Verification Process

The imported source files are placed in a `sources/` subdirectory of the
application directory. Install the harness once (network required, one time
only):

```bash
sh sources/setup_harness.sh
```

Then run the suite from the application directory:

```bash
sh sources/run_conformance.sh
```

Mechanics: `toml-test` holds the corpus internally. For each valid case it pipes
TOML into the decoder on stdin and compares the emitted tagged JSON against the
expected description. For each invalid case it requires a non-zero exit. The
summary is:

```
  valid tests: NNN passed,  N failed
invalid tests: NNN passed,  N failed
```

The passed counts are the correctness score. Exit code is non-zero while any
test fails.

### Useful flags

Flags pass straight through `sources/run_conformance.sh` to `toml-test test`.

- `-run 'valid/string/*'` — run one feature group. Use this to develop one
  construct at a time.
- `-run=valid/string-empty,valid/string-nl` — run named cases.
- `-skip 'invalid/datetime/*'` — exclude a group.
- `-json` — machine-readable report instead of text.
- `-v` — list passing tests as well as failures.
- `-script` — emit a shell script of `-skip` flags for the current failures,
  which is the fastest way to snapshot known failures between passes.

Feature groups available to `-run`:

- valid: `array bool comment datetime float inline-table integer key spec-1.0.0 string table`
- invalid: the above plus `control encoding local-date local-datetime local-time`

## Suggested Implementation Order

TOML parsing is lexically simple and structurally fussy. The difficulty is in
key/table semantics and in rejecting malformed input, not in the grammar.

1. **Scaffolding** — line handling, comments, whitespace, the stdin/stdout/exit
   contract, tagged JSON emission.
2. **Scalars** — booleans, integers (including `0x`, `0o`, `0b`, underscores),
   floats (including `inf`, `nan`, exponents), basic and literal strings, then
   multi-line strings with their line-ending backslash and trimming rules.
3. **Keys** — bare, quoted, and dotted keys; the redefinition rules.
4. **Tables** — `[table]`, `[a.b.c]` implicit creation, `[[array of tables]]`,
   and the rules governing which of these may follow which.
5. **Inline tables and arrays** — including nesting and the TOML 1.0 restriction
   that inline tables are closed to later extension.
6. **Datetimes** — offset, local datetime, local date, local time.
7. **Invalid-input hardening** — control characters, bad UTF-8, duplicate keys,
   redefinition after an inline table, unterminated constructs. This is where
   most of the remaining score lives.

The specification is normative and short. Follow it directly.

## Files the LLM Needs

- `sources/toml-v1.0.0.md` — the specification. Primary input. Required.
- `sources/run_conformance.sh` — the scoring entry point.
- `sources/setup_harness.sh` — one-time harness installation.

## Definition of Done

- A program exists in the target directory called `full_test.sh` which runs the
  full test suite. It is a thin wrapper over `sources/run_conformance.sh` and
  must not filter, skip, or reinterpret the harness result:

  ```sh
  #!/bin/sh
  set -eu
  exec sh sources/run_conformance.sh
  ```
- `sh full_test.sh` runs cleanly with zero errors.
- The program satisfies the stdin → tagged-JSON → exit-code contract.
- Passing count is 100 percent: 210 valid, 499 invalid.
- The LLM writes the parser itself. **`tomllib`, `tomli`, `toml`, `tomlkit`, and
  any other TOML library are forbidden**, whether stdlib or third party. Python's
  stdlib `tomllib` already scores 208/210 and 499/499, so importing it makes the
  exercise meaningless. Permitted stdlib imports are `sys`, `json`, `re`,
  `datetime`, `math`, and `string`.
- No network access at test time after `setup_harness.sh` has run once.
