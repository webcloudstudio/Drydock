<!-- Compacted from Rigging/languages/go/go.md sha256=aa96c7155b26f091e4f2ee9b7a47ff2202fc7c162254f2b8676779198c7147da on 2026-10-18 by Rigging maintenance -->

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

Application foundations add packages under `internal/`. The generated persistence library is a
separate module at `persistence/`, linked by the root `go.mod`.

### Native application layouts and fixtures

Initialize the root `go.mod` in the language foundation before the DATABASE block.
Use `cmd/app/main.go` for process startup, `internal/cli` for CLI behavior, and
`internal/appserver` for HTTP behavior. The root application module requires
`drydock.local/persistence v0.0.0` with `replace drydock.local/persistence => ./persistence`;
the generated persistence directory owns its nested module. Run both module test suites.

For a CLI, expose `Run(args []string, stdout, stderr io.Writer) int`, use a local
`flag.FlagSet` with `flag.ContinueOnError`, and test with `bytes.Buffer`. Only main calls
`os.Exit`. For HTTP, expose `NewHandler(...) http.Handler` using `net/http.ServeMux`.
Use `httptest.NewRecorder` and `httptest.NewRequest` for handler tests, or
`httptest.NewServer` with `t.Cleanup(server.Close)` when testing a real HTTP client.
Keep business logic in application packages and persistence access in the shipped library.

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

Use the shipped module in `Rigging/languages/go/persistence/`. Drydock copies it to the Target's
`persistence/`, generates `schema.go`, `testing.go` and a schema command from `DATABASE.md`, and
links it into the existing root `go.mod` as `drydock.local/persistence`. Driver versions and sums
are shipped; SQLite uses `go-sqlite3` (a C compiler and CGO are required), PostgreSQL uses `lib/pq`.
Run `go mod download` during dependency provisioning; execution requires these modules available.

Call `persistence.OpenDatabase(ctx, dsn)`, then typed methods such as
`db.Tickets.List(ctx, persistence.TicketsListInput{Status: "open"})`. Methods return a value and
an error. Optional inputs use pointers; read results are generated structs. Undeclared operations
and unsupported field types fail explicitly. Use `OpenSession(ctx, dsn, ddl)` for native tests;
close with its cleanup function. Empty DSN creates a temporary SQLite store. An explicit DSN uses
the named store and cleanup does not delete it. Both engines ship; the DSN selects one.

The Go library and generator are verified on SQLite and PostgreSQL. Keep application SQL inside
the library; agents write callers. The language foundation must create `go.mod` before the
DATABASE step. Python Blueprint AC containers invoke the native Go tests through `run_test`.

---

## Consumer Rules

- Use `gofmt`, explicit errors, small consumer-owned interfaces and owned goroutine lifetimes.
- Keep business logic in `internal/` and entry points in `cmd/`; commit `go.mod` and `go.sum`.
- Gate with `go vet ./...`, `go build ./...` and `go test -race ./...`.
