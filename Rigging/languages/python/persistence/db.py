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
]

VERBS = ("get", "list", "create", "update", "delete")


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

    ``inputs`` are the parameters the caller supplies; for ``get``, ``list``, and ``delete`` they
    are the predicate, and for ``create`` and ``update`` they are the values written. ``row`` is
    the dataclass a read returns, and ``columns`` are the columns it selects.
    """

    identifier: str
    table: str
    verb: str
    inputs: tuple[str, ...]
    row: type | None = None
    columns: tuple[str, ...] = ()
    key: str | None = None


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

    def _predicate(self, names: Sequence[str], start: int = 0) -> str:
        return " AND ".join(
            f"{self.quote(name)} = {self.placeholder(start + offset)}"
            for offset, name in enumerate(names)
        )

    def select(self, table: str, columns: Sequence[str], predicate: Sequence[str]) -> str:
        selected = ", ".join(self.quote(name) for name in columns)
        statement = f"SELECT {selected} FROM {self.quote(table)}"
        if predicate:
            statement += f" WHERE {self._predicate(predicate)}"
        return statement

    def insert(self, table: str, columns: Sequence[str], key: str | None) -> str:
        names = ", ".join(self.quote(name) for name in columns)
        marks = ", ".join(self.placeholder(index) for index in range(len(columns)))
        statement = f"INSERT INTO {self.quote(table)} ({names}) VALUES ({marks})"
        if self.returning and key:
            statement += f" RETURNING {self.quote(key)}"
        return statement

    def update(self, table: str, columns: Sequence[str], predicate: Sequence[str]) -> str:
        assignments = ", ".join(
            f"{self.quote(name)} = {self.placeholder(index)}" for index, name in enumerate(columns)
        )
        statement = f"UPDATE {self.quote(table)} SET {assignments}"
        if predicate:
            statement += f" WHERE {self._predicate(predicate, len(columns))}"
        return statement

    def delete(self, table: str, predicate: Sequence[str]) -> str:
        statement = f"DELETE FROM {self.quote(table)}"
        if predicate:
            statement += f" WHERE {self._predicate(predicate)}"
        return statement

    def inserted_key(self, cursor: Any) -> Any:  # pragma: no cover - engine specific
        raise NotImplementedError


class TableAccess:
    """The methods one table grants, bound from the declaration rather than defined by hand."""

    def __init__(self, table: Table, operations: Iterable[Operation], database: Database) -> None:
        self._table = table
        self._database = database
        self._operations = {operation.verb: operation for operation in operations}

    def __repr__(self) -> str:
        granted = ", ".join(sorted(self._operations))
        return f"<TableAccess {self._table.name}: {granted or 'no declared operation'}>"

    def __getattr__(self, verb: str) -> Callable[..., Any]:
        operation = self._operations.get(verb)
        if operation is None:
            granted = ", ".join(sorted(self._operations)) or "none"
            raise UnknownOperation(
                f"{self._table.name} declares no {verb!r} operation. Declared: {granted}. "
                "Add an access pattern to DATABASE.md rather than reaching around this class."
            )
        return lambda **arguments: self._database.run(operation, arguments)


class Database:
    """One store, presented to callers as declared tables with declared methods.

    Callers construct one instance, share it freely, and call methods synchronously. Connection
    handling is internal and may change without affecting any caller.
    """

    def __init__(self, dsn: str, schema: Schema, *, driver: Driver | None = None) -> None:
        self._schema = schema
        self._driver = driver if driver is not None else open_driver(dsn)
        grouped = schema.by_table()
        for table in schema.tables:
            setattr(self, table.name, TableAccess(table, grouped.get(table.name, ()), self))

    @property
    def driver(self) -> Driver:
        return self._driver

    def close(self) -> None:
        self._driver.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def execute_script(self, sql: str) -> None:
        """Apply generated DDL. The schema is built once, at the DATABASE build step."""
        connection = self._driver.connect()
        cursor = connection.cursor()
        try:
            for statement in statements(self._driver.prepare_schema(sql)):
                cursor.execute(statement)
            connection.commit()
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
        key = operation.key or self._primary_key(operation.table)
        if operation.verb in ("get", "update", "delete") and key in operation.inputs and key not in arguments:
            raise PersistenceError(f"{operation.identifier} requires key {key}")
        if operation.verb == "delete" and not arguments:
            raise PersistenceError(f"{operation.identifier} requires a delete predicate")
        names = [name for name in operation.inputs if name in arguments]
        values = [arguments[name] for name in names]
        connection = self._driver.connect()
        cursor = connection.cursor()
        try:
            return self._dispatch(operation, cursor, connection, names, values)
        except Exception as exc:  # noqa: BLE001 - translated at the boundary on purpose
            connection.rollback()
            raise PersistenceError(f"{operation.identifier} failed: {exc}") from exc
        finally:
            cursor.close()

    def _dispatch(
        self,
        operation: Operation,
        cursor: Any,
        connection: Any,
        names: list[str],
        values: list[Any],
    ) -> Any:
        verb = operation.verb
        table = operation.table
        if verb in ("get", "list"):
            columns = operation.columns or self._columns(table)
            cursor.execute(self._driver.select(table, columns, names), values)
            rows = cursor.fetchall() if verb == "list" else cursor.fetchmany(1)
            built = [self._build(operation, columns, row) for row in rows]
            return built if verb == "list" else (built[0] if built else None)
        if verb == "create":
            key = operation.key or self._primary_key(table)
            cursor.execute(self._driver.insert(table, names, key), values)
            identity = self._driver.inserted_key(cursor)
            connection.commit()
            return identity
        if verb == "update":
            key = operation.key or self._primary_key(table)
            if key is None or key not in names:
                raise PersistenceError(
                    f"{operation.identifier} updates {table} without supplying {key or 'a key'}"
                )
            assigned = [name for name in names if name != key]
            ordered = [values[names.index(name)] for name in assigned] + [values[names.index(key)]]
            cursor.execute(self._driver.update(table, assigned, [key]), ordered)
            connection.commit()
            return cursor.rowcount
        if verb == "delete":
            cursor.execute(self._driver.delete(table, names), values)
            connection.commit()
            return cursor.rowcount
        raise UnknownOperation(f"{operation.identifier} names unsupported verb {verb!r}")

    def _columns(self, table: str) -> tuple[str, ...]:
        for declared in self._schema.tables:
            if declared.name == table:
                return declared.columns
        raise PersistenceError(f"{table} is not a declared table")

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
