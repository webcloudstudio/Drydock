"""Typed Blueprint contracts for encapsulated relational persistence.

``DATABASE.md`` owns the public repository operations.  Feature Blueprints only name those
operations through ``## Database Interface``; tables and Alembic implementation remain private.
Migration records under ``blueprint/migrations/`` are Drydock's planned/built ledger.  They are
not executable Alembic files and therefore never claim that a deployed database was upgraded.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from drydock.errors import SpecificationError

_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_H3_RE = re.compile(r"^###\s+([A-Z][A-Z0-9-]*-\d{3})\s+—\s+(.+?)\s*$", re.MULTILINE)
#: One ``| Owner | <name> |`` row, split so the cell is replaceable without touching the table.
_OWNER_CELL_RE = re.compile(
    r"(?P<head>^\|\s*Owner\s*\|)(?P<owner>[^|\n]*)(?P<tail>\|)", re.MULTILINE
)
_TABLE_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$")
_INPUT_OUTPUT_RE = re.compile(r"^(Input|Output):\s*(.+?)\s*$", re.MULTILINE)
_INTERFACE_RE = re.compile(
    r"^\s*-\s+`(?P<id>[A-Z][A-Z0-9-]*-\d{3})`\s+—\s+"
    r"(?P<access>read-write|read|write)\s*:\s*.*?\s+-\s+supplies:\s*(?P<input>.*?)"
    r"\s+-\s+returns:\s*(?P<output>.*?)\s*$",
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
#: than carrying SQL text. A builder for five shapes is small and testable; one for an open verb
#: set is a SQL generator, which is the thing this design exists to avoid.
_REPOSITORY_VERBS = ("get", "list", "create", "update", "delete")
_REPOSITORY_OPERATION_RE = re.compile(
    r"^[a-z][a-z0-9_]*\.(?:" + "|".join(_REPOSITORY_VERBS) + r")$"
)


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


def sqlite_schema_tables(text: str, *, source: str = "DATABASE.md") -> tuple[SQLiteTable, ...]:
    """Read Markdown ``## `table_name``` declarations into a safe SQLite schema.

    ``DATABASE.md`` is a persistence declaration, not a Python test fixture.  This narrow,
    deterministic reader recognizes its table-heading/field-table form and leaves operation-only
    database contracts alone.  The result is used to prove the declaration can create and open a
    SQLite store before any model is asked to implement an application adapter.
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
                table.name, tuple(field.name for field in pattern.inputs if field.name in declared)
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
    Manifest's compact ``applied_specs`` registry.  It excludes every private
    DATABASE section, so a repository/schema/migration edit cannot invalidate a
    Feature merely by changing DATABASE.md's file digest.
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
        ))
        entries.append(f"{pattern.identifier}:{sha256(payload.encode()).hexdigest()}")
    return ";".join(entries)


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
            f"{invalid[0]!r}: it names one declared table and one verb as `<table>.<verb>`, "
            f"lowercase, where the verb is one of {', '.join(_REPOSITORY_VERBS)}"
        )
    return operations


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
    matches = list(_H3_RE.finditer(access_patterns))
    if not matches:
        raise SpecificationError(f"{source}: ## Access Patterns has no named operation")
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
    return AccessPattern(
        identifier=match.group(1),
        owner=metadata["owner"].strip(),
        access=access,
        repository_operation=metadata["repository operation"].strip("`"),
        operations=_repository_operations(
            metadata["repository operation"], identifier=match.group(1), source=source
        ),
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


def database_contract_defects(text: str, *, source: str = "DATABASE.md") -> tuple[str, ...]:
    """Return every reason :func:`parse_database_contract` would reject ``text``, or ``()``.

    The parser stops at the first bad pattern. A repair pass handed only that one fixes it and
    returns to find the next, so thirteen incomplete patterns cost thirteen passes against a
    budget sized for far fewer. Each pattern is judged on its own here.
    """
    try:
        blocks = _pattern_blocks(text, source)
    except SpecificationError as exc:
        return (str(exc),)
    defects: list[str] = []
    ids: list[str] = []
    for match, block in blocks:
        ids.append(match.group(1))
        try:
            _parse_access_pattern(match, block, source)
        except SpecificationError as exc:
            defects.append(str(exc))
    duplicates = sorted({ident for ident in ids if ids.count(ident) > 1})
    if duplicates:
        defects.append(f"{source}: duplicate access-pattern identifier(s): {', '.join(duplicates)}")
    return tuple(defects)


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
                supplies=_names(match.group("input")),
                returns=_names(match.group("output")),
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
        item.strip().strip("`") for item in value.split(",") if item.strip() and item.strip() != "—"
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
