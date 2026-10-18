<!-- Compacted from Rigging/stack/go.md sha256=07bdff2ccd97c4a591b65059142bf82632e2cd732fd70c205d8449e1bfa53036 on 2026-10-18 by Rigging maintenance — regenerate with: drydock rigging compact --include-file Rigging/stack/go.md -->

## Foundation Contract

The published shape of this foundation. It is built before every other foundation: a web server,
a database, or a CLI is built *into* this tree, this environment, and this test runner. Carried
verbatim into `go_compact.md`.

- source_root: internal/
- test_command: go test ./...
- environment: the module declared in `go.mod`; no vendored toolchain
- dependencies: `go.mod`

```
project/
  go.mod                  # module path; the Go toolchain version
  cmd/                    # one directory per binary, each package main
  internal/               # application packages; not importable outside this module
  bin/                    # launchers; each runs the toolchain, never a vendored copy
```

A later foundation adds packages under `internal/`; it does not restructure this tree.

### How do we execute and measure Acceptance Criteria in this language?

An Acceptance Criterion (AC) is an executable check of Blueprint-required behavior. Put native
checks in `*_test.go` using `testing`; run `go test ./...`, or select a named test with `-run`.
Use `go test -json -count=1 ./...` for fresh, machine-readable test results. Associate test names
with Blueprint criterion IDs and retain observed values, output and results; a failing test
fails the check. Coverage and persistence interaction observations must be collected explicitly
and associated with the criterion; aggregate suite coverage does not identify an individual
criterion's exercised code. Missing observations are unknown. Drydock's current Programmatic
Acceptance harness executes Python scripts, not Go fences: use a Python criterion to invoke
and assert on the Go command result. Native Go criterion execution is not implemented.

### How does this language provide the shared persistence contract?

No Go persistence library is shipped or verified. Drydock currently rejects Go Targets declaring
`DATABASE.md`. A Go implementation must ship a reusable library implementing the shared
operations in `stack/persistence.md`, with language-native bindings and fixtures, engine drivers
pinned in `go.mod`/`go.sum`, and schema declarations generated from `DATABASE.md`. Application
code calls that library; build agents do not invent an access layer. Library release, generator
support and engine integration tests are required before advertising Go persistence support.

---

## Consumer Rules

- Use `gofmt`, explicit errors, small consumer-owned interfaces and owned goroutine lifetimes.
- Keep business logic in `internal/` and entry points in `cmd/`; commit `go.mod` and `go.sum`.
- Gate with `go vet ./...`, `go build ./...` and `go test -race ./...`.
