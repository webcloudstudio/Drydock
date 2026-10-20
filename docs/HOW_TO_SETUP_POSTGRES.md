# How To Set Up PostgreSQL for a Drydock Target

A Target uses PostgreSQL when its `TECHNOLOGY_STACK.md` selects `postgres.md`. Drydock generates
the `persistence/` package from `DATABASE.md`; the application and Drydock's own schema step
connect through one connection string read from `DATABASE_URL`.

## 1. Facts

| Item | Value |
|---|---|
| Stack selection | `postgres.md` (database), with `python.md` or `go.md` (language) |
| Connection string | `DATABASE_URL=postgresql://<user>:<password>@<host>:<port>/<database>` |
| Fallback when unset | `DATABASE_PATH`, then the SQLite file `data/app.db` |
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

Export `DATABASE_URL` in the shell that runs `drydock build`, `drydock score` and QuarterDeck.
Every child process — schema step, acceptance runs, the application — inherits it.

```bash
export DATABASE_URL=postgresql://postgres:drydock@localhost:5432/marina
psql "$DATABASE_URL" -c "select 1"                       # confirm the connection
```

Keep the password out of the repository. Put the export in your shell profile or a local,
untracked environment file.

## 5. Select, Approve, Plan, Build

1. `drydock run`, open the Technology Stack, select the language and `postgres.md`, approve.
2. `drydock plan <Target>`
3. `drydock build <Target>`

For a Python Target, the build log reports `schema applied to postgresql://...` at the DATABASE
block. If it reports `data/app.db`, `DATABASE_URL` was not set in that shell and the build ran
against SQLite. A Go Target reports only `schema applied`; confirm with
`psql "$DATABASE_URL" -c "\dt"` that the tables exist.

For a Python Target, confirm `psycopg[binary]` is in `pyproject.toml`. Without it the schema step
fails with `PostgreSQL was selected by the DSN but no driver is installed`.

## 6. Verify the Shipped Libraries (Drydock Developers)

Drydock's own test suite runs its PostgreSQL integration tests only when given a disposable
database. These tests create and drop their own schemas.

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
- **Silent SQLite fallback.** Selecting `postgres.md` does not by itself connect to PostgreSQL;
  only `DATABASE_URL` does. Check the build log as in step 5.
- **One database per Target.** Reusing a database across Targets mixes their tables.
