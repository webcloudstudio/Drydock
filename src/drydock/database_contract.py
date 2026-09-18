"""Typed Blueprint contracts for encapsulated relational persistence.

``DATABASE.md`` owns the public repository operations.  Feature Blueprints only name those
operations through ``## Database Interface``; tables and Alembic implementation remain private.
Migration records under ``blueprint/migrations/`` are Drydock's planned/built ledger.  They are
not executable Alembic files and therefore never claim that a deployed database was upgraded.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from drydock.errors import SpecificationError

_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_H3_RE = re.compile(r"^###\s+([A-Z][A-Z0-9-]*-\d{3})\s+—\s+(.+?)\s*$", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$")
_INPUT_OUTPUT_RE = re.compile(r"^(Input|Output):\s*(.+?)\s*$", re.MULTILINE)
_INTERFACE_RE = re.compile(
    r"^\s*-\s+`(?P<id>[A-Z][A-Z0-9-]*-\d{3})`\s+—\s+"
    r"(?P<access>read-write|read|write)\s*:\s*.*?\s+-\s+supplies:\s*(?P<input>.*?)"
    r"\s+-\s+returns:\s*(?P<output>.*?)\s*$",
    re.MULTILINE | re.IGNORECASE,
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
_REPOSITORY_OPERATION_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


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
class SQLiteTable:
    """One table declared by the SQLite-facing portion of ``DATABASE.md``."""

    name: str
    fields: tuple[Field, ...]


_SQLITE_TABLE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_SQLITE_TYPES = frozenset({"BLOB", "INTEGER", "NUMERIC", "REAL", "TEXT"})


def sqlite_schema_tables(text: str, *, source: str = "DATABASE.md") -> tuple[SQLiteTable, ...]:
    """Read Markdown ``## `table_name``` declarations into a safe SQLite schema.

    ``DATABASE.md`` is a persistence declaration, not a Python test fixture.  This narrow,
    deterministic reader recognizes its table-heading/field-table form and leaves operation-only
    database contracts alone.  The result is used to prove the declaration can create and open a
    SQLite store before any model is asked to implement an application adapter.
    """
    tables: list[SQLiteTable] = []
    for match in _SECTION_RE.finditer(text):
        name = match.group(1).strip().strip("`")
        if not _SQLITE_TABLE_NAME_RE.fullmatch(name):
            continue
        fields = _field_table(text, match.end())
        if not fields:
            continue
        names: set[str] = set()
        for field in fields:
            if not _SQLITE_TABLE_NAME_RE.fullmatch(field.name):
                raise SpecificationError(f"{source}: {name} has invalid field name {field.name!r}")
            if field.name in names:
                raise SpecificationError(f"{source}: {name} declares {field.name!r} more than once")
            names.add(field.name)
            sql_type = field.type.upper().split(maxsplit=1)[0]
            if sql_type not in _SQLITE_TYPES:
                raise SpecificationError(
                    f"{source}: {name}.{field.name} has unsupported SQLite type {field.type!r}"
                )
        tables.append(SQLiteTable(name, fields))
    names = [table.name for table in tables]
    if len(names) != len(set(names)):
        raise SpecificationError(f"{source}: duplicate SQLite table declaration")
    return tuple(tables)


def sqlite_schema_sql(tables: Iterable[SQLiteTable]) -> str:
    """Render idempotent SQLite DDL from :func:`sqlite_schema_tables` output."""
    statements: list[str] = []
    for table in tables:
        columns = []
        for field in table.fields:
            tokens = field.type.upper().split()
            sql_type = tokens[0]
            suffix = " PRIMARY KEY" if "PK" in tokens else ""
            columns.append(f'"{field.name}" {sql_type}{suffix}')
        statements.append(f'CREATE TABLE IF NOT EXISTS "{table.name}" ({", ".join(columns)});')
    return "\n".join(statements)


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
    """Split a Repository operation cell into validated ``<table>.<verb>`` operations."""
    operations = tuple(
        item for item in (part.strip().strip("`").strip() for part in value.split(",")) if item
    )
    if not operations:
        raise SpecificationError(f"{source}: {identifier} names no repository operation")
    invalid = [item for item in operations if not _REPOSITORY_OPERATION_RE.fullmatch(item)]
    if invalid:
        raise SpecificationError(
            f"{source}: {identifier} has invalid repository operation(s) "
            f"{', '.join(repr(item) for item in invalid)}: each names one declared table and one "
            "verb as `<table>.<verb>`, lowercase, and several are separated by commas"
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


def parse_database_contract(text: str, *, source: str = "DATABASE.md") -> DatabaseContract:
    """Parse the public operation surface from a DATABASE Blueprint."""
    access_patterns = _section(text, "Access Patterns")
    if not access_patterns.strip():
        raise SpecificationError(f"{source}: missing required ## Access Patterns section")
    patterns: list[AccessPattern] = []
    matches = list(_H3_RE.finditer(access_patterns))
    if not matches:
        raise SpecificationError(f"{source}: ## Access Patterns has no named operation")
    for index, match in enumerate(matches):
        block = access_patterns[
            match.end() : matches[index + 1].start()
            if index + 1 < len(matches)
            else len(access_patterns)
        ]
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
        io = list(_INPUT_OUTPUT_RE.finditer(block))
        values: dict[str, tuple[str, tuple[Field, ...]]] = {}
        for io_match in io:
            values[io_match.group(1).casefold()] = (
                io_match.group(2).strip("` "),
                _field_table(block, io_match.end()),
            )
        if "input" not in values or "output" not in values:
            raise SpecificationError(f"{source}: {match.group(1)} requires Input and Output tables")
        patterns.append(
            AccessPattern(
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
        )
    ids = [pattern.identifier for pattern in patterns]
    if len(ids) != len(set(ids)):
        raise SpecificationError(f"{source}: duplicate access-pattern identifier")
    return DatabaseContract(tuple(patterns))


def parse_database_interface(text: str, *, source: str = "Blueprint") -> tuple[DatabaseUse, ...]:
    """Read a Blueprint's optional database-interface declaration."""
    section = _section(text, "Database Interface")
    if not section.strip():
        return ()
    uses: list[DatabaseUse] = []
    for match in _INTERFACE_RE.finditer(section):
        uses.append(
            DatabaseUse(
                identifier=match.group("id"),
                access=match.group("access").casefold(),
                supplies=_names(match.group("input")),
                returns=_names(match.group("output")),
            )
        )
    if not uses:
        raise SpecificationError(f"{source}: malformed ## Database Interface entry")
    return tuple(uses)


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
                    f"{blueprint}: unknown database operation {use.identifier}"
                )
            if pattern.owner != blueprint:
                raise SpecificationError(
                    f"{blueprint}: {use.identifier} is owned by {pattern.owner}, not this Blueprint"
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
