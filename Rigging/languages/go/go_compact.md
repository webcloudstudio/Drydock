<!-- Compacted from Rigging/languages/go/go.md sha256=a183e28b12b4aae8c36a8850c8b6669fde2d41b37c3f3d8e54f53193d0092a77 on 2026-10-18 by Rigging maintenance -->

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

An Acceptance Criterion (AC) is an executable check of Blueprint-required behavior. Native tests
use `testing` in `*_test.go`; the project gate is `go test ./...`. Within the existing Blueprint
Python AC container, execute a named test through the shipped helper:

```python
from drydock_go import run_test
result = run_test("./internal/orders", "TestCreateOrder")
assert result.passed, (result.status, result.stdout, result.stderr)
```

Drydock stages this helper beside the criterion. It runs `go test -json -count=1 -run` with an
exact test name, retains output and per-test outcomes, and rejects absent/skipped tests as proof.
The enclosing AC provides identity, timeout, result storage and repair state. Compilation errors
remain distinct from assertion failures in `result.status`. Coverage and persistence observations
require explicit instrumentation per criterion; unavailable observations are unknown.

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
