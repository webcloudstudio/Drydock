"""The shipped persistence layer is tested once, here, so every Target inherits a passing one.

``Rigging/database/`` is copied into a build unchanged. It is not generated and not re-derived
from prose on each build, so its behaviour is Drydock's responsibility rather than the build
agent's.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock.paths import get_database_dir, get_rigging_root


def _load(name: str):
    directory = get_database_dir()
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    spec = importlib.util.spec_from_file_location(name, directory / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


db = _load("db")
sqlite_driver = _load("sqlite")
postgres_driver = _load("postgres")


@dataclass(frozen=True)
class Ticket:
    id: int
    status: str
    title: str


TICKETS = db.Table(name="tickets", columns=("id", "status", "title"), primary_key="id")
SCHEMA = db.Schema(
    tables=(TICKETS,),
    operations=(
        db.Operation("FEATURE-TICKET-001", "tickets", "create", ("status", "title")),
        db.Operation("FEATURE-TICKET-002", "tickets", "get", ("id",), Ticket, TICKETS.columns),
        db.Operation("FEATURE-TICKET-003", "tickets", "list", ("status",), Ticket, TICKETS.columns),
        db.Operation("FEATURE-TICKET-004", "tickets", "update", ("id", "status")),
        db.Operation("FEATURE-TICKET-005", "tickets", "delete", ("id",)),
    ),
)
DDL = (
    'CREATE TABLE IF NOT EXISTS "tickets" ("id" INTEGER PRIMARY KEY, '
    '"status" TEXT NOT NULL DEFAULT \'open\', "title" VARCHAR(200) NOT NULL);'
)


@pytest.fixture
def database(tmp_path: Path):
    instance = db.Database(str(tmp_path / "app.db"), SCHEMA)
    instance.execute_script(DDL)
    yield instance
    instance.close()


def test_every_declared_verb_round_trips_on_sqlite(database):
    identity = database.tickets.create(status="open", title="Plan discovery")

    fetched = database.tickets.get(id=identity)
    assert isinstance(fetched, Ticket)
    assert (fetched.status, fetched.title) == ("open", "Plan discovery")

    assert [row.id for row in database.tickets.list(status="open")] == [identity]

    assert database.tickets.update(id=identity, status="closed") == 1
    assert database.tickets.list(status="open") == []

    assert database.tickets.delete(id=identity) == 1
    assert database.tickets.get(id=identity) is None


def test_a_length_declaration_is_accepted_and_not_enforced_by_sqlite(database):
    identity = database.tickets.create(status="open", title="x" * 500)

    assert database.tickets.get(id=identity).title == "x" * 500


def test_an_undeclared_verb_names_what_the_table_does_grant(database):
    with pytest.raises(db.UnknownOperation, match="create, delete, get, list, update"):
        database.tickets.truncate()


def test_an_undeclared_input_is_refused_rather_than_ignored(database):
    with pytest.raises(db.PersistenceError, match="does not accept owner"):
        database.tickets.list(owner="ed")


def test_a_driver_failure_is_translated_at_the_boundary(database):
    database.execute_script('DROP TABLE "tickets";')

    with pytest.raises(db.PersistenceError, match="FEATURE-TICKET-003 failed"):
        database.tickets.list(status="open")


def test_an_unsafe_identifier_is_refused_before_it_reaches_sql():
    with pytest.raises(db.PersistenceError, match="unsafe identifier"):
        db.Driver.quote('tickets"; DROP TABLE tickets; --')


def test_each_thread_opens_its_own_sqlite_connection(tmp_path: Path):
    driver = sqlite_driver.SqliteDriver(str(tmp_path / "app.db"))
    seen: list[int] = []

    def record() -> None:
        seen.append(id(driver.connect()))

    record()
    worker = threading.Thread(target=record)
    worker.start()
    worker.join()

    assert len(set(seen)) == 2


def test_postgres_builds_format_placeholders_and_returns_the_generated_key():
    driver = postgres_driver.PostgresDriver("postgresql://localhost/app")

    assert driver.select("tickets", ("id",), ("status",)) == (
        'SELECT "id" FROM "tickets" WHERE "status" = %s'
    )
    assert driver.insert("tickets", ("status",), "id") == (
        'INSERT INTO "tickets" ("status") VALUES (%s) RETURNING "id"'
    )


def test_sqlite_builds_qmark_placeholders_and_no_returning_clause():
    driver = sqlite_driver.SqliteDriver(":memory:")

    assert driver.update("tickets", ("status",), ("id",)) == (
        'UPDATE "tickets" SET "status" = ? WHERE "id" = ?'
    )
    assert driver.insert("tickets", ("status",), "id") == (
        'INSERT INTO "tickets" ("status") VALUES (?)'
    )


def test_the_dsn_selects_the_engine_and_an_unsupported_one_names_the_gap():
    assert isinstance(db.open_driver("sqlite:///tmp/app.db"), sqlite_driver.SqliteDriver)
    assert isinstance(db.open_driver("/tmp/app.db"), sqlite_driver.SqliteDriver)
    assert isinstance(db.open_driver("postgresql://localhost/app"), postgres_driver.PostgresDriver)

    with pytest.raises(db.PersistenceError, match="no persistence driver for 'mysql'"):
        db.open_driver("mysql://localhost/app")


def test_postgres_reports_a_missing_driver_as_a_dependency_gap(monkeypatch):
    monkeypatch.setitem(sys.modules, "psycopg", None)
    monkeypatch.setitem(sys.modules, "psycopg2", None)

    with pytest.raises(db.PersistenceError, match="no driver is installed"):
        postgres_driver.PostgresDriver("postgresql://localhost/app").connect()


def test_the_adapter_directory_resolves_beside_the_rest_of_rigging():
    directory = get_database_dir()

    assert directory == get_rigging_root() / "database"
    assert {path.name for path in directory.glob("*.py")} == {"db.py", "sqlite.py", "postgres.py"}
