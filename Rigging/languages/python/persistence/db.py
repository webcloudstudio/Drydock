"""Persistence access for a Drydock Target.

This file is shipped by Drydock and copied into the build unchanged. Do not edit it here: edit
``DATABASE.md`` and rebuild. It is hardened and tested once, in Drydock's own suite, so every
Target inherits a persistence layer that has already passed rather than one re-derived from prose
on each build.

The application-facing surface is ``Database``. One attribute per declared table, one method per
declared access pattern::

    db = Database(dsn, SCHEMA)
    ticket = db.tickets.get(id=7)
    open_tickets = db.tickets.list(status="open")

``schema.py`` beside this file is generated from ``DATABASE.md`` and carries the tables, the
operations, and the row types. It contains no SQL. Statements are constructed here, by the driver
for the engine in use, so a parameter placeholder never appears in generated code or in a caller.

Values reach the database as bound parameters, never as formatted text. Identifiers cannot be
bound in any engine, so they are taken only from the generated schema — which Drydock validated
against ``^[a-z][a-z0-9_]*$`` before emitting it — and are quoted on the way out.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, fields
from contextlib import contextmanager, nullcontext
import threading
from typing import Any

__all__ = [
    "Database",
    "Driver",
    "Operation",
    "PersistenceError",
    "Schema",
    "Table",
    "statements",
    "UnknownOperation",
    "begin_acceptance_transaction",
    "end_acceptance_transaction",
]

VERBS = ("get", "list", "create", "update", "delete")
#: The comparisons a declared Match term may state; anything else is refused before SQL is built.
COMPARISONS = ("=", "<", "<=", ">", ">=")
DIRECTIONS = ("asc", "desc")


class PersistenceError(RuntimeError):
    """A persistence failure the caller may act on, raised in place of a driver exception."""


class UnknownOperation(PersistenceError):
    """A verb was requested that the declaration does not grant for that table."""


@dataclass(frozen=True)
class Table:
    """One declared table: its columns and the column that identifies a row."""

    name: str
    columns: tuple[str, ...]
    primary_key: str | None = None


@dataclass(frozen=True)
class Operation:
    """One declared access pattern, reduced to what executing it requires.

    ``name`` is the method callers use and ``verb`` is its Kind, how it runs; a name that is a
    verb runs as that verb. ``inputs`` are the parameters the caller supplies. ``match`` is the
    equality predicate of a ``get``, ``update``, ``upsert``, or ``delete``, every field of it
    required; a ``list`` filters on whichever inputs are supplied, and the inputs of a
    ``create``, ``update``, or ``upsert`` outside ``match`` are the values written. ``row`` is the dataclass the operation returns, and
    ``columns`` are its fields; an operation with no ``row`` returns a count. ``compare`` holds
    ``(field, op, column)`` for each input compared other than by equality with its own column,
    such as ``("start_date", ">=", "date")``, and ``order`` the ``(column, direction)`` sort keys
    of a ``list``.
    """

    identifier: str
    table: str
    verb: str
    inputs: tuple[str, ...]
    row: type | None = None
    columns: tuple[str, ...] = ()
    match: tuple[str, ...] = ()
    name: str = ""
    compare: tuple[tuple[str, str, str], ...] = ()
    order: tuple[tuple[str, str], ...] = ()

    def keys(self) -> tuple[str, ...]:
        """The match fields compared by equality: what reads back the one row a write reached."""
        compared = {field for field, op, _ in self.compare if op != "="}
        return tuple(name for name in self.match if name not in compared)


@dataclass(frozen=True)
class Schema:
    """The generated declaration: every table and every operation reaching one."""

    tables: tuple[Table, ...]
    operations: tuple[Operation, ...]

    def by_table(self) -> dict[str, tuple[Operation, ...]]:
        grouped: dict[str, list[Operation]] = {table.name: [] for table in self.tables}
        for operation in self.operations:
            grouped.setdefault(operation.table, []).append(operation)
        return {name: tuple(items) for name, items in grouped.items()}


class Driver:
    """Statement construction shared by every engine.

    Subclasses supply connection handling and the two things engines genuinely disagree about:
    how a parameter is spelled, and how a freshly inserted row reports its key. Everything else is
    identical SQL, so it is written once here rather than twice in the engines.
    """

    def prepare_schema(self, sql: str) -> str:
        """Translate generated DDL for this engine."""
        return sql

    #: Spelled by the DB-API driver, not by this class's callers.
    paramstyle = "qmark"
    returning = False

    def connect(self) -> Any:  # pragma: no cover - engine specific
        raise NotImplementedError

    def pin(self) -> Any:  # pragma: no cover - engine specific
        """Serve one connection to every thread until ``close``. The acceptance harness's."""
        raise NotImplementedError

    def identity(self) -> str:  # pragma: no cover - engine specific
        """Name the store, so two spellings of one DSN share one acceptance transaction."""
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - engine specific
        raise NotImplementedError

    def placeholder(self, index: int) -> str:
        """Render parameter ``index`` (0-based) in this engine's spelling."""
        return "?" if self.paramstyle == "qmark" else "%s"

    @staticmethod
    def quote(identifier: str) -> str:
        """Quote a declared identifier. Never called with caller-supplied text."""
        if not identifier.replace("_", "").isalnum():
            raise PersistenceError(f"refusing unsafe identifier {identifier!r}")
        return f'"{identifier}"'

    def _predicate(
        self, names: Sequence[str], start: int = 0, compare: Sequence[tuple[str, str, str]] = ()
    ) -> str:
        """``names`` are input fields; each is compared with its declared column, else its own."""
        by_field = {field: (op, column) for field, op, column in compare}
        terms = []
        for offset, name in enumerate(names):
            op, column = by_field.get(name, ("=", name))
            if op not in COMPARISONS:
                raise PersistenceError(f"refusing undeclared comparison {op!r}")
            terms.append(f"{self.quote(column)} {op} {self.placeholder(start + offset)}")
        return " AND ".join(terms)

    def select(
        self,
        table: str,
        columns: Sequence[str],
        predicate: Sequence[str],
        compare: Sequence[tuple[str, str, str]] = (),
        order: Sequence[tuple[str, str]] = (),
    ) -> str:
        selected = ", ".join(self.quote(name) for name in columns)
        statement = f"SELECT {selected} FROM {self.quote(table)}"
        if predicate:
            statement += f" WHERE {self._predicate(predicate, 0, compare)}"
        if order:
            for _, direction in order:
                if direction not in DIRECTIONS:
                    raise PersistenceError(f"refusing undeclared order {direction!r}")
            keys = ", ".join(
                f"{self.quote(column)} {direction.upper()}" for column, direction in order
            )
            statement += f" ORDER BY {keys}"
        return statement

    def insert(self, table: str, columns: Sequence[str], key: str | None) -> str:
        names = ", ".join(self.quote(name) for name in columns)
        marks = ", ".join(self.placeholder(index) for index in range(len(columns)))
        statement = f"INSERT INTO {self.quote(table)} ({names}) VALUES ({marks})"
        if self.returning and key:
            statement += f" RETURNING {self.quote(key)}"
        return statement

    def update(
        self,
        table: str,
        columns: Sequence[str],
        predicate: Sequence[str],
        compare: Sequence[tuple[str, str, str]] = (),
    ) -> str:
        assignments = ", ".join(
            f"{self.quote(name)} = {self.placeholder(index)}" for index, name in enumerate(columns)
        )
        statement = f"UPDATE {self.quote(table)} SET {assignments}"
        if predicate:
            statement += f" WHERE {self._predicate(predicate, len(columns), compare)}"
        return statement

    def upsert(self, table: str, columns: Sequence[str], match: Sequence[str]) -> str:
        """Insert a row, or replace the Set columns of the row ``match`` identifies.

        ``match`` names a declared unique key, which is what ``ON CONFLICT`` requires; SQLite
        and PostgreSQL spell the statement identically.
        """
        assigned = [name for name in columns if name not in match]
        target = ", ".join(self.quote(name) for name in match)
        action = (
            "DO UPDATE SET "
            + ", ".join(f"{self.quote(name)} = excluded.{self.quote(name)}" for name in assigned)
            if assigned
            else "DO NOTHING"
        )
        return f"{self.insert(table, columns, None)} ON CONFLICT ({target}) {action}"

    def delete(
        self, table: str, predicate: Sequence[str], compare: Sequence[tuple[str, str, str]] = ()
    ) -> str:
        statement = f"DELETE FROM {self.quote(table)}"
        if predicate:
            statement += f" WHERE {self._predicate(predicate, 0, compare)}"
        return statement

    def inserted_key(self, cursor: Any) -> Any:  # pragma: no cover - engine specific
        raise NotImplementedError


class TableAccess:
    """The methods one table grants, bound from the declaration rather than defined by hand."""

    def __init__(self, table: Table, operations: Iterable[Operation], database: Database) -> None:
        self._table = table
        self._database = database
        self._operations = {operation.name or operation.verb: operation for operation in operations}

    def __repr__(self) -> str:
        granted = ", ".join(sorted(self._operations))
        return f"<TableAccess {self._table.name}: {granted or 'no declared operation'}>"

    def __getattr__(self, name: str) -> Callable[..., Any]:
        operation = self._operations.get(name)
        if operation is None:
            granted = ", ".join(sorted(self._operations)) or "none"
            raise UnknownOperation(
                f"{self._table.name} declares no {name!r} operation. Declared: {granted}. "
                "Add an access pattern to DATABASE.md rather than reaching around this class."
            )
        return lambda **arguments: self._database.run(operation, arguments)


class _AcceptanceTransaction:
    """One transaction per store, shared by every ``Database`` this process opens; never committed.

    The acceptance harness begins it before a criterion runs and rolls it back when the criterion
    ends. The criterion's fixture, the application behind an in-process HTTP client, and an
    in-process command all join it, so setup, behavior and readback see one another's writes and
    none of them persists. A crash loses nothing: an engine discards an uncommitted transaction.
    """

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self._drivers: dict[str, Driver] = {}

    def join(self, driver: Driver) -> Driver:
        with self.lock:
            shared = self._drivers.get(driver.identity())
            if shared is None:
                cursor = driver.pin().cursor()
                try:
                    cursor.execute("BEGIN")
                finally:
                    cursor.close()
                shared = self._drivers[driver.identity()] = driver
            return shared

    def rollback(self) -> None:
        failures = []
        with self.lock:
            for identity, driver in self._drivers.items():
                try:
                    cursor = driver.pin().cursor()
                    try:
                        cursor.execute("ROLLBACK")
                    finally:
                        cursor.close()
                except Exception as exc:  # noqa: BLE001 - every store is still closed
                    failures.append(f"{identity}: {exc}")
                finally:
                    driver.close()
            self._drivers.clear()
        if failures:
            raise PersistenceError("acceptance rollback failed: " + "; ".join(failures))


_harness: _AcceptanceTransaction | None = None


def begin_acceptance_transaction() -> None:
    """Join every store this process opens from now on to one transaction the harness owns."""
    global _harness
    if _harness is None:
        _harness = _AcceptanceTransaction()


def end_acceptance_transaction() -> None:
    """Roll back the harness's transaction on every store it joined."""
    global _harness
    harness, _harness = _harness, None
    if harness is not None:
        harness.rollback()


class Database:
    """One store, presented to callers as declared tables with declared methods.

    Callers construct one instance, share it freely, and call methods synchronously. Connection
    handling is internal and may change without affecting any caller.
    """

    def __init__(self, dsn: str, schema: Schema, *, driver: Driver | None = None) -> None:
        self._rollback_owner = None
        self._schema = schema
        driver = driver if driver is not None else open_driver(dsn)
        self._harness = _harness
        self._driver = self._harness.join(driver) if self._harness is not None else driver
        grouped = schema.by_table()
        for table in schema.tables:
            setattr(self, table.name, TableAccess(table, grouped.get(table.name, ()), self))

    @property
    def driver(self) -> Driver:
        if self._harness is not None:
            raise PersistenceError("driver access is forbidden inside the acceptance transaction")
        if self._rollback_owner is not None:
            raise PersistenceError("driver access is forbidden inside a rollback session")
        return self._driver

    def close(self) -> None:
        if self._harness is not None:
            return  # the acceptance harness owns the shared connection
        if self._rollback_owner is not None:
            raise PersistenceError("the rollback session owns connection lifetime")
        self._driver.close()

    @contextmanager
    def rollback_session(self):
        """Use this connection for setup, behavior and assertions; always roll back.

        Normal calls remain autocommitted. No schema creation, nested transaction,
        driver escape, or cross-thread operation is allowed in this scope. Under the acceptance
        harness the scope is the harness's transaction, rolled back when the criterion ends, so
        leaving it rolls nothing back.
        """
        if self._harness is not None:
            yield self
            return
        if self._rollback_owner is not None:
            raise PersistenceError("nested rollback session")
        connection = self._driver.connect()
        cursor = connection.cursor()
        try:
            cursor.execute("BEGIN")
            self._rollback_owner = threading.get_ident()
            try:
                yield self
            finally:
                try:
                    cursor.execute("ROLLBACK")
                except Exception as exc:
                    raise PersistenceError(f"acceptance rollback failed: {exc}") from exc
                finally:
                    self._rollback_owner = None
        finally:
            cursor.close()
            self._driver.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def execute_script(self, sql: str) -> None:
        """Apply generated DDL. The schema is built once, at the DATABASE build step."""
        if self._rollback_owner is not None or self._harness is not None:
            raise PersistenceError("schema and transaction SQL are forbidden in rollback sessions")
        cursor = self._open("schema")
        try:
            for statement in statements(self._driver.prepare_schema(sql)):
                cursor.execute(statement)
        finally:
            cursor.close()

    def run(self, operation: Operation, arguments: Mapping[str, Any]) -> Any:
        """Execute one declared operation with bound parameters."""
        unknown = sorted(set(arguments) - set(operation.inputs))
        if unknown:
            raise PersistenceError(
                f"{operation.identifier} does not accept {', '.join(unknown)}. Declared inputs: "
                f"{', '.join(operation.inputs) or 'none'}."
            )
        if operation not in self._schema.operations:
            raise UnknownOperation(f"{operation.identifier} is not a declared operation")
        missing = [name for name in self._match(operation) if name not in arguments]
        if missing:
            raise PersistenceError(f"{operation.identifier} requires {', '.join(missing)}")
        if operation.verb == "delete" and not arguments:
            raise PersistenceError(f"{operation.identifier} requires a delete predicate")
        names = [name for name in operation.inputs if name in arguments]
        values = [arguments[name] for name in names]
        # The harness's one connection serves the criterion and the application's request
        # threads alike, so an operation holds it for its whole statement and savepoint.
        with self._harness.lock if self._harness is not None else nullcontext():
            scoped = self._rollback_owner is not None or self._harness is not None
            cursor = self._open(operation.identifier)
            try:
                if scoped:
                    cursor.execute("SAVEPOINT drydock_operation")
                result = self._dispatch(operation, cursor, names, values)
                if scoped:
                    cursor.execute("RELEASE SAVEPOINT drydock_operation")
                return result
            except Exception as exc:  # noqa: BLE001 - translated at the boundary on purpose
                if scoped:
                    cursor.execute("ROLLBACK TO SAVEPOINT drydock_operation")
                    cursor.execute("RELEASE SAVEPOINT drydock_operation")
                raise PersistenceError(f"{operation.identifier} failed: {exc}") from exc
            finally:
                cursor.close()

    def _open(self, action: str) -> Any:
        """Return a cursor, translating a refused or failed connection."""
        if self._rollback_owner not in (None, threading.get_ident()):
            raise PersistenceError("rollback session requires its owning thread and connection")
        try:
            return self._driver.connect().cursor()
        except PersistenceError:
            raise
        except Exception as exc:  # noqa: BLE001 - translated at the boundary on purpose
            raise PersistenceError(f"{action} could not connect: {exc}") from exc

    def _dispatch(
        self,
        operation: Operation,
        cursor: Any,
        names: list[str],
        values: list[Any],
    ) -> Any:
        verb = operation.verb
        table = operation.table
        match = self._match(operation)
        if verb in ("get", "list"):
            columns = operation.columns or self._columns(table)
            statement = self._driver.select(
                table, columns, names, operation.compare, operation.order
            )
            cursor.execute(statement, values)
            rows = cursor.fetchall() if verb == "list" else cursor.fetchmany(1)
            built = [self._build(operation, columns, row) for row in rows]
            return built if verb == "list" else (built[0] if built else None)
        if verb == "create":
            key = self._primary_key(table)
            cursor.execute(self._driver.insert(table, names, key), values)
            identity = self._driver.inserted_key(cursor)
            if operation.row is None:
                return identity
            # The declared Output row, read back so column defaults are included. A supplied key
            # wins over the engine's report: SQLite's lastrowid is the rowid, not a text key.
            if key is None:
                return self._build(operation, names, values)
            if key in names:
                identity = values[names.index(key)]
            columns = operation.columns or self._columns(table)
            cursor.execute(self._driver.select(table, columns, [key]), [identity])
            return self._build(operation, columns, cursor.fetchone())
        if verb == "update":
            if not match:
                raise PersistenceError(f"{operation.identifier} updates {table} without a match")
            assigned = [name for name in names if name not in match]
            if not assigned:
                raise PersistenceError(f"{operation.identifier} supplies no column to set")
            keys = [values[names.index(name)] for name in match]
            ordered = [values[names.index(name)] for name in assigned] + keys
            cursor.execute(self._driver.update(table, assigned, match, operation.compare), ordered)
            if operation.row is None:
                return cursor.rowcount
            if not cursor.rowcount:
                return None
            # The declared Output row, read back by its equality match so unassigned columns are
            # included; a row-returning update matches a unique key by equality.
            columns = operation.columns or self._columns(table)
            equal = operation.keys() if operation.match else match
            cursor.execute(
                self._driver.select(table, columns, equal, operation.compare),
                [values[names.index(name)] for name in equal],
            )
            return self._build(operation, columns, cursor.fetchone())
        if verb == "upsert":
            cursor.execute(self._driver.upsert(table, names, match), values)
            if operation.row is None:
                return cursor.rowcount
            columns = operation.columns or self._columns(table)
            keys = [values[names.index(name)] for name in match]
            cursor.execute(self._driver.select(table, columns, match), keys)
            return self._build(operation, columns, cursor.fetchone())
        if verb == "delete":
            cursor.execute(self._driver.delete(table, names, operation.compare), values)
            if operation.row is None:
                return cursor.rowcount
            # The declared Output, built from the key it was given; None when nothing matched.
            return self._build(operation, names, values) if cursor.rowcount else None
        raise UnknownOperation(f"{operation.identifier} names unsupported verb {verb!r}")

    def _columns(self, table: str) -> tuple[str, ...]:
        for declared in self._schema.tables:
            if declared.name == table:
                return declared.columns
        raise PersistenceError(f"{table} is not a declared table")

    def _match(self, operation: Operation) -> tuple[str, ...]:
        """The required equality predicate; a schema generated without one keys by the PK."""
        if operation.match or operation.verb not in ("get", "update", "delete"):
            return operation.match
        key = self._primary_key(operation.table)
        if key and (operation.verb == "update" or key in operation.inputs):
            return (key,)
        return ()

    def _primary_key(self, table: str) -> str | None:
        for declared in self._schema.tables:
            if declared.name == table:
                return declared.primary_key
        return None

    @staticmethod
    def _build(operation: Operation, columns: Sequence[str], row: Sequence[Any]) -> Any:
        if operation.row is None:
            return dict(zip(columns, row, strict=False))
        accepted = {field.name for field in fields(operation.row)}
        return operation.row(**{
            name: value for name, value in zip(columns, row, strict=False) if name in accepted
        })


def statements(sql: str) -> list[str]:
    """Split a DDL script into statements.

    Comment lines are dropped and a semicolon inside a quoted literal does not end a statement —
    a ``DEFAULT \'a;b\'`` would otherwise be cut in half, and the halves are not valid SQL.
    """
    body = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    parts: list[str] = []
    current: list[str] = []
    quoted = False
    for character in body:
        if character == "'":
            quoted = not quoted
        if character == ";" and not quoted:
            parts.append("".join(current))
            current = []
            continue
        current.append(character)
    parts.append("".join(current))
    return [statement.strip() for statement in parts if statement.strip()]


def open_driver(dsn: str) -> Driver:
    """Select the engine from the DSN, so one build serves SQLite in test and Postgres in production."""
    scheme = dsn.split("://", 1)[0].lower() if "://" in dsn else "sqlite"
    if scheme in ("postgres", "postgresql"):
        try:
            from .postgres import PostgresDriver
        except ImportError:  # flat layout
            from postgres import PostgresDriver

        return PostgresDriver(dsn)
    if scheme in ("sqlite", "file") or "://" not in dsn:
        try:
            from .sqlite import SqliteDriver
        except ImportError:  # flat layout
            from sqlite import SqliteDriver

        return SqliteDriver(dsn)
    raise PersistenceError(
        f"no persistence driver for {scheme!r}. Drydock ships sqlite and postgres; add a driver "
        "beside this file and a branch here for another engine."
    )
