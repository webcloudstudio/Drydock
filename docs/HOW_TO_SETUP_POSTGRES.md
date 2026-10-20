# How To Set Up PostgreSQL for a Drydock Target

A Target uses PostgreSQL when its `TECHNOLOGY_STACK.md` selects `postgres.md`. Drydock generates
the `persistence/` package from `DATABASE.md`. The `drydock config` key `postgres_dsn` names the
server; Drydock passes it to the schema step, acceptance runs and the application as
`DATABASE_URL`.

## 1. Facts

| Item | Value |
|---|---|
| Stack selection | `postgres.md` (database), with `python.md` or `go.md` (language) |
| Connection string | `drydock config set postgres_dsn postgresql://<user>:<password>@<host>:<port>/<database>` |
| Environment override | `POSTGRES_DSN` |
| Passed to the Target as | `DATABASE_URL` |
| When unset | `drydock build`, `drydock score ac` and `drydock score release` stop with exit 1 |
| Python driver | `psycopg[binary]` in the Target's dependencies |
| Go driver | `github.com/lib/pq`, pinned in the shipped persistence module |
| Schema | `schema.sql`, generated from `DATABASE.md`, `CREATE ... IF NOT EXISTS` |
| Schema applied | At the DATABASE block and before every acceptance run |

The library chooses the database from the connection string prefix: `postgresql://` or
`postgres://` opens PostgreSQL, and anything else is a SQLite file path.

## 2. Run a PostgreSQL Server

Docker:

```bash
docker run -d --name drydock-pg --restart unless-stopped \
  -e POSTGRES_PASSWORD=drydock -p 5432:5432 postgres:16
```

Or a native install under Ubuntu/WSL:

```bash
sudo apt install postgresql
sudo service postgresql start
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'drydock';"
```

## 3. Create One Database per Target

Tables are named from `DATABASE.md`, so two Targets in one database collide on names such as
`tickets`. Give each Target its own database:

```bash
docker exec drydock-pg createdb -U postgres marina      # Docker
sudo -u postgres createdb marina                         # native
```

## 4. Point Drydock at It

```bash
drydock config set postgres_dsn postgresql://postgres:drydock@localhost:5432/marina
drydock config show                                      # password shown as ***
psql postgresql://postgres:drydock@localhost:5432/marina -c "select 1"   # confirm the connection
```

The value is stored in the user configuration file, never in the repository. The setting applies
to every Target. To build a second Target against its own database, override it for that
command:

```bash
POSTGRES_DSN=postgresql://postgres:drydock@localhost:5432/other drydock build Other
```

## 5. Select, Approve, Plan, Build

1. `drydock run`, open the Technology Stack, select the language and `postgres.md`, approve.
2. `drydock plan <Target>`
3. `drydock build <Target>`

If `postgres_dsn` is not set, the build stops before any work with:

```text
postgres.md is selected but no PostgreSQL connection string is configured.
  Run: drydock config set postgres_dsn postgresql://<user>:<password>@<host>:<port>/<database>
```

The build log reports `persistence: schema applied` at the DATABASE block. Confirm the tables
with `psql <dsn> -c "\dt"`. A wrong host, password or database fails that step and stops the
build.

For a Python Target, confirm `psycopg[binary]` is in `pyproject.toml`. Without it the schema step
fails with `PostgreSQL was selected by the DSN but no driver is installed`.

## 6. Verify the Shipped Libraries (Drydock Developers)

Drydock's own test suite runs its PostgreSQL integration tests only when given a disposable
database. These tests create and drop their own schemas, so they read a separate variable,
never `postgres_dsn`, and cannot reach a Target database.

```bash
docker exec drydock-pg createdb -U postgres drydock_test
export DRYDOCK_TEST_POSTGRES_DSN=postgresql://postgres:drydock@localhost:5432/drydock_test
python -m pytest -p no:randomly tests/test_shipped_database.py tests/test_database_go.py
```

The Go tests also need the pinned drivers in the module cache, once:

```bash
cd Rigging/languages/go/persistence && go mod download
```

Without `DRYDOCK_TEST_POSTGRES_DSN` these tests are skipped, not passed.

## 7. Limits

- **No migrations.** `CREATE ... IF NOT EXISTS` never alters an existing table. After changing a
  table in `DATABASE.md`, drop and recreate the Target database:
  `dropdb marina && createdb marina`.
- **One database per Target.** `postgres_dsn` is shared by every Target. Reusing one database
  across Targets mixes their tables; override `POSTGRES_DSN` per Target as in step 4.
- **Connection checked at the DATABASE block.** Drydock checks that `postgres_dsn` is set before
  the build starts, but first connects at the DATABASE block, after the language foundation.
