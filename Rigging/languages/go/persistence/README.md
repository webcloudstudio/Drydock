# Go persistence library

The shipped Go module implements the shared declared-table operations. `db.go` owns the public
schema/operation types, bound statements and results; `sqlite.go` and `postgres.go` supply drivers.
`go.mod`/`go.sum` pin dependencies. SQLite requires CGO and a C compiler.

Drydock copies these sources unchanged into the Target's `persistence/` module, generates its
schema and typed repositories, and adds a local module replacement to the root `go.mod`.
The language foundation must exist first. `../templates/` owns generated support-file shapes.

- `go test -race ./...`: real SQLite operation and constraint checks.
- Set `DRYDOCK_TEST_POSTGRES_DSN` to a disposable PostgreSQL database to run the same checks there.
- `tests/test_database_go.py`: generator, typed callers and schema-application integration.
- Dependency downloads are setup; offline test runs use cached pinned drivers (`GOPROXY=off`).

Errors propagate through returned errors; undeclared calls satisfy `errors.Is(err, ErrUnknownOperation)`.
`OpenSession` removes only temporary stores it creates. Tests against an explicit DSN own their data.
Generated DDL creates absent objects; it does not migrate existing tables. PostgreSQL integer primary
keys receive an identity declaration matching SQLite's generated-key behavior.
