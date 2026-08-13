# Build Instructions: TOML 1.0.0 Parser

## Objective

Build a TOML v1.0.0 parser that conforms to the specification in
`sources/toml-v1.0.0.md`. Correctness is measured by the upstream `toml-test`
conformance suite. The goal is to pass every valid and every invalid case the
installed suite supplies, with no case failed, errored, or skipped. The suite's
size is a property of the version `setup_harness.sh` installs; never assert a
case count.

Rejecting invalid input is scored as heavily as accepting valid input. A parser
that is merely permissive fails roughly 70 percent of the suite.

The implementation language is Go, fixed by this Target's `TECHNOLOGY_STACK.md`
and governed by `stack/go.md`. The conformance harness itself is written in Go
but is a scoring instrument, not part of the deliverable.

## Run Harness

`sources/full_test.sh` is the single scoring entry point. It is supplied, not
authored: it is staged verbatim into the build directory alongside the other
imported assets, and `drydock uat` runs `sh sources/full_test.sh` from the
completed application root and takes its exit code and output as the score. It
reads:

```sh
#!/bin/sh
# full_test.sh — scoring entry point. Do not filter, skip, or reinterpret.
set -eu
go build -o toml-decoder ./cmd/toml-decoder
DECODER="$PWD/toml-decoder" exec sh sources/run_conformance.sh
```

The build step is deliberately separate from the scoring step so that a
compilation failure and a conformance failure are distinguishable in the
evidence. `DECODER` is the harness's only knowledge of the implementation
language; the harness itself is language-neutral.

**The scoring assets are read-only.** `sources/full_test.sh`,
`sources/run_conformance.sh`, and `sources/setup_harness.sh` are hash-verified
against the import and restored before grading, so a modification is reported as
tampering rather than honored. Do not write to them. Build `cmd/toml-decoder` so
that the supplied entry point succeeds; changing the entry point is not a
repair.

## Interface Contract

The program is a filter: read TOML from **stdin**, write tagged JSON to
**stdout**, exit `0`. On invalid TOML, write a diagnostic to **stderr** and exit
non-zero. No arguments, no config, no side effects.

Minimal shape (`cmd/toml-decoder/main.go`):

```go
package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"

	"github.com/owner/toml-decoder/internal/toml"
)

func main() {
	input, err := io.ReadAll(os.Stdin)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	tagged, err := toml.Decode(string(input))
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	if err := json.NewEncoder(os.Stdout).Encode(tagged); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
```

The parser lives in `internal/toml`; `main` reads, delegates, and encodes. See
`stack/go.md` for the module layout and the toolchain floor.

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

Then run the suite from the application directory. `DECODER` is required — the
harness has no default implementation language:

```bash
go build -o toml-decoder ./cmd/toml-decoder
DECODER="$PWD/toml-decoder" sh sources/run_conformance.sh
```

During development, `sh sources/full_test.sh` does both steps and is the same
command the score is taken from.

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
- `sources/full_test.sh` — the supplied scoring entry point.
- `sources/run_conformance.sh` — the conformance harness it invokes.
- `sources/setup_harness.sh` — one-time harness installation.

## Definition of Done

- `sh sources/full_test.sh` runs cleanly with zero errors and exits zero.
- The program satisfies the stdin → tagged-JSON → exit-code contract.
- Every supplied valid and invalid case passes: the failed, errored, and skipped
  counts are all zero. The harness exit status is the verdict and the whole
  verdict — assert `returncode == 0` and stop there. Do not assert on the text
  of the summary line at all: the case totals belong to the installed suite, and
  a check that reads a runner's printed output is measuring the runner rather
  than the parser.
- The parser is written from the specification. **Every third-party TOML module is
  forbidden** — `github.com/BurntSushi/toml`, `github.com/pelletier/go-toml`,
  `github.com/naoina/toml`, and any other. `BurntSushi/toml` scores near-perfectly
  on this suite, so importing it makes the exercise meaningless.
- `go.mod` declares no `require` dependencies. The standard library is sufficient:
  `encoding/json`, `strconv`, `strings`, `unicode`, `unicode/utf8`, `time`, `math`,
  `fmt`, `io`, `os`, `errors`.
- No network access at test time after `setup_harness.sh` has run once.
