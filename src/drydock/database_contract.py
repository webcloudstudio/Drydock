"""Typed Blueprint contracts for encapsulated relational persistence.

``DATABASE.md`` owns the public repository operations.  Feature Blueprints only name those
operations through ``## Database Interface``; tables and Alembic implementation remain private.
Migration records under ``blueprint/migrations/`` are Drydock's planned/built ledger.  They are
not executable Alembic files and therefore never claim that a deployed database was upgraded.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from drydock.database_row_types import row_class_name, row_field_type
from drydock.errors import SpecificationError

_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_H3_RE = re.compile(r"^###\s+([A-Z][A-Z0-9-]*-\d{3})\s+—\s+(.+?)\s*$", re.MULTILINE)
#: One ``| Owner | <name> |`` row, split so the cell is replaceable without touching the table.
_OWNER_CELL_RE = re.compile(
    r"(?P<head>^\|\s*Owner\s*\|)(?P<owner>[^|\n]*)(?P<tail>\|)", re.MULTILINE
)
_TABLE_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$")
#: ``[ \t]`` keeps the DTO name on its own line: a bare ``Output:`` read the next line's
#: ``| Field | Type |`` header as its name, and every such pattern shared one class (FxRates
#: ``20261024.070101``).
_INPUT_OUTPUT_RE = re.compile(r"^(Input|Output):[ \t]*(.*?)[ \t]*$", re.MULTILINE)
_INTERFACE_RE = re.compile(
    r"^\s*-\s+`(?P<id>[A-Z][A-Z0-9-]*-\d{3})`\s+—\s+"
    r"(?P<access>read-write|read|write)\s*:\s*.*?\s+-\s+"
    r"(?:supplies:\s*(?P<input>.*?)(?:\s+-\s+returns:\s*(?P<output>.*?))?"
    r"|returns:\s*(?P<only_output>.*?))\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_INTERFACE_BULLET_RE = re.compile(r"^\s*-\s+\S")
#: A Blueprint that reaches no repository still often writes the heading, because a Screen that
#: delegates persistence to a Feature is saying something true about itself. Without a declared
#: form for that, the only way to say it is prose, and prose in this section is indistinguishable
#: from a citation the author got wrong. ``- None`` makes the empty claim writable.
_INTERFACE_NONE_RE = re.compile(r"^\s*-\s+none\b", re.IGNORECASE)
#: Quoted verbatim in the parse failure. The repair loop is handed the message and nothing else,
#: so a message that names the defect without showing the accepted form cannot be repaired: five
#: passes of ``malformed ## Database Interface entry`` returned the same prose five times.
_INTERFACE_FORM = (
    "each entry is one line "
    "``- `FEATURE-DOMAIN-001` — read: <operation> - supplies: `a`, `b` - returns: `c`, `d``, "
    "and a Blueprint that reaches no repository declares ``- None — <why>.``"
)
_MIGRATION_FILE_RE = re.compile(
    r"^MIGRATION-(?:(?P<ticket>TICKET-\d+)-)?(?P<scope>[A-Z][A-Z0-9-]*(?:-\d{3})?)\.md$"
)
_OPERATION_ID_RE = re.compile(r"\b([A-Z][A-Z0-9-]*-\d{3})\b")
_COMPATIBILITY = frozenset({"unchanged", "data", "rebuild"})
#: Declared access levels. ``read-write`` exists because a repository surface is often genuinely
#: both — ``settings.get``/``set``/``delete`` is one operation set, and forcing it apart invents a
#: split the declaration never intended. A citation may claim less than the pattern grants but
#: never more, so ``_ACCESS_GRANTS`` maps each declared level to the citations it admits.
_ACCESS_GRANTS = {
    "read": frozenset({"read"}),
    "write": frozenset({"write"}),
    "read-write": frozenset({"read", "write", "read-write"}),
}
_MIGRATION_STATES = frozenset({"planned", "built", "applied"})
#: A repository operation names one table and one verb. The cell is the only place the
#: declaration says which table a pattern reaches, so its shape is load-bearing rather than
#: cosmetic: table coverage — every declared table reached by some pattern — is decided from
#: these prefixes. Free text here makes that check guess, and a check that guesses about
#: persistence is worse than no check at all.
#:
#: The verb is a closed set because the generated persistence layer builds the statement rather
#: than carrying SQL text. A builder for six shapes is small and testable; one for an open verb
#: set is a SQL generator, which is the thing this design exists to avoid. ``upsert`` exists
#: because "a stored (date, currency) is replaced" is a write by natural key, and composing it
#: from ``list`` and ``update`` moves a read-modify-write out of the layer that owns writes
#: (FxRates ``20261023.234755``).
_REPOSITORY_VERBS = ("get", "list", "create", "update", "upsert", "delete")
#: ``<table>.<name>``. The name is the method callers use and the contract they depend on; its
#: ``| Kind |`` is how it runs. A name that is a verb implies its own Kind, so a simple table
#: needs no Kind row and calls ``db.<table>.get(...)``.
_REPOSITORY_OPERATION_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
#: The comparisons a Match term may state. Each binds one Input field as a parameter, so a range
#: is two terms on one column (``date >= start_date``, ``date <= end_date``), never SQL text.
COMPARISONS = ("=", "<", "<=", ">", ">=")
#: ``<column> <op> <field>``: the Input field ``field`` compared with ``column``. A bare name is
#: the Input field compared by equality with the column of its own name.
_MATCH_TERM_RE = re.compile(r"^([a-z][a-z0-9_]*)\s*(<=|>=|=|<|>)\s*([a-z][a-z0-9_]*)$")
_ORDER_TERM_RE = re.compile(r"^([a-z][a-z0-9_]*)(?:\s+(asc|desc))?$", re.IGNORECASE)


@dataclass(frozen=True)
class Field:
    name: str
    type: str
    required: bool = False


@dataclass(frozen=True)
class AccessPattern:
    identifier: str
    owner: str
    access: str
    repository_operation: str
    compatibility: str
    input_name: str
    inputs: tuple[Field, ...]
    output_name: str
    outputs: tuple[Field, ...]
    operations: tuple[str, ...] = ()
    match: tuple[str, ...] = ()
    kind: str = ""
    #: ``(field, op, column)`` for each Match term written as a comparison; a bare term is absent.
    compare: tuple[tuple[str, str, str], ...] = ()
    #: ``(column, "asc" | "desc")`` from ``| Order |``, in sort-key order.
    order: tuple[tuple[str, str], ...] = ()

    def column_of(self, field: str) -> str:
        """The column an Input field binds: the one its comparison names, else its own name."""
        return next((column for name, _, column in self.compare if name == field), field)

    @property
    def tables(self) -> frozenset[str]:
        """Tables this pattern reaches, read from the prefix of each repository operation."""
        return frozenset(operation.split(".", 1)[0] for operation in self.operations)


@dataclass(frozen=True)
class DatabaseContract:
    patterns: tuple[AccessPattern, ...]

    def by_id(self) -> dict[str, AccessPattern]:
        return {item.identifier: item for item in self.patterns}


@dataclass(frozen=True)
class ColumnSpec:
    """One column's declared type and constraints, parsed from its ``| Field | Type |`` row."""

    name: str
    sql_type: str
    primary_key: bool = False
    not_null: bool = False
    unique: bool = False
    default: str | None = None
    references: tuple[str, str] | None = None


@dataclass(frozen=True)
class TableConstraint:
    """A composite ``UNIQUE`` or ``INDEX`` spanning more than one column."""

    kind: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class SQLiteTable:
    """One table declared by the SQLite-facing portion of ``DATABASE.md``."""

    name: str
    fields: tuple[Field, ...]
    columns: tuple[ColumnSpec, ...] = ()
    constraints: tuple[TableConstraint, ...] = ()


_SQLITE_TABLE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
#: Declared column types. ``VARCHAR(n)`` carries a length because PostgreSQL enforces one and
#: SQLite parses the identical declaration while ignoring it, so a single rendering serves both
#: engines and no engine-specific stripping is needed.
_BARE_TYPES = frozenset({"INTEGER", "NUMERIC", "REAL", "TEXT"})
_VARCHAR_RE = re.compile(r"^VARCHAR\([1-9][0-9]{0,5}\)$")
_COLUMN_MODIFIERS = frozenset({"PK", "NOT_NULL", "UNIQUE"})
#: ``REFERENCES`` and ``DEFAULT`` are the two type-cell entries carrying an argument, so they are
#: lifted out before the remainder is tokenized on whitespace.
_REFERENCES_RE = re.compile(
    r"\bREFERENCES\s+([a-z][a-z0-9_]*)\s*\(\s*([a-z][a-z0-9_]*)\s*\)", re.IGNORECASE
)
#: This DDL is rendered by Drydock and then executed against a live connection, so the literal
#: set is closed rather than free text: an open DEFAULT cell is a DDL injection path into
#: Drydock's own process, not merely a malformed declaration.
_DEFAULT_RE = re.compile(
    r"\bDEFAULT\s+(?P<literal>'[^']*'|-?\d+(?:\.\d+)?|NULL|CURRENT_TIMESTAMP|CURRENT_DATE"
    r"|CURRENT_TIME)(?=\s|$)",
    re.IGNORECASE,
)
_NOT_NULL_RE = re.compile(r"\bNOT\s+NULL\b", re.IGNORECASE)
#: The accepted form marks optional entries with square brackets, and a model reading it writes
#: ``TEXT NOT NULL [UNIQUE]`` often enough that repair passes return the same cell unchanged. The
#: brackets carry no meaning, so a bracketed modifier is unwrapped rather than refused. Only a
#: bracket enclosing a known modifier is removed, so a quoted default such as ``'[]'`` survives.
_BRACKETED_MODIFIER_RE = re.compile(
    r"\[\s*(PK|NOT\s+NULL|UNIQUE|DEFAULT\s+(?:'[^']*'|[^\s\]]+)"
    r"|REFERENCES\s+[a-z][a-z0-9_]*\s*\(\s*[a-z][a-z0-9_]*\s*\))\s*\]",
    re.IGNORECASE,
)
#: A composite constraint spans columns, so it cannot live in a per-column row. It is declared as
#: a bullet under the table's field table.
_TABLE_CONSTRAINT_RE = re.compile(
    r"^-\s+(?P<kind>UNIQUE|INDEX)\s*\((?P<columns>[^)]*)\)\s*$", re.IGNORECASE
)
#: Quoted verbatim in the parse failure, for the same reason as ``_INTERFACE_FORM``: the repair
#: loop is handed the message and nothing else.
_COLUMN_FORM = (
    "a type cell is `<TYPE> [PK] [NOT NULL] [UNIQUE] [DEFAULT <literal>] "
    "[REFERENCES <table>(<column>)]`, where <TYPE> is INTEGER, NUMERIC, REAL, TEXT, or "
    "VARCHAR(<n>), and <literal> is a single-quoted string, a number, NULL, CURRENT_TIMESTAMP, "
    "CURRENT_DATE, or CURRENT_TIME; brackets mark optional entries and are not written, "
    "as in `TEXT NOT NULL UNIQUE`"
)


def _parse_column(field: Field, *, table: str, source: str) -> ColumnSpec:
    """Read one ``| Field | Type |`` cell into a validated column declaration.

    ``REFERENCES`` and ``DEFAULT`` carry arguments containing spaces, so both are lifted out of
    the cell before the remainder is tokenized. What is left must be the type and a closed set of
    bare modifiers; anything else is refused by name rather than ignored, because a modifier that
    parses as nothing is a constraint the author believes exists and the database does not have.
    """
    cell = _BRACKETED_MODIFIER_RE.sub(r"\1", field.type.strip())
    references: tuple[str, str] | None = None
    reference = _REFERENCES_RE.search(cell)
    if reference is not None:
        references = (reference.group(1), reference.group(2))
        cell = f"{cell[: reference.start()]} {cell[reference.end() :]}".strip()
    default: str | None = None
    literal = _DEFAULT_RE.search(cell)
    if literal is not None:
        default = literal.group("literal")
        cell = f"{cell[: literal.start()]} {cell[literal.end() :]}".strip()
    if re.search(r"\bDEFAULT\b", cell, re.IGNORECASE):
        raise SpecificationError(
            f"{source}: {table}.{field.name} has an unreadable DEFAULT value — {_COLUMN_FORM}"
        )
    tokens = _NOT_NULL_RE.sub("NOT_NULL", cell).split()
    if not tokens:
        raise SpecificationError(f"{source}: {table}.{field.name} names no type — {_COLUMN_FORM}")
    sql_type = tokens[0].upper()
    if sql_type not in _BARE_TYPES and not _VARCHAR_RE.fullmatch(sql_type):
        raise SpecificationError(
            f"{source}: {table}.{field.name} has unsupported type {field.type!r} — {_COLUMN_FORM}"
        )
    modifiers = [token.upper() for token in tokens[1:]]
    unknown = [token for token in modifiers if token not in _COLUMN_MODIFIERS]
    if unknown:
        raise SpecificationError(
            f"{source}: {table}.{field.name} has unknown column modifier(s) "
            f"{', '.join(repr(token.replace('NOT_NULL', 'NOT NULL')) for token in unknown)} — "
            f"{_COLUMN_FORM}"
        )
    if len(set(modifiers)) != len(modifiers):
        raise SpecificationError(
            f"{source}: {table}.{field.name} repeats a column modifier — {_COLUMN_FORM}"
        )
    return ColumnSpec(
        name=field.name,
        sql_type=sql_type,
        primary_key="PK" in modifiers,
        not_null="NOT_NULL" in modifiers,
        unique="UNIQUE" in modifiers,
        default=default,
        references=references,
    )


def _table_constraints(
    body: str, *, table: str, source: str, columns: tuple[ColumnSpec, ...]
) -> tuple[TableConstraint, ...]:
    """Read the composite ``UNIQUE``/``INDEX`` bullets declared under one table's field table."""
    declared = {column.name for column in columns}
    constraints: list[TableConstraint] = []
    for line in body.splitlines():
        match = _TABLE_CONSTRAINT_RE.match(line.strip())
        if match is None:
            continue
        names = tuple(
            item
            for item in (part.strip().strip("`") for part in match["columns"].split(","))
            if item
        )
        if len(names) < 2:
            raise SpecificationError(
                f"{source}: {table} declares a composite {match['kind'].upper()} over "
                f"{len(names)} column(s). A composite constraint spans two or more; a single "
                "column states UNIQUE in its own type cell."
            )
        missing = [item for item in names if item not in declared]
        if missing:
            raise SpecificationError(
                f"{source}: {table} constrains undeclared column(s) "
                f"{', '.join(repr(item) for item in missing)}"
            )
        if len(set(names)) != len(names):
            raise SpecificationError(f"{source}: {table} repeats a column in one constraint")
        constraints.append(TableConstraint(kind=match["kind"].upper(), columns=names))
    return tuple(constraints)


def _key_count_defect(name: str, keys: Sequence[str], *, source: str) -> str:
    return (
        f"{source}: {name} declares {len(keys)} PK columns ({', '.join(keys) or 'none'}). "
        "Every table declares exactly one PK column, such as `id | INTEGER PK`, so each "
        "row is read, updated, and deleted by that key; a natural key spanning several "
        "columns is a `- UNIQUE (a, b)` bullet beside it."
    )


def sqlite_schema_tables(
    text: str, *, source: str = "DATABASE.md", require_key: bool = True
) -> tuple[SQLiteTable, ...]:
    """Read Markdown ``## `table_name``` declarations into a safe SQLite schema.

    ``DATABASE.md`` is a persistence declaration, not a Python test fixture.  This narrow,
    deterministic reader recognizes its table-heading/field-table form and leaves operation-only
    database contracts alone.  The result is used to prove the declaration can create and open a
    SQLite store before any model is asked to implement an application adapter.

    ``require_key=False`` reads a table whose PK count is wrong instead of refusing it, so
    :func:`database_contract_defects` can report that fault beside the pattern faults.
    """
    sections = list(_SECTION_RE.finditer(text))
    tables: list[SQLiteTable] = []
    for index, match in enumerate(sections):
        name = match.group(1).strip().strip("`")
        if not _SQLITE_TABLE_NAME_RE.fullmatch(name):
            continue
        fields = _field_table(text, match.end())
        if not fields:
            continue
        seen: set[str] = set()
        columns: list[ColumnSpec] = []
        for field in fields:
            if not _SQLITE_TABLE_NAME_RE.fullmatch(field.name):
                raise SpecificationError(f"{source}: {name} has invalid field name {field.name!r}")
            if field.name in seen:
                raise SpecificationError(f"{source}: {name} declares {field.name!r} more than once")
            seen.add(field.name)
            columns.append(_parse_column(field, table=name, source=source))
        keys = [column.name for column in columns if column.primary_key]
        if len(keys) != 1 and require_key:
            raise SpecificationError(_key_count_defect(name, keys, source=source))
        stop = sections[index + 1].start() if index + 1 < len(sections) else len(text)
        tables.append(
            SQLiteTable(
                name,
                fields,
                tuple(columns),
                _table_constraints(
                    text[match.end() : stop], table=name, source=source, columns=tuple(columns)
                ),
            )
        )
    names = [table.name for table in tables]
    if len(names) != len(set(names)):
        raise SpecificationError(f"{source}: duplicate SQLite table declaration")
    _validate_references(tuple(tables), source=source)
    return tuple(tables)


def _validate_references(tables: tuple[SQLiteTable, ...], *, source: str) -> None:
    """Refuse a foreign key whose target the declaration never states.

    A key pointing at a table or column that does not exist is accepted silently by SQLite and
    refused by PostgreSQL, so the declaration would build in test and fail in production.
    """
    declared = {table.name: {column.name for column in table.columns} for table in tables}
    for table in tables:
        for column in table.columns:
            if column.references is None:
                continue
            target, target_column = column.references
            if target not in declared:
                raise SpecificationError(
                    f"{source}: {table.name}.{column.name} references table {target!r}, which "
                    "this declaration does not declare"
                )
            if target_column not in declared[target]:
                raise SpecificationError(
                    f"{source}: {table.name}.{column.name} references {target}.{target_column}, "
                    f"which {target} does not declare"
                )


def _creation_order(tables: tuple[SQLiteTable, ...], *, source: str) -> tuple[SQLiteTable, ...]:
    """Order tables so every foreign-key target is created before the table citing it.

    SQLite tolerates any order; PostgreSQL does not. Rendering one ordering for both engines
    keeps the generated schema portable rather than accidentally SQLite-shaped.
    """
    by_name = {table.name: table for table in tables}
    ordered: list[SQLiteTable] = []
    placed: set[str] = set()
    visiting: set[str] = set()

    def visit(table: SQLiteTable) -> None:
        if table.name in placed:
            return
        if table.name in visiting:
            raise SpecificationError(
                f"{source}: foreign keys form a cycle through {table.name!r}. Break it by "
                "dropping one REFERENCES and enforcing that edge in the repository."
            )
        visiting.add(table.name)
        for column in table.columns:
            if column.references is not None and column.references[0] != table.name:
                target = by_name.get(column.references[0])
                if target is not None:
                    visit(target)
        visiting.discard(table.name)
        placed.add(table.name)
        ordered.append(table)

    for table in tables:
        visit(table)
    return tuple(ordered)


def _column_sql(column: ColumnSpec) -> str:
    """Render one column definition, identical for SQLite and PostgreSQL."""
    parts = [f'"{column.name}"', column.sql_type]
    if column.primary_key:
        parts.append("PRIMARY KEY")
    if column.not_null:
        parts.append("NOT NULL")
    if column.unique:
        parts.append("UNIQUE")
    if column.default is not None:
        parts.append(f"DEFAULT {column.default}")
    if column.references is not None:
        parts.append(f'REFERENCES "{column.references[0]}"("{column.references[1]}")')
    return " ".join(parts)


def sqlite_schema_sql(tables: Iterable[SQLiteTable]) -> str:
    """Render idempotent SQLite DDL from :func:`sqlite_schema_tables` output."""
    ordered = _creation_order(tuple(tables), source="DATABASE.md")
    statements: list[str] = []
    indexes: list[str] = []
    for table in ordered:
        definitions = [_column_sql(column) for column in table.columns]
        for constraint in table.constraints:
            names = ", ".join(f'"{item}"' for item in constraint.columns)
            if constraint.kind == "UNIQUE":
                definitions.append(f"UNIQUE ({names})")
            else:
                index = f"{table.name}_{'_'.join(constraint.columns)}_idx"
                indexes.append(f'CREATE INDEX IF NOT EXISTS "{index}" ON "{table.name}" ({names});')
        statements.append(f'CREATE TABLE IF NOT EXISTS "{table.name}" ({", ".join(definitions)});')
    return "\n".join(statements + indexes)


def derived_indexes(
    tables: tuple[SQLiteTable, ...], contract: DatabaseContract
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Indexes the declaration implies, as ``(table, columns)`` pairs in a stable order.

    An index is derived rather than decided wherever the declaration already states the answer:
    a foreign key is looked up by its child column, and a ``read`` pattern's ``Input:`` fields are
    the predicate it filters on. Deriving them keeps the schema reproducible — an index invented
    at build time and recorded only in a decision log is dropped by the next render, and nothing
    detects the loss. Anything genuinely optional is declared as an ``- INDEX (...)`` bullet
    instead.

    ``read-write`` is excluded on purpose: its inputs are part predicate and part payload, and the
    declaration does not say which, so deriving from it would index columns nothing searches.
    """
    by_name = {table.name: table for table in tables}
    covered: set[tuple[str, tuple[str, ...]]] = set()
    for table in tables:
        for column in table.columns:
            if column.primary_key or column.unique:
                covered.add((table.name, (column.name,)))
        for constraint in table.constraints:
            covered.add((table.name, constraint.columns))
    derived: list[tuple[str, tuple[str, ...]]] = []

    def offer(table: str, columns: tuple[str, ...]) -> None:
        key = (table, columns)
        if not columns or key in covered:
            return
        covered.add(key)
        derived.append(key)

    for table in tables:
        for column in table.columns:
            if column.references is not None:
                offer(table.name, (column.name,))
    for pattern in contract.patterns:
        if pattern.access != "read":
            continue
        for operation in pattern.operations:
            table = by_name.get(operation.split(".", 1)[0])
            if table is None:
                continue
            declared = {column.name for column in table.columns}
            offer(
                table.name,
                tuple(
                    column
                    for column in dict.fromkeys(pattern.column_of(f.name) for f in pattern.inputs)
                    if column in declared
                ),
            )
    return tuple(derived)


def schema_sql(text: str, *, source: str = "DATABASE.md") -> str:
    """Render the complete declared schema: tables, declared constraints, and derived indexes."""
    tables = sqlite_schema_tables(text, source=source)
    if not tables:
        return ""
    statements = [sqlite_schema_sql(tables)]
    try:
        contract = parse_database_contract(text)
    except SpecificationError:
        contract = DatabaseContract(patterns=())
    extra: list[str] = []
    for table, columns in derived_indexes(tables, contract):
        index = table + "_" + "_".join(columns) + "_idx"
        names = ", ".join('"' + item + '"' for item in columns)
        extra.append(
            'CREATE INDEX IF NOT EXISTS "' + index + '" ON "' + table + '" (' + names + ");"
        )
    return "\n".join(statements + extra) if extra else statements[0]


def validate_sqlite_schema(text: str, *, source: str = "DATABASE.md") -> tuple[SQLiteTable, ...]:
    """Prove a declared SQLite schema creates, connects, and exposes every declared column.

    An empty tuple means the document uses a non-SQLite or operation-only contract, for which
    this invariant is inapplicable.  Any returned declaration was exercised against a fresh,
    in-memory SQLite database using DDL rendered exclusively by Drydock.
    """
    tables = sqlite_schema_tables(text, source=source)
    if not tables:
        return ()
    import sqlite3

    with sqlite3.connect(":memory:") as connection:
        connection.executescript(sqlite_schema_sql(tables))
        connection.execute("SELECT 1").fetchone()
        existing = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        for table in tables:
            if table.name not in existing:
                raise SpecificationError(
                    f"{source}: generated SQLite table {table.name!r} is absent"
                )
            columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table.name}")')}
            missing = {field.name for field in table.fields} - columns
            if missing:
                raise SpecificationError(
                    f"{source}: generated SQLite table {table.name!r} misses column(s) "
                    f"{', '.join(sorted(missing))}"
                )
    return tables


@dataclass(frozen=True)
class DatabaseUse:
    identifier: str
    access: str
    supplies: tuple[str, ...]
    returns: tuple[str, ...]


@dataclass(frozen=True)
class MigrationRecord:
    path: Path
    access_pattern: str
    revision: str
    compatibility: str
    state: str
    ticket_id: str = ""


def database_operation_fingerprints(text: str) -> str:
    """Serialize the public persistence contract for the applied-spec registry.

    The serialized value is deliberately token-safe because it lives inside the
    Manifest's compact ``applied_specs`` registry. Each fingerprint hashes only what a
    caller depends on (``_contract_payload``), so a schema, migration, length, or
    nullability edit cannot invalidate a Feature merely by changing DATABASE.md.
    """
    contract = parse_database_contract(text)
    try:
        tables = {table.name: table for table in sqlite_schema_tables(text)}
    except SpecificationError:
        tables = {}
    entries: list[str] = []
    for pattern in contract.patterns:
        payload = _contract_payload(pattern, tables.get(pattern.operations[0].partition(".")[0]))
        entries.append(f"{pattern.identifier}:{sha256(payload.encode()).hexdigest()}")
    return ";".join(entries)


def _legacy_operation_fingerprints(text: str) -> str:
    """The fingerprint Manifests recorded before it hashed caller types only.

    Kept so an unchanged ``DATABASE.md`` under an older Manifest still reads as unchanged.
    """
    contract = parse_database_contract(text)
    entries: list[str] = []
    for pattern in contract.patterns:
        payload = "\x1f".join((
            pattern.identifier,
            pattern.owner,
            pattern.access,
            pattern.repository_operation,
            pattern.compatibility,
            pattern.input_name,
            *(f"{field.name}:{field.type}:{int(field.required)}" for field in pattern.inputs),
            pattern.output_name,
            *(f"{field.name}:{field.type}" for field in pattern.outputs),
            *((f"match:{','.join(pattern.match)}",) if pattern.match else ()),
        ))
        entries.append(f"{pattern.identifier}:{sha256(payload.encode()).hexdigest()}")
    return ";".join(entries)


def changed_operation_contracts(prior: Mapping[str, str], text: str) -> set[str]:
    """Access-pattern ids whose caller contract differs from the recorded fingerprints.

    A recorded value equal to either the current or the legacy fingerprint is unchanged, so a
    Manifest written before the caller-type fingerprint does not mark every operation changed.
    """
    current = parse_database_operation_fingerprints(database_operation_fingerprints(text))
    legacy = parse_database_operation_fingerprints(_legacy_operation_fingerprints(text))
    return {
        identifier
        for identifier in set(prior) | set(current)
        if prior.get(identifier) not in {current.get(identifier), legacy.get(identifier)}
    }


def parse_database_operation_fingerprints(value: str) -> dict[str, str]:
    """Read the compact public-contract snapshot recorded in ``applied_specs``."""
    result: dict[str, str] = {}
    for item in value.split(";"):
        identifier, separator, fingerprint = item.partition(":")
        if (
            not separator
            or not _OPERATION_ID_RE.fullmatch(identifier)
            or not re.fullmatch(r"[0-9a-f]{64}", fingerprint)
        ):
            continue
        result[identifier] = fingerprint
    return result


def _section(text: str, heading: str) -> str:
    match = next((m for m in _SECTION_RE.finditer(text) if m.group(1).strip() == heading), None)
    if match is None:
        return ""
    next_match = _SECTION_RE.search(text, match.end())
    return text[match.end() : next_match.start() if next_match else len(text)]


def _rows(text: str) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for line in text.splitlines():
        match = _TABLE_ROW_RE.match(line.strip())
        if not match:
            continue
        left, right = (part.strip() for part in match.groups())
        if left.casefold() == "field" or set(left) <= {"-", ":"}:
            continue
        result.append((left, right))
    return result


def _no_field(name: str) -> bool:
    """True for a row that says a DTO carries nothing — ``(none)``, ``—`` — rather than a field.

    LLM-authored declarations write a placeholder row under an empty ``Input:``. Read as a field,
    it became an input named ``(none)`` in the generated repository and an undeclared column to
    the Go emitter.
    """
    stripped = name.strip()
    return (
        stripped in {"", "—", "-"}
        or stripped.casefold() == "none"
        or (stripped.startswith("(") and stripped.endswith(")"))
    )


def _field_table(text: str, start: int) -> tuple[Field, ...]:
    fields: list[Field] = []
    seen_table = False
    for line in text[start:].splitlines():
        stripped = line.strip()
        if not stripped:
            if seen_table:
                break
            continue
        if not stripped.startswith("|"):
            if seen_table:
                break
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if cells[0].casefold() == "field" or set(cells[0]) <= {"-", ":"}:
            seen_table = True
            continue
        if len(cells) < 2:
            continue
        seen_table = True
        if _no_field(cells[0].strip("`")):
            continue
        fields.append(
            Field(
                name=cells[0].strip("`"),
                type=cells[1].strip("`"),
                required=len(cells) > 2 and cells[2].casefold() in {"yes", "true", "required"},
            )
        )
    return tuple(fields)


def _repository_operations(value: str, *, identifier: str, source: str) -> tuple[str, ...]:
    """Read a Repository operation cell into the one validated ``<table>.<verb>`` it names.

    One pattern declares one operation. The cell once accepted a comma-separated list, but a
    pattern carries exactly one ``Input:`` and one ``Output:`` table, so a cell naming
    ``settings.get, settings.set`` describes two operations with one pair of DTOs and leaves
    which fields belong to which undeclared. Splitting them is the only reading that stays
    honest, and it is what lets the generated persistence layer build a statement per operation.
    """
    operations = tuple(
        item for item in (part.strip().strip("`").strip() for part in value.split(",")) if item
    )
    if not operations:
        raise SpecificationError(f"{source}: {identifier} names no repository operation")
    if len(operations) > 1:
        raise SpecificationError(
            f"{source}: {identifier} names {len(operations)} repository operations "
            f"({', '.join(repr(item) for item in operations)}). One access pattern declares one "
            "operation, because it carries one Input and one Output. Give each operation its own "
            "`### <FEATURE-DOMAIN-NNN>` section with its own DTO tables."
        )
    invalid = [item for item in operations if not _REPOSITORY_OPERATION_RE.fullmatch(item)]
    if invalid:
        raise SpecificationError(
            f"{source}: {identifier} has invalid repository operation "
            f"{invalid[0]!r}: it names one declared table and one operation as "
            "`<table>.<name>`, lowercase snake_case, such as `rates.get` or `rates.replace_rate`"
        )
    return operations


def _operation_kind(operation: str, declared: str, *, identifier: str, source: str) -> str:
    """The Kind an operation runs as: its ``| Kind |`` cell, or its name when that is a verb."""
    name = operation.partition(".")[2]
    kind = declared.strip().strip("`").strip().casefold()
    verbs = ", ".join(_REPOSITORY_VERBS)
    if kind and kind not in _REPOSITORY_VERBS:
        raise SpecificationError(
            f"{source}: {identifier} has invalid Kind {kind!r}; the Kind is one of {verbs}"
        )
    if name in _REPOSITORY_VERBS:
        if kind and kind != name:
            raise SpecificationError(
                f"{source}: {identifier} names operation `{operation}` with Kind `{kind}`. A "
                f"verb name is its own Kind; name the operation for what it does, such as "
                f"`{operation.partition('.')[0]}.<name>`, or drop the Kind row."
            )
        return name
    if not kind:
        raise SpecificationError(
            f"{source}: {identifier} names operation `{operation}`, which is not a verb, so it "
            f"declares `| Kind | <kind> |`, one of {verbs}"
        )
    return kind


def table_coverage_defects(
    text: str, *, source: str = "DATABASE.md"
) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    """Return the two ways the schema and the operation surface can disagree.

    ``(uncited, undeclared)``. A declared table no pattern reaches cannot be read or written by
    any story: it is storage the product describes and nothing can use, and it means the schema
    and the stories disagree about what is kept. An operation naming a table the schema never
    declares is the same disagreement from the other side, and it builds a repository against a
    table that will not exist.

    Both are decided from the declaration alone, with no model judgment, which is why persistence
    is gated here rather than left to review.
    """
    tables = sqlite_schema_tables(text, source=source)
    if not tables:
        return (), ()
    contract = parse_database_contract(text, source=source)
    declared = {table.name for table in tables}
    covered: set[str] = set()
    undeclared: list[tuple[str, str]] = []
    for pattern in contract.patterns:
        covered |= pattern.tables
        undeclared.extend(
            (pattern.identifier, operation)
            for operation in pattern.operations
            if operation.split(".", 1)[0] not in declared
        )
    uncited = tuple(table.name for table in tables if table.name not in covered)
    return uncited, tuple(undeclared)


def _pattern_blocks(text: str, source: str) -> list[tuple[re.Match[str], str]]:
    """Split ``## Access Patterns`` into one ``(heading, body)`` pair per named operation."""
    access_patterns = _section(text, "Access Patterns")
    if not access_patterns.strip():
        raise SpecificationError(f"{source}: missing required ## Access Patterns section")
    invalid = [
        heading.group(0).strip()
        for heading in re.finditer(r"^###[ \t]+[^\n]+", access_patterns, re.MULTILINE)
        if not _H3_RE.fullmatch(heading.group(0))
    ]
    if invalid:
        raise SpecificationError(
            f"{source}: invalid access-pattern heading(s): "
            + "; ".join(f"`{heading}`" for heading in invalid)
            + ". Each heading is `### FEATURE-DOMAIN-001 — Operation`: the identifier uses "
            "uppercase letters, digits, and hyphens and ends in a three-digit number; "
            "the separator is a literal em dash. Correct every invalid heading before retrying."
        )
    matches = list(_H3_RE.finditer(access_patterns))
    if not matches:
        raise SpecificationError(
            f"{source}: ## Access Patterns has no named operation: each operation is its own "
            "`### <FEATURE-DOMAIN-NNN> — <Operation>` section over a `| Field | Value |` table, "
            "never a row in one table of operations"
        )
    return [
        (
            match,
            access_patterns[
                match.end() : matches[index + 1].start()
                if index + 1 < len(matches)
                else len(access_patterns)
            ],
        )
        for index, match in enumerate(matches)
    ]


def _parse_access_pattern(match: re.Match[str], block: str, source: str) -> AccessPattern:
    metadata = {key.casefold(): value for key, value in _rows(block)}
    missing = [
        label
        for label in ("owner", "access", "repository operation", "compatibility")
        if not metadata.get(label)
    ]
    if missing:
        raise SpecificationError(
            f"{source}: {match.group(1)} missing access-pattern field(s): {', '.join(missing)}"
        )
    access = metadata["access"].casefold()
    compatibility = metadata["compatibility"].casefold()
    if access not in _ACCESS_GRANTS:
        raise SpecificationError(f"{source}: {match.group(1)} has invalid Access: {access}")
    if compatibility not in _COMPATIBILITY:
        raise SpecificationError(
            f"{source}: {match.group(1)} has invalid Compatibility: {compatibility}"
        )
    values: dict[str, tuple[str, tuple[Field, ...]]] = {}
    for io_match in _INPUT_OUTPUT_RE.finditer(block):
        values[io_match.group(1).casefold()] = (
            io_match.group(2).strip("` "),
            _field_table(block, io_match.end()),
        )
    if "input" not in values or "output" not in values:
        # The repair prompt carries this message and nothing else, so it states the grammar.
        raise SpecificationError(
            f"{source}: {match.group(1)} requires Input and Output tables — after the "
            "`| Field | Value |` table, write `Input: <DtoName>` and `Output: <DtoName>`, each "
            "followed by a `| Field | Type |` table of the fields it carries"
        )
    unnamed = [label.title() for label, (name, _) in values.items() if not name]
    if unnamed:
        raise SpecificationError(
            f"{source}: {match.group(1)} names no DTO after "
            f"{' and '.join(f'`{label}:`' for label in sorted(unnamed))} — write "
            "`Input: <DtoName>` and `Output: <DtoName>` on one line, each followed by a "
            "`| Field | Type |` table of the fields it carries"
        )
    # FxRates 20261024.162029 wrote `Input: `date: str`, `currency: str``: one DTO name with no
    # field table, so the pattern declared no fields and every Match field was "not an Input
    # field" — a defect the model could not see in its own line, repeated for three passes.
    inline = [label.title() for label, (name, _) in values.items() if ":" in name]
    if inline:
        raise SpecificationError(
            f"{source}: {match.group(1)} lists fields on the "
            f"{' and '.join(f'`{label}:`' for label in sorted(inline))} line, which takes one "
            "DTO name, so it declares no fields — write `Input: <DtoName>` and "
            "`Output: <DtoName>`, each followed by a `| Field | Type |` table with one row per "
            "field"
        )
    declared_match: list[str] = []
    compare: list[tuple[str, str, str]] = []
    for item in (part.replace("`", "").strip() for part in metadata.get("match", "").split(",")):
        if not item or _no_field(item):
            continue
        if re.fullmatch(r"[a-z][a-z0-9_]*", item):
            declared_match.append(item)
            continue
        term = _MATCH_TERM_RE.match(item)
        if term is None:
            raise SpecificationError(
                f"{source}: {match.group(1)} Match term `{item}` is neither an Input field nor "
                f"`<column> <op> <field>` with op one of {', '.join(COMPARISONS)}, such as "
                "`date >= start_date`."
            )
        declared_match.append(term.group(3))
        compare.append((term.group(3), term.group(2), term.group(1)))
    order: list[tuple[str, str]] = []
    for item in (part.replace("`", "").strip() for part in metadata.get("order", "").split(",")):
        if not item or _no_field(item):
            continue
        term = _ORDER_TERM_RE.match(item)
        if term is None:
            raise SpecificationError(
                f"{source}: {match.group(1)} Order term `{item}` is not `<column>`, "
                "`<column> asc`, or `<column> desc`."
            )
        order.append((term.group(1), (term.group(2) or "asc").casefold()))
    operations = _repository_operations(
        metadata["repository operation"], identifier=match.group(1), source=source
    )
    return AccessPattern(
        identifier=match.group(1),
        match=tuple(declared_match),
        compare=tuple(compare),
        order=tuple(order),
        kind=_operation_kind(
            operations[0], metadata.get("kind", ""), identifier=match.group(1), source=source
        ),
        owner=metadata["owner"].strip(),
        access=access,
        repository_operation=metadata["repository operation"].strip("`"),
        operations=operations,
        compatibility=compatibility,
        input_name=values["input"][0],
        inputs=values["input"][1],
        output_name=values["output"][0],
        outputs=values["output"][1],
    )


#: The declaration itself, named as the ``| Owner |`` of a shared access pattern: one no single
#: Feature owns, reached by several. An audit or activity log is the shape that needs it — six
#: Features append to it and two Screens read it, so naming any one of them the owner is a lie,
#: and inventing a Blueprint for it is worse. A shared pattern may be cited by any Blueprint and
#: is required of none.
SHARED_OWNER = "DATABASE.md"


def legal_owner(owner: str, blueprints: Collection[str]) -> bool:
    """True when ``owner`` may appear in an ``| Owner |`` cell.

    Only a Feature owns data. A Screen renders it and a Release verifies it; both reach it
    through a Feature's service, so neither may hold a repository. ``DATABASE.md`` is the one
    other legal value, and it means shared.
    """
    return owner == SHARED_OWNER or (owner.startswith("FEATURE") and owner in blueprints)


def rewrite_illegal_owners(
    text: str, blueprints: Collection[str], *, source: str = "DATABASE.md"
) -> tuple[str, tuple[str, ...]]:
    """Point every illegal ``| Owner |`` cell at ``DATABASE.md``; return the text and what changed.

    A name that owns nothing in this plan — a service, a module, a Screen, or a Blueprint the
    model invented for the purpose — states no fact that can be checked. The one thing known
    about the pattern is that no Feature here claims it, which is what ``DATABASE.md`` as owner
    says. Deterministic, because there is nothing to decide: the alternative was an LLM repair
    pass that invented `FEATURE-ACTIVITY-EVENTS.md`, a file no Blueprint answered to.
    """
    changes: list[str] = []

    def replace(match: re.Match[str]) -> str:
        owner = match.group("owner").strip()
        if legal_owner(owner, blueprints):
            return match.group(0)
        changes.append(owner)
        return match.group("head") + f" {SHARED_OWNER} " + match.group("tail")

    patterns = _section(text, "Access Patterns")
    if not patterns.strip():
        return text, ()
    rewritten = _OWNER_CELL_RE.sub(replace, patterns)
    if not changes:
        return text, ()
    return text.replace(patterns, rewritten, 1), tuple(sorted(set(changes)))


def _dto_name(table: str) -> str:
    return "".join(part.capitalize() for part in table.split("_") if part)


def _derived_dtos(
    table: SQLiteTable, verb: str
) -> dict[str, tuple[str, tuple[tuple[str, str, bool], ...]]]:
    """The Input and Output a ``<table>.<verb>`` operation carries, read from the table alone.

    Keyed operations (``get``, ``update``, ``delete``) take the primary key every table declares.
    ``create`` takes the non-key columns, required where the schema says ``NOT NULL`` with no
    default. Every verb but ``delete`` returns the row.
    """
    columns = table.columns
    keys = tuple(column for column in columns if column.primary_key)
    row = tuple((column.name, column.sql_type, False) for column in columns)
    key = tuple((column.name, column.sql_type, True) for column in keys)
    base = _dto_name(table.name)
    if verb == "list":
        inputs: tuple[str, tuple[tuple[str, str, bool], ...]] = (f"{base}Query", ())
    elif verb == "create":
        inputs = (
            f"{base}Create",
            tuple(
                (column.name, column.sql_type, column.not_null and column.default is None)
                for column in columns
                if not column.primary_key
            ),
        )
    elif verb == "upsert":
        inputs = (
            f"{base}Upsert",
            tuple(
                (column.name, column.sql_type, column.not_null and column.default is None)
                for column in columns
                if not column.primary_key
            ),
        )
    elif verb == "update":
        inputs = (
            f"{base}Update",
            key
            + tuple(
                (column.name, column.sql_type, False) for column in columns if column not in keys
            ),
        )
    else:
        inputs = (f"{base}Key", key)
    output = (f"{base}Key", key) if verb == "delete" else (f"{base}Row", row)
    return {"Input": inputs, "Output": output}


def _render_dto(label: str, name: str, fields: tuple[tuple[str, str, bool], ...]) -> str:
    rows = "".join(
        f"| {field} | {kind} | {'yes' if required else 'no'} |\n"
        for field, kind, required in fields
    )
    return f"{label}: `{name}`\n| Field | Type | Required |\n|-------|------|----------|\n{rows}"


def derive_missing_dtos(text: str, *, source: str = "DATABASE.md") -> tuple[str, tuple[str, ...]]:
    """Write the Input/Output tables a pattern omits when its schema table determines them.

    A pattern whose Repository operation names one declared table and one closed verb fixes its
    DTOs: the fields are that table's columns. Nothing is left for a model to decide, and the
    repair loop proved it cannot be relied on to do it — a Marina_Luna repair pass asked to reach
    fifteen uncited tables added fifteen patterns with no DTO tables, and the run ended on its
    last pass. A pattern whose operation is invalid or names an undeclared table is left alone for
    the gate to report. Returns the text and the identifiers that were completed.
    """
    try:
        tables = {table.name: table for table in sqlite_schema_tables(text, source=source)}
    except SpecificationError:
        return text, ()
    section = _section(text, "Access Patterns")
    matches = list(_H3_RE.finditer(section))
    if not tables or not matches:
        return text, ()
    completed: list[str] = []
    pieces = [section[: matches[0].start()]]
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        block = section[match.start() : end]
        present = {found.group(1) for found in _INPUT_OUTPUT_RE.finditer(block)}
        metadata = {key.casefold(): value for key, value in _rows(block)}
        operation = metadata.get("repository operation", "").strip().strip("`").strip()
        table_name = operation.partition(".")[0]
        try:
            verb = _operation_kind(
                operation, metadata.get("kind", ""), identifier=match.group(1), source=source
            )
        except SpecificationError:
            verb = ""
        if (
            {"Input", "Output"} <= present
            or not verb
            or not _REPOSITORY_OPERATION_RE.fullmatch(operation)
            or table_name not in tables
        ):
            pieces.append(block)
            continue
        dtos = _derived_dtos(tables[table_name], verb)
        additions = "\n".join(
            _render_dto(label, *dtos[label])
            for label in ("Input", "Output")
            if label not in present
        )
        trailing = block[len(block.rstrip()) :] or "\n"
        pieces.append(block.rstrip() + "\n\n" + additions.rstrip("\n") + trailing)
        completed.append(match.group(1))
    if not completed:
        return text, ()
    return text.replace(section, "".join(pieces), 1), tuple(completed)


def declared_owners(text: str, *, source: str = "DATABASE.md") -> tuple[str, ...]:
    """Return every ``| Owner |`` value in ``## Access Patterns``, whether or not it parses.

    Ownership is checked against the emitted Blueprints independently of the rest of the
    pattern, so an unreadable pattern does not also hide the fact that it names no Blueprint.
    """
    try:
        blocks = _pattern_blocks(text, source)
    except SpecificationError:
        return ()
    owners: list[str] = []
    for _, block in blocks:
        metadata = {key.casefold(): value for key, value in _rows(block)}
        if owner := metadata.get("owner", "").strip():
            owners.append(owner)
    return tuple(owners)


def parse_database_contract(text: str, *, source: str = "DATABASE.md") -> DatabaseContract:
    """Parse the public operation surface from a DATABASE Blueprint."""
    patterns = [
        _parse_access_pattern(match, block, source)
        for match, block in _pattern_blocks(text, source)
    ]
    ids = [pattern.identifier for pattern in patterns]
    if len(ids) != len(set(ids)):
        raise SpecificationError(f"{source}: duplicate access-pattern identifier")
    return DatabaseContract(tuple(patterns))


def output_row_defects(
    patterns: Iterable[AccessPattern], *, source: str = "DATABASE.md"
) -> tuple[str, ...]:
    """Judge shared Output names exactly as the Python emitter materializes them.

    FxRates 20261025.014047 reused Rate for a full row and a delete key projection. The
    emitter refused it, but admission froze the declaration first. Normalize both names and
    annotations here so aliases cannot hide conflicts or reject equivalent field types.
    """
    declared: dict[str, tuple[tuple[tuple[str, str], ...], AccessPattern]] = {}
    defects: list[str] = []
    for pattern in patterns:
        if not pattern.outputs:
            continue
        name = row_class_name(pattern.output_name or f"{pattern.identifier}Row")
        shape = tuple((field.name, row_field_type(field.type)) for field in pattern.outputs)
        previous_shape, previous = declared.setdefault(name, (shape, pattern))
        if previous_shape == shape:
            continue
        suggested = _dto_name(pattern.operations[0].replace(".", "_")) + "Output"
        fields = ", ".join(f"{field}: {kind}" for field, kind in shape)
        prior_fields = ", ".join(f"{field}: {kind}" for field, kind in previous_shape)
        defects.append(
            f"{source}: Conflicting Python row class {name}: {pattern.identifier} "
            f"(`{pattern.operations[0]}`) declares Output `{pattern.output_name}` "
            f"({fields}), but {previous.identifier} (`{previous.operations[0]}`) "
            f"declares ({prior_fields}). One Output type name has one ordered field/type "
            f"definition. Give this distinct projection an operation-derived name such as "
            f"`{suggested}`; preserve its fields and all callers' contracts."
        )
    return tuple(defects)


def database_contract_defects(text: str, *, source: str = "DATABASE.md") -> tuple[str, ...]:
    """Return all parse and generation-contract defects in ``text``, or ``()``.

    The parser stops at the first bad pattern. A repair pass handed only that one fixes it and
    returns to find the next, so thirteen incomplete patterns cost thirteen passes against a
    budget sized for far fewer. Each pattern is judged on its own here, and every check runs on
    every pattern it can judge: a table's wrong PK count, a pattern that does not parse, and a
    field that does not bind each exclude only what they make unjudgeable. Reported one tier per
    pass, FxRates ``20261024.143213`` spent its three attempts on three faults batch 1 already
    held.
    """
    try:
        blocks = _pattern_blocks(text, source)
    except SpecificationError as exc:
        return (str(exc),)
    defects: list[str] = []
    ids: list[str] = []
    patterns: list[AccessPattern] = []
    for match, block in blocks:
        ids.append(match.group(1))
        try:
            patterns.append(_parse_access_pattern(match, block, source))
        except SpecificationError as exc:
            defects.append(str(exc))
    duplicates = sorted({ident for ident in ids if ids.count(ident) > 1})
    if duplicates:
        defects.append(f"{source}: duplicate access-pattern identifier(s): {', '.join(duplicates)}")
    defects.extend(output_row_defects(patterns, source=source))
    try:
        tables = sqlite_schema_tables(text, source=source, require_key=False)
    except SpecificationError:
        # An unreadable schema is reported by the checks that own it; no field can be judged.
        return tuple(defects)
    for table in tables:
        keys = [column.name for column in table.columns if column.primary_key]
        if len(keys) != 1:
            defects.append(_key_count_defect(table.name, keys, source=source))
    columns_of = {table.name: tuple(column.name for column in table.columns) for table in tables}
    binding: list[AccessPattern] = []
    for pattern in patterns:
        found = _input_column_defects(columns_of, (pattern,), source) + _output_column_defects(
            columns_of, (pattern,), source
        )
        defects.extend(found)
        if not found:
            binding.append(pattern)
    # Shape is judged on fields that bind, so a misnamed column is reported once, not twice.
    defects.extend(
        _operation_shape_defects({table.name: table for table in tables}, binding, source)
    )
    return tuple(defects)


def input_column_defects(text: str, *, source: str = "DATABASE.md") -> tuple[str, ...]:
    """Name every ``Input:`` field that is not a column of the table its operation reaches.

    The generated repository binds each Input field as the column of that name: the predicate of
    a ``get``, ``list``, or ``delete`` and the values of a ``create`` or ``update``. A field the
    table does not declare cannot be bound, and SQLite reads a double-quoted unknown identifier as
    a string literal, so ``"book_id" = ?`` matches nothing and a delete silently removes nothing
    (ReadingList ``20261022.180908``). An unreadable schema or an undeclared table is reported by
    the checks that own them.
    """
    try:
        tables = sqlite_schema_tables(text, source=source)
        contract = parse_database_contract(text, source=source)
    except SpecificationError:
        return ()
    columns_of = {table.name: tuple(column.name for column in table.columns) for table in tables}
    return _input_column_defects(columns_of, contract.patterns, source)


def _input_column_defects(
    columns_of: Mapping[str, tuple[str, ...]], patterns: Sequence[AccessPattern], source: str
) -> tuple[str, ...]:
    defects: list[str] = []
    for pattern in patterns:
        for operation in pattern.operations:
            table = operation.split(".", 1)[0]
            columns = columns_of.get(table)
            if columns is None:
                continue
            for field in pattern.inputs:
                column = pattern.column_of(field.name)
                if column not in columns:
                    subject = (
                        f"Input field `{field.name}` is compared with `{column}`, which is not"
                        if column != field.name
                        else f"Input field `{field.name}` is not"
                    )
                    defects.append(
                        f"{source}: {pattern.identifier} {subject} a column of `{table}` "
                        f"({', '.join(columns)}). Each Input field is bound "
                        "as the column of the same name; name the column it means, or compare "
                        "an argument with a column in `| Match |`, such as `date >= start_date`."
                    )
    return tuple(defects)


def output_column_defects(text: str, *, source: str = "DATABASE.md") -> tuple[str, ...]:
    """Name every ``Output:`` field the generated repository cannot return.

    A ``get``, ``list``, ``create``, or ``update`` returns its Output row built from the table's
    columns, and a ``list`` returns one such row per record, so a collection field such as
    ``books: list[Book]`` names no column and builds an empty row (ReadingList
    ``20261023.200606``). A ``delete`` returns its Output built from the key it was given, so
    every field must be one of its Input fields.
    """
    try:
        tables = sqlite_schema_tables(text, source=source)
        contract = parse_database_contract(text, source=source)
    except SpecificationError:
        return ()
    columns_of = {table.name: tuple(column.name for column in table.columns) for table in tables}
    return _output_column_defects(columns_of, contract.patterns, source)


def _output_column_defects(
    columns_of: Mapping[str, tuple[str, ...]], patterns: Sequence[AccessPattern], source: str
) -> tuple[str, ...]:
    defects: list[str] = []
    for pattern in patterns:
        for operation in pattern.operations:
            table, verb = operation.partition(".")[0], pattern.kind
            columns = columns_of.get(table)
            if columns is None:
                continue
            if verb in ("get", "list", "create", "update", "upsert"):
                shape = (
                    "one Output row per record, so the Output names the row's columns, never a "
                    "collection of rows"
                    if verb == "list"
                    else "its Output row read from the table"
                )
                for field in pattern.outputs:
                    if field.name not in columns:
                        defects.append(
                            f"{source}: {pattern.identifier} Output field `{field.name}` is not a "
                            f"column of `{table}` ({', '.join(columns)}). `{operation}` returns "
                            f"{shape}."
                        )
            elif verb == "delete":
                inputs = tuple(field.name for field in pattern.inputs)
                for field in pattern.outputs:
                    if field.name not in inputs:
                        defects.append(
                            f"{source}: {pattern.identifier} Output field `{field.name}` is not "
                            f"an Input field ({', '.join(inputs) or 'none'}). `{operation}` "
                            "returns its Output built from the key it was given."
                        )
    return tuple(defects)


@dataclass(frozen=True)
class ResolvedOperation:
    """One declared operation with every implicit choice made explicit.

    ``name`` is the method callers use; ``verb`` is its Kind, how it runs. ``match`` is the
    equality ``WHERE`` of a ``get``, ``update``, ``upsert``, or ``delete``; ``filters`` are the
    optional filters of a ``list``; ``sets`` are the columns a ``create``, ``update``, or
    ``upsert`` writes. ``compare`` holds ``(field, op, column)`` for each field of ``match`` or
    ``filters`` compared by something other than equality with its own column, and ``order`` the
    ``(column, direction)`` sort keys of a ``list``. ``many`` is decided from the schema, never
    declared: an equality match covering the primary key or a declared ``UNIQUE`` reaches at most
    one row.
    """

    identifier: str
    table: str
    verb: str
    inputs: tuple[str, ...]
    match: tuple[str, ...]
    filters: tuple[str, ...]
    sets: tuple[str, ...]
    many: bool
    output_name: str
    outputs: tuple[str, ...]
    name: str = ""
    compare: tuple[tuple[str, str, str], ...] = ()
    order: tuple[tuple[str, str], ...] = ()

    @property
    def operation(self) -> str:
        return f"{self.table}.{self.name or self.verb}"

    @property
    def keys(self) -> tuple[str, ...]:
        """The Match fields compared by equality: what reads back the one row a write reached."""
        compared = {field for field, op, _ in self.compare if op != "="}
        return tuple(field for field in self.match if field not in compared)

    @property
    def returns_row(self) -> bool:
        """True when the operation returns its Output row rather than a count or key."""
        return bool(self.outputs) and not (self.many and self.verb in ("update", "delete"))


def unique_keys(table: SQLiteTable) -> tuple[tuple[str, ...], ...]:
    """Every column set that identifies at most one row: the PK, each UNIQUE column or bullet."""
    keys = [(column.name,) for column in table.columns if column.primary_key]
    keys += [(column.name,) for column in table.columns if column.unique and not column.primary_key]
    keys += [item.columns for item in table.constraints if item.kind == "UNIQUE"]
    return tuple(keys)


def _identifies_one(table: SQLiteTable, match: Collection[str]) -> bool:
    return bool(match) and any(set(key) <= set(match) for key in unique_keys(table))


def _keys_text(table: SQLiteTable) -> str:
    return ", ".join(
        "(" + ", ".join(f"`{name}`" for name in key) + ")" for key in unique_keys(table)
    )


def resolve_operation(pattern: AccessPattern, table: SQLiteTable) -> ResolvedOperation:
    """Make one pattern's match, filters, sets, and cardinality explicit.

    Without a ``| Match |`` row an ``update`` matches the primary key and a ``get`` or ``delete``
    matches every Input field, which is what the runtime did before ``Match`` existed. ``list``
    filters on its Input fields and ``create`` matches nothing.
    """
    verb = pattern.kind
    inputs = tuple(field.name for field in pattern.inputs)
    primary = next((column.name for column in table.columns if column.primary_key), "")
    if verb in ("list", "create"):
        match: tuple[str, ...] = ()
    elif pattern.match:
        match = pattern.match
    elif verb == "update":
        match = (primary,)
    elif verb in ("get", "delete"):
        match = inputs
    else:
        match = ()
    filters = inputs if verb == "list" else ()
    sets = (
        inputs
        if verb == "create"
        else tuple(name for name in inputs if name not in match)
        if verb in ("update", "upsert")
        else ()
    )
    compared = {field: op for field, op, _ in pattern.compare}
    equal = [pattern.column_of(field) for field in match if compared.get(field, "=") == "="]
    many = verb == "list" or (verb in ("update", "delete") and not _identifies_one(table, equal))
    return ResolvedOperation(
        identifier=pattern.identifier,
        table=table.name,
        verb=verb,
        inputs=inputs,
        match=match,
        filters=filters,
        sets=sets,
        many=many,
        output_name=pattern.output_name,
        outputs=tuple(field.name for field in pattern.outputs),
        name=pattern.operations[0].partition(".")[2],
        compare=pattern.compare,
        order=pattern.order,
    )


def resolved_operations(text: str, *, source: str = "DATABASE.md") -> tuple[ResolvedOperation, ...]:
    """Every declared operation on a declared table, resolved; unreadable input yields ``()``."""
    try:
        tables = {table.name: table for table in sqlite_schema_tables(text, source=source)}
        contract = parse_database_contract(text, source=source)
    except SpecificationError:
        return ()
    return tuple(
        resolve_operation(pattern, tables[name])
        for pattern in contract.patterns
        if (name := pattern.operations[0].partition(".")[0]) in tables
    )


def operation_shape_defects(text: str, *, source: str = "DATABASE.md") -> tuple[str, ...]:
    """Name every operation whose match, writes, or return the runtime cannot honor exactly.

    Each rule removes a guess a builder would otherwise make: which rows a write reaches, whether
    one row or many come back, and what a call returns. An operation name is a method, so a
    table grants each name once, and two names that run the same statement are synonyms whose
    callers would drift apart.
    """
    try:
        tables = {table.name: table for table in sqlite_schema_tables(text, source=source)}
        contract = parse_database_contract(text, source=source)
    except SpecificationError:
        return ()
    return _operation_shape_defects(tables, contract.patterns, source)


def _operation_shape_defects(
    tables: Mapping[str, SQLiteTable], patterns: Sequence[AccessPattern], source: str
) -> tuple[str, ...]:
    defects: list[str] = []
    seen: dict[str, str] = {}
    shapes: dict[tuple[object, ...], str] = {}
    for pattern in patterns:
        operation = pattern.operations[0]
        name = operation.partition(".")[0]
        verb = pattern.kind
        table = tables.get(name)
        if table is None:
            continue
        ident = pattern.identifier
        if operation in seen:
            defects.append(
                f"{source}: {ident} declares `{operation}`, which {seen[operation]} already "
                f"declares. An operation name is one method, `db.{operation}(...)`; give this "
                "one its own name and `| Kind |`, or merge the two patterns."
            )
            continue
        seen[operation] = ident
        resolved = resolve_operation(pattern, table)
        shape = (
            name,
            verb,
            resolved.match,
            resolved.filters,
            resolved.sets,
            resolved.outputs,
            resolved.compare,
            resolved.order,
        )
        if shape in shapes:
            defects.append(
                f"{source}: {ident} `{operation}` runs exactly what {shapes[shape]} runs: the "
                "same Kind, Match, Sets, and Output. One operation serves every caller; cite "
                f"{shapes[shape]} instead."
            )
            continue
        shapes[shape] = ident
        if sum(1 for column in table.columns if column.primary_key) != 1:
            # Names and synonyms hold whatever the key; the rules below read it, and the table's
            # PK count is reported on its own.
            continue
        inputs = set(resolved.inputs)
        stray = [item for item in pattern.match if item not in inputs]
        if stray:
            defects.append(
                f"{source}: {ident} Match names {', '.join(f'`{item}`' for item in stray)}, "
                f"which {'is' if len(stray) == 1 else 'are'} not Input fields. Every Match "
                "field is an Input field the caller supplies."
            )
            continue
        repeated = sorted({item for item in pattern.match if pattern.match.count(item) > 1})
        if repeated:
            defects.append(
                f"{source}: {ident} Match names {', '.join(f'`{item}`' for item in repeated)} "
                "more than once. Each Input field binds one parameter; a range compares two "
                "fields with one column, such as `date >= start_date`, `date <= end_date`."
            )
            continue
        columns = {column.name for column in table.columns}
        if pattern.compare and verb not in ("list", "update", "delete"):
            defects.append(
                f"{source}: {ident} `{operation}` is a `{verb}`, which matches each Input field "
                f"by equality with the column of its own name, so `{_term(pattern.compare[0])}` "
                "cannot apply. A comparison term belongs to a `list`, `update`, or `delete`."
            )
        if pattern.order and verb != "list":
            defects.append(
                f"{source}: {ident} `{operation}` is a `{verb}`; only a `list` returns rows in "
                "an order. Remove the Order row."
            )
        unknown = [column for column, _ in pattern.order if column not in columns]
        if unknown:
            defects.append(
                f"{source}: {ident} Order names {', '.join(f'`{item}`' for item in unknown)}, "
                f"which {'is' if len(unknown) == 1 else 'are'} not a column of `{name}` "
                f"({', '.join(column.name for column in table.columns)})."
            )
        if verb == "create" and pattern.match:
            defects.append(
                f"{source}: {ident} `{operation}` inserts one row and declares no Match; remove "
                "the Match row."
            )
        elif verb == "get":
            if set(resolved.match) != inputs:
                defects.append(
                    f"{source}: {ident} `{operation}` reads one row by its Match, so its "
                    "Input fields are exactly its Match fields."
                )
            elif not _identifies_one(table, resolved.match):
                defects.append(
                    f"{source}: {ident} `{operation}` matches "
                    f"({', '.join(resolved.match)}), which identifies no single row of "
                    f"`{name}`. A get matches a unique key: {_keys_text(table)}. Reading "
                    "rows by a non-unique field is a `list`."
                )
        elif verb in ("update", "upsert"):
            if verb == "update" and not pattern.match and resolved.match[0] not in inputs:
                defects.append(
                    f"{source}: {ident} `{operation}` matches the primary key "
                    f"`{resolved.match[0]}` by default, which is not an Input field. Add it "
                    "to the Input, or declare `| Match | <columns> |`."
                )
            elif verb == "upsert" and not any(
                set(key) == set(resolved.match) for key in unique_keys(table)
            ):
                defects.append(
                    f"{source}: {ident} `{operation}` inserts or replaces the row its Match "
                    f"identifies, so `| Match |` names exactly one unique key of `{name}`: "
                    f"{_keys_text(table)}."
                )
            elif verb == "update" and not resolved.sets:
                defects.append(
                    f"{source}: {ident} `{operation}` sets nothing: every Input field is a "
                    "Match field. Add the columns it writes to the Input."
                )
            if verb == "upsert":
                absent = [
                    column.name
                    for column in table.columns
                    if column.not_null
                    and column.default is None
                    and not column.primary_key
                    and column.name not in inputs
                ]
                if absent:
                    defects.append(
                        f"{source}: {ident} `{operation}` may insert, so its Input carries "
                        f"every NOT NULL column without a DEFAULT: missing "
                        f"{', '.join(f'`{item}`' for item in absent)}."
                    )
        elif verb == "delete" and set(resolved.match) != inputs:
            defects.append(
                f"{source}: {ident} `{operation}` removes the rows its Match identifies, so "
                "its Input fields are exactly its Match fields."
            )
        if resolved.many and verb in ("update", "delete") and resolved.outputs:
            defects.append(
                f"{source}: {ident} `{operation}` matches ({', '.join(resolved.match)}), "
                f"which is no unique key of `{name}` ({_keys_text(table)}), so it reaches "
                "many rows and returns their count. Declare its Output with no fields, or "
                "match a unique key."
            )
    return tuple(defects)


#: Declared field types as the type a caller holds. Length and nullability are storage facts, so
#: ``VARCHAR(12)``, ``VARCHAR(40)``, and ``TEXT | None`` are all ``str`` to a caller.
CALLER_TYPES = {
    "int": "int",
    "integer": "int",
    "int64": "int",
    "bigint": "int",
    "smallint": "int",
    "str": "str",
    "string": "str",
    "text": "str",
    "varchar": "str",
    "char": "str",
    "character varying": "str",
    "date": "str",
    "timestamp": "str",
    "uuid": "str",
    "bool": "bool",
    "boolean": "bool",
    "float": "float",
    "float64": "float",
    "number": "float",
    "real": "float",
    "double precision": "float",
    "numeric": "float",
    "decimal": "float",
    "bytes": "bytes",
    "any": "object",
    "object": "object",
}


def caller_type(declared: str) -> str:
    """The type a caller sees for a declared field: no length, no nullability, no modifiers."""
    value = declared.strip().casefold()
    for suffix in (" | none", "| none"):
        value = value.removesuffix(suffix).strip()
    base = re.sub(r"\s*\(.*\)$", "", value.split()[0] if value else "")
    if value.startswith(("double precision", "character varying")):
        base = " ".join(value.split()[:2])
    return CALLER_TYPES.get(base, base or "object")


def _field_types(fields: Iterable[Field]) -> dict[str, str]:
    return {field.name: caller_type(field.type) for field in fields}


def _quote(name: str) -> str:
    return f'"{name}"'


def _term(comparison: tuple[str, str, str]) -> str:
    field, op, column = comparison
    return f"{column} {op} {field}"


def _terms(names: Sequence[str], compare: Sequence[tuple[str, str, str]]) -> tuple[str, ...]:
    """Each field as its Match term: bare under equality with its own column, else compared."""
    by_field = {item[0]: item for item in compare}
    return tuple(_term(by_field[name]) if name in by_field else name for name in names)


def _where(names: Sequence[str], compare: Sequence[tuple[str, str, str]] = ()) -> str:
    by_field = {field: (op, column) for field, op, column in compare}
    terms = [
        f"{_quote(by_field.get(name, ('=', name))[1])} {by_field.get(name, ('=', name))[0]} ?"
        for name in names
    ]
    return (" WHERE " + " AND ".join(terms)) if terms else ""


def _order_by(order: Sequence[tuple[str, str]]) -> str:
    keys = ", ".join(f"{_quote(column)} {direction.upper()}" for column, direction in order)
    return f" ORDER BY {keys}" if keys else ""


def operation_sql(operation: ResolvedOperation, table: SQLiteTable) -> tuple[str, ...]:
    """The statements the runtime executes for one operation, in SQLite placeholder form.

    Spelled exactly as the shipped ``Driver`` builds them, so the contract shows what runs; a
    test holds the two byte-identical. PostgreSQL binds the same positions with its own marker.
    """
    columns = [name for name in operation.outputs if name in {c.name for c in table.columns}]
    selected = ", ".join(_quote(name) for name in (columns or [c.name for c in table.columns]))
    target = _quote(table.name)

    def select(predicate: Sequence[str], order: Sequence[tuple[str, str]] = ()) -> str:
        where = _where(predicate, operation.compare)
        return f"SELECT {selected} FROM {target}{where}{_order_by(order)}"

    def insert(names: Sequence[str]) -> str:
        marks = ", ".join("?" for _ in names)
        return f"INSERT INTO {target} ({', '.join(_quote(n) for n in names)}) VALUES ({marks})"

    verb = operation.verb
    if verb == "get":
        return (select(operation.match),)
    if verb == "list":
        return (select(operation.filters, operation.order),)
    if verb == "create":
        primary = next(column.name for column in table.columns if column.primary_key)
        return (insert(operation.inputs),) + ((select((primary,)),) if operation.outputs else ())
    if verb == "update":
        assignments = ", ".join(f"{_quote(name)} = ?" for name in operation.sets)
        statement = f"UPDATE {target} SET {assignments}{_where(operation.match, operation.compare)}"
        return (statement,) + ((select(operation.keys),) if operation.returns_row else ())
    if verb == "upsert":
        conflict = ", ".join(_quote(name) for name in operation.match)
        action = (
            "DO UPDATE SET "
            + ", ".join(f"{_quote(n)} = excluded.{_quote(n)}" for n in operation.sets)
            if operation.sets
            else "DO NOTHING"
        )
        statement = f"{insert(operation.inputs)} ON CONFLICT ({conflict}) {action}"
        return (statement,) + ((select(operation.match),) if operation.outputs else ())
    return (f"DELETE FROM {target}{_where(operation.match, operation.compare)}",)


def _json(fields: Mapping[str, str], optional: Collection[str] = ()) -> str:
    return (
        "{"
        + ", ".join(
            f'"{name}": "{kind}{"?" if name in optional else ""}"' for name, kind in fields.items()
        )
        + "}"
    )


def _output_json(operation: ResolvedOperation, pattern: AccessPattern, table: SQLiteTable) -> str:
    row = _json(_field_types(pattern.outputs))
    if operation.verb == "list":
        return f"[{row}]"
    if operation.returns_row:
        return row if operation.verb in ("create", "upsert") else f"{row} | null"
    if operation.verb == "create":
        primary = next(column for column in table.columns if column.primary_key)
        return f'"{caller_type(primary.sql_type)}" (the new key)'
    return '"int" (rows changed)'


def _contract_payload(pattern: AccessPattern, table: SQLiteTable | None) -> str:
    """What callers depend on, and nothing a storage change can move.

    Name, Kind, Match, cardinality, return shape, and each field's name and caller type. Length,
    nullability, Required, defaults, indexes, and the SQL are excluded, so widening a column or
    relaxing NOT NULL rebuilds nothing.
    """
    resolved = resolve_operation(pattern, table) if table is not None else None
    matched: Sequence[str] = resolved.match if resolved else pattern.match
    if resolved and pattern.compare:
        # A comparison or an order is caller-visible; a pattern declaring neither hashes as before.
        matched = _terms(resolved.match or resolved.filters, pattern.compare)
    order = (
        ("order:" + ",".join(f"{column} {direction}" for column, direction in pattern.order),)
        if pattern.order
        else ()
    )
    return "\x1f".join((
        pattern.operations[0],
        pattern.kind,
        "match:" + ",".join(matched),
        *order,
        "rows:" + ("" if resolved is None else "many" if resolved.many else "one"),
        "returns:" + ("" if resolved is None else "row" if resolved.returns_row else "count"),
        *(f"in:{name}:{kind}" for name, kind in _field_types(pattern.inputs).items()),
        f"out:{pattern.output_name}",
        *(f"out:{name}:{kind}" for name, kind in _field_types(pattern.outputs).items()),
    ))


def _cells(values: Iterable[str]) -> str:
    rendered = ", ".join(f"`{value}`" for value in values)
    return rendered or "—"


_SURFACE_RULES = (
    "Generated by Drydock from this declaration; it is the complete persistence surface. Each "
    "operation is a method `db.<table>.<name>(field=value, ...)` (Go: "
    "`db.<Table>.<Name>(ctx, <Table><Name>Input{...})`) taking exactly its Input fields. Match "
    "fields are required and compared with their column, joined with AND: a bare field by equality "
    "with the column of its name, a term `<column> <op> <field>` by `=`, `<`, `<=`, `>`, or `>=`. "
    "A field marked `?` may be omitted: an omitted `list` filter or bound does not constrain, and "
    "an `update` sets only the fields supplied. A `list` with an Order returns its rows in that "
    "order, and in no stated order otherwise. No other operator, no OR, no join, and no SQL "
    "exists. An operation reaches one row when its equality Match covers a unique key, and many "
    "rows otherwise. `upsert` "
    "inserts the row its Match identifies, or replaces that row's Set columns when it exists, in "
    "one atomic statement. The SQL is what runs, in SQLite form. An operation not listed raises "
    "`UnknownOperation`; to reach the store differently, declare a pattern in `DATABASE.md`. "
    "Contract is the operation's fingerprint: it changes only when the call, its Kind, Match, "
    "rows, or a field's name or caller type changes, never for a length or nullability change."
)


def operation_surface(text: str, *, source: str = "DATABASE.md") -> str:
    """Render the per-operation contract a builder calls, or ``""`` when none is declared.

    Deterministic, so the compact derivative a builder reads states exactly the call, the JSON
    it takes and returns, which rows it reaches, and the SQL that runs, rather than leaving a
    model to summarize it.
    """
    try:
        tables = sqlite_schema_tables(text, source=source)
        contract = parse_database_contract(text, source=source)
    except SpecificationError:
        return ""
    fingerprints = parse_database_operation_fingerprints(database_operation_fingerprints(text))
    by_table = {table.name: table for table in tables}
    patterns = [p for p in contract.patterns if p.operations[0].partition(".")[0] in by_table]
    if not tables or not patterns:
        return ""
    lines = ["## Operation Surface", "", _SURFACE_RULES]
    for table in tables:
        mine = [p for p in patterns if p.operations[0].partition(".")[0] == table.name]
        lines += ["", f"### `{table.name}`", "", f"Unique keys: {_keys_text(table)}"]
        if not mine:
            lines += ["", "- No declared operation."]
            continue
        for pattern in mine:
            item = resolve_operation(pattern, table)
            if item.verb == "list":
                rows, optional = "0..n", item.filters
            else:
                rows = "1" if item.verb in ("create", "upsert") else "0..n" if item.many else "0..1"
                optional = item.sets if item.verb == "update" else ()
            sql = "\n".join(f"{statement};" for statement in operation_sql(item, table))
            lines += [
                "",
                f"#### `db.{item.operation}` — {item.identifier}",
                "",
                "| Kind | Rows | Match | Sets | Contract |",
                "|---|---|---|---|---|",
                f"| {item.verb} | {rows} | {_cells(_terms(item.match or item.filters, item.compare))} | "
                f"{_cells(item.sets)} | `{fingerprints.get(item.identifier, '')[:12]}` |",
                "",
                f"- Input: `{_json(_field_types(pattern.inputs), optional)}`",
                f"- Output: `{_output_json(item, pattern, table)}`",
                *(
                    [f"- Order: {', '.join(f'`{c}` {d}' for c, d in item.order)}"]
                    if item.order
                    else []
                ),
                "",
                "```sql",
                sql,
                "```",
            ]
    return "\n".join(lines) + "\n"


def parse_database_interface(text: str, *, source: str = "Blueprint") -> tuple[DatabaseUse, ...]:
    """Read a Blueprint's database-interface declaration.

    Every bullet in the section is an entry, and every entry must parse. Reading only the
    lines that happened to match let a Blueprint describe its persistence in prose beside one
    well-formed citation and pass, which is the failure this section exists to catch.
    """
    section = _section(text, "Database Interface")
    if not section.strip():
        return ()
    uses: list[DatabaseUse] = []
    declared_none = False
    for line in section.splitlines():
        if not _INTERFACE_BULLET_RE.match(line):
            continue
        if _INTERFACE_NONE_RE.match(line):
            declared_none = True
            continue
        match = _INTERFACE_RE.match(line)
        if match is None:
            raise SpecificationError(
                f"{source}: malformed ## Database Interface entry {line.strip()!r} — "
                f"{_INTERFACE_FORM}"
            )
        uses.append(
            DatabaseUse(
                identifier=match.group("id"),
                access=match.group("access").casefold(),
                supplies=_names(match.group("input") or ""),
                returns=_names(match.group("output") or match.group("only_output") or ""),
            )
        )
    if declared_none and uses:
        raise SpecificationError(
            f"{source}: ## Database Interface declares None and also cites "
            f"{len(uses)} access pattern(s); it reaches a repository or it does not"
        )
    if not declared_none and not uses:
        raise SpecificationError(
            f"{source}: ## Database Interface states no entry — {_INTERFACE_FORM}"
        )
    return tuple(uses)


def render_database_interface(contract: DatabaseContract, blueprint: str) -> str:
    """Return the ``## Database Interface`` body the declaration implies for ``blueprint``.

    A citation may only name a pattern the Blueprint owns, so an owner's section is a function of
    ``DATABASE.md`` alone: every owned pattern at its declared access, supplying every Input field
    and returning every Output field. A Blueprint that owns nothing declares ``- None``.
    """
    owned = [pattern for pattern in contract.patterns if pattern.owner == blueprint]
    if not owned:
        owners = sorted({pattern.owner for pattern in contract.patterns})
        why = (
            f"persistence is owned by {', '.join(owners)}."
            if owners
            else "no repository is declared."
        )
        return f"- None — {why}\n"

    def names(fields: tuple[Field, ...]) -> str:
        return ", ".join(f"`{field.name}`" for field in fields) or "—"

    return "".join(
        f"- `{pattern.identifier}` — {pattern.access}: {pattern.repository_operation} "
        f"- supplies: {names(pattern.inputs)} - returns: {names(pattern.outputs)}\n"
        for pattern in sorted(owned, key=lambda item: item.identifier)
    )


def replace_database_interface(text: str, body: str) -> str:
    """Replace the ``## Database Interface`` section body with ``body``, appending if absent."""
    match = next(
        (m for m in _SECTION_RE.finditer(text) if m.group(1).strip() == "Database Interface"),
        None,
    )
    if match is None:
        return text.rstrip("\n") + "\n\n## Database Interface\n\n" + body
    next_match = _SECTION_RE.search(text, match.end())
    tail = text[next_match.start() :] if next_match else ""
    return text[: match.end()] + "\n\n" + body + ("\n" + tail if tail else "")


def _names(value: str) -> tuple[str, ...]:
    return tuple(
        name
        for name in (item.strip().strip("`") for item in value.split(","))
        if not _no_field(name)
    )


def validate_database_interfaces(
    contract: DatabaseContract, interfaces: Mapping[str, Iterable[DatabaseUse]]
) -> None:
    """Reject feature contracts that escape the declared persistence API."""
    patterns = contract.by_id()
    for blueprint, uses in interfaces.items():
        for use in uses:
            pattern = patterns.get(use.identifier)
            if pattern is None:
                raise SpecificationError(
                    f"{blueprint}: unknown database operation {use.identifier} — "
                    f"no `### {use.identifier}` section is declared in ## Access Patterns"
                )
            if pattern.owner != blueprint and pattern.owner != SHARED_OWNER:
                raise SpecificationError(
                    f"{blueprint}: {use.identifier} is owned by {pattern.owner!r}, not this "
                    f"Blueprint. Either its `| Owner |` row names the owning Blueprint's file "
                    f"name — {blueprint} — or this Blueprint reaches no repository and declares "
                    f"`- None — <who owns it>.` instead. A service name is not an owner."
                )
            # A citation may narrow what the pattern grants — a read-only consumer of a
            # read-write surface is a real and useful claim — but never widen it.
            if use.access not in _ACCESS_GRANTS[pattern.access]:
                raise SpecificationError(
                    f"{blueprint}: {use.identifier} declares {use.access}, "
                    f"which {pattern.access} does not grant"
                )
            allowed_input = {field.name for field in pattern.inputs}
            allowed_output = {field.name for field in pattern.outputs}
            required_input = {field.name for field in pattern.inputs if field.required}
            supplied, returned = set(use.supplies), set(use.returns)
            if unknown := supplied - allowed_input:
                raise SpecificationError(
                    f"{blueprint}: {use.identifier} supplies undeclared field(s): {', '.join(sorted(unknown))}"
                )
            if missing := required_input - supplied:
                raise SpecificationError(
                    f"{blueprint}: {use.identifier} omits required field(s): {', '.join(sorted(missing))}"
                )
            if unknown := returned - allowed_output:
                raise SpecificationError(
                    f"{blueprint}: {use.identifier} returns undeclared field(s): {', '.join(sorted(unknown))}"
                )


def migration_records(blueprint_dir: Path) -> tuple[MigrationRecord, ...]:
    """Load Blueprint migration ledger records. Missing ledger means no staged migration."""
    directory = blueprint_dir / "migrations"
    if not directory.is_dir():
        return ()
    records: list[MigrationRecord] = []
    for path in sorted(directory.glob("MIGRATION-*.md")):
        match = _MIGRATION_FILE_RE.match(path.name)
        if match is None:
            continue
        text = path.read_text(encoding="utf-8")
        rows = {key.casefold(): value for key, value in _rows(text)}
        scope = match.group("scope")
        access_pattern = rows.get("access pattern", scope).strip()
        compatibility = rows.get("compatibility", "").casefold()
        state = rows.get("state", "planned").casefold()
        if access_pattern != scope:
            raise SpecificationError(f"{path}: Access Pattern must match its filename scope")
        if compatibility not in _COMPATIBILITY or state not in _MIGRATION_STATES:
            raise SpecificationError(f"{path}: invalid Compatibility or State")
        if not _section(text, "Upgrade").strip() or not _section(text, "Downgrade").strip():
            raise SpecificationError(f"{path}: requires ## Upgrade and ## Downgrade snippets")
        records.append(
            MigrationRecord(
                path,
                access_pattern,
                rows.get("revision", "").strip(),
                compatibility,
                state,
                rows.get("Ticket", match.group("ticket") or "").strip(),
            )
        )
    return tuple(records)


def staged_operation_ids(blueprint_dir: Path) -> tuple[str, ...]:
    """Operations with a migration not yet built into the generated application."""
    return tuple(
        record.access_pattern
        for record in migration_records(blueprint_dir)
        if record.state == "planned"
    )


def mark_migrations_built(blueprint_dir: Path) -> tuple[Path, ...]:
    """Advance planned ledger records after their DATABASE build story completes."""
    changed: list[Path] = []
    for record in migration_records(blueprint_dir):
        if record.state != "planned":
            continue
        text = record.path.read_text(encoding="utf-8")
        updated, count = re.subn(r"(?m)^(\|\s*State\s*\|\s*)planned(\s*\|\s*)$", r"\1built\2", text)
        if count != 1:
            raise SpecificationError(f"{record.path}: requires one State row")
        record.path.write_text(updated, encoding="utf-8", newline="\n")
        changed.append(record.path)
    return tuple(changed)


def create_ticket_migration_records(
    blueprint_dir: Path, ticket_texts: Iterable[str | Path]
) -> tuple[Path, ...]:
    """Create planned ledger records for DATABASE ticket operations not already recorded.

    A ticket names affected operation ids; its migration blocks remain intentionally skeletal
    until the DATABASE build story renders the application-specific Alembic directives.
    """
    database_path = blueprint_dir / "DATABASE.md"
    if not database_path.is_file() or "## Access Patterns" not in database_path.read_text(
        encoding="utf-8"
    ):
        return ()
    contract = parse_database_contract(database_path.read_text(encoding="utf-8"))
    patterns = contract.by_id()
    requested: list[tuple[str, str, str]] = []
    for source in ticket_texts:
        path = source if isinstance(source, Path) else None
        text = path.read_text(encoding="utf-8") if path is not None else source
        ticket_match = re.search(r"^drydock_id:\s*(TICKET-\d+)", text, re.MULTILINE)
        ticket_id = ticket_match.group(1) if ticket_match else ""
        kind_match = re.search(r"^drydock_kind:\s*(\S+)", text, re.MULTILINE)
        kind = kind_match.group(1) if kind_match else "database-access-pattern"
        compatibility_match = re.search(r"^drydock_compatibility:\s*(\S+)", text, re.MULTILINE)
        compatibility = compatibility_match.group(1) if compatibility_match else ""
        amends_match = re.search(r"^drydock_amends:\s*(\S+)", text, re.MULTILINE)
        amended_ids = (
            set(_OPERATION_ID_RE.findall(amends_match.group(1))) & set(patterns)
            if amends_match
            else set()
        )
        operation_ids = (
            sorted(amended_ids)
            if amended_ids
            else sorted(set(_OPERATION_ID_RE.findall(text)) & set(patterns))
        )
        if kind == "database-access-pattern" and operation_ids:
            for identifier in operation_ids:
                requested.append((
                    ticket_id,
                    identifier,
                    compatibility or patterns[identifier].compatibility,
                ))
        elif kind in {"database-private", "database-data"} and ticket_id:
            requested.append((
                ticket_id,
                "DATABASE",
                "data" if kind == "database-data" else "rebuild",
            ))

    existing = {
        (record.ticket_id, record.access_pattern) for record in migration_records(blueprint_dir)
    }
    directory = blueprint_dir / "migrations"
    created: list[Path] = []
    for ticket_id, identifier, compatibility in requested:
        identity = (ticket_id, identifier)
        if identity in existing:
            continue
        path = directory / (
            f"MIGRATION-{ticket_id}-{identifier}.md" if ticket_id else f"MIGRATION-{identifier}.md"
        )
        directory.mkdir(parents=True, exist_ok=True)
        revision = "_".join(part.casefold() for part in (ticket_id, identifier) if part).replace(
            "-", "_"
        )
        ticket_row = f"| Ticket | {ticket_id} |\n" if ticket_id else ""
        path.write_text(
            f"# Migration: {ticket_id + ' ' if ticket_id else ''}{identifier}\n\n"
            "| Field | Value |\n"
            "|---|---|\n" + ticket_row + f"| Access Pattern | {identifier} |\n"
            f"| Revision | {revision} |\n"
            f"| Compatibility | {compatibility} |\n"
            "| State | planned |\n\n"
            "## Upgrade\n\n"
            "```python\n"
            f"# Implement the {identifier} schema change with Alembic op directives.\n"
            "```\n\n"
            "## Downgrade\n\n"
            "```python\n"
            f"# Reverse the {identifier} schema change when supported.\n"
            "```\n",
            encoding="utf-8",
            newline="\n",
        )
        created.append(path)
        existing.add(identity)
    return tuple(created)


def changed_operation_ids_since(blueprint_dir: Path, commit: str) -> tuple[str, ...] | None:
    """Compare DATABASE access patterns to the applied Git revision when it is available.

    ``None`` represents an unavailable Git baseline, not an empty diff. Callers still use the
    Blueprint migration ledger in that case, which keeps non-Git Targets deterministic.
    """
    if not commit or commit == "-":
        return None
    database_path = blueprint_dir / "DATABASE.md"
    if not database_path.is_file():
        return None
    root = subprocess.run(
        ["git", "-C", str(blueprint_dir), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if root.returncode:
        return None
    root_path = Path(root.stdout.strip())
    try:
        relative = database_path.relative_to(root_path).as_posix()
    except ValueError:
        return None
    prior = subprocess.run(
        ["git", "-C", str(root_path), "show", f"{commit}:{relative}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if prior.returncode:
        return None
    old = parse_database_contract(prior.stdout, source=f"{commit}:{relative}").by_id()
    current = parse_database_contract(database_path.read_text(encoding="utf-8")).by_id()
    return tuple(
        sorted(
            identifier
            for identifier in set(old) | set(current)
            if old.get(identifier) != current.get(identifier)
        )
    )
