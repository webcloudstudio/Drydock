<!-- Compacted from Rigging/languages/go/go.md sha256=1126e6e8affc974e2eedef2e5e2091419a6a39dbf24ca6af7dd28df24eb4ef7a on 2026-10-26 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

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

A criterion that exercises the command line runs the built executable through the same helper,
never `go run`, which reports every non-zero program exit as 1:

```python
from drydock_go import cli_runner
code, out, err = cli_runner("--top", "0", "data.csv")
assert code == 2, (code, out, err)
```

`cli_runner` builds the single `./cmd/<name>` main package once with `go build` and returns
`(exit_code, stdout, stderr)`; pass `package="./cmd/<name>"` when there are several, and `input=`
for standard input. A failed build settles the criterion as `execution-error`.

### How does this language provide the shared persistence contract?

Use the shipped module in `Rigging/languages/go/persistence/`. Drydock copies it to the Target's
`persistence/`, generates `schema.go`, `testing.go` and a schema command from `DATABASE.md`, and
links it into the existing root `go.mod` as `drydock.local/persistence`. Driver versions and sums
are shipped; SQLite uses `go-sqlite3` (a C compiler and CGO are required), PostgreSQL uses `lib/pq`.
Run `go mod download` during dependency provisioning; execution requires these modules available.

Call `persistence.OpenDatabase(ctx, dsn)`, then typed methods such as
`db.Tickets.List(ctx, persistence.TicketsListInput{Status: "open"})`. Methods return a value and
an error. Optional inputs use pointers; read results are generated structs. Undeclared operations
and unsupported field types fail explicitly. Use `OpenSession(ctx, dsn)` for native database criteria;
empty DSN selects the configured, provisioned application store. Defer its cleanup and check the
returned error: it rolls back on success and failure, never applies schema or deletes the store.
Pass the same Store to the feature. Other connections and external effects require committed,
idempotent criteria with owned records and supported cleanup. Both engines retain autocommit
outside explicit rollback scopes.

The Go library and generator are verified on SQLite and PostgreSQL. Keep application SQL inside
the library; agents write callers. The language foundation must create `go.mod` before the
DATABASE step. Python Blueprint AC containers invoke the native Go tests through `run_test`.

---

# Go Best Practices — Contract Surface

## Toolchain and Module Layout

### config_key: go.mod
The module declaration specifies the module path, minimum Go version, and exact dependencies.

Constraints: Go 1.22 or newer is required; `go.sum` is committed; `go mod tidy` runs after dependency changes; application logic resides in `internal/`; binaries reside in `cmd/<name>/`; `pkg/` is used only for externally imported libraries.

### Rule: toolchain-validation
Before writing code, verify the installed Go version and stop when it is older than 1.22.

## Errors

### function LoadConfig
Loads and parses a configuration file.

| Parameter | Type |
|---|---|
| `path` | `string` |

Returns `*Config` and `error`.

Constraints: Return errors instead of panicking; wrap added context with `%w`; callers inspect errors with `errors.Is` or `errors.As`; error strings are lowercase without trailing punctuation.

## Types and Interfaces

### interface Store
Provides access to stored data.

| Method | Parameters | Returns |
|---|---|---|
| `Get` | `context.Context`, `id string` | `[]byte`, `error` |

Constraints: Interfaces are defined by consumers, contain one or two methods, and functions accept interfaces but return concrete types.

### function Render
Renders data retrieved from a store.

| Parameter | Type |
|---|---|
| `ctx` | `context.Context` |
| `s` | `Store` |
| `id` | `string` |

Returns `[]byte` and `error`.

### type Buffer
Provides a usable zero-value byte buffer.

### Buffer.Write
Appends bytes to the buffer.

| Parameter | Type |
|---|---|
| `p` | `[]byte` |

Returns the number of bytes written and `error`.

Constraints: The zero value is usable; `context.Context` is the first parameter for I/O, blocking, or spawned-work functions.

## Concurrency

### function Fetch
Fetches results concurrently for a list of URLs.

| Parameter | Type |
|---|---|
| `ctx` | `context.Context` |
| `urls` | `[]string` |

Returns `[]Result` and `error`.

Constraints: Every goroutine has an owner, cancellation path, failure-reporting path, and wait; cancellation flows through `context.Context`; the sender closes channels; shared state uses mutexes and handoff uses channels; builds and CI run `go test -race`.

## Testing

### function ParseDuration
Parses a duration string.

| Parameter | Type |
|---|---|
| `input` | `string` |

Returns `time.Duration` and `error`.

Constraints: Tests use the standard `testing` package, table-driven subtests with `t.Run`, informative failure messages, offline deterministic fixtures, `testdata/`, `t.TempDir()`, and `t.Cleanup()`; no network, credentials, or wall-clock sleeps.

## Build and Verification

### Rule: verification-commands
The project passes the following commands before commit:

```bash
gofmt -l .
go vet ./...
go build ./...
go test -race -cover ./...
```

Constraints: `gofmt -l .` emits no filenames; `CGO_ENABLED=0` is used unless a dependency requires cgo; release builds use `-trimpath`; verification commands are wrapped in one `bin/` script.

## Dependencies

### Rule: dependency-management
Dependencies use the standard library where practical and exact versions for external modules.

Constraints: Check the standard library first; never use `@latest` in committed configuration; run `go mod tidy` after dependency changes; evaluate maintenance, transitive dependencies, and licensing; deprecated or archived dependencies are defects to schedule.
