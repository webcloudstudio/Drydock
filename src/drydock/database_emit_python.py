"""Generate the Target's persistence package from ``DATABASE.md``.

The declaration is the source of the persistence layer, not merely a description checked against
it. Drydock copies the shipped engines from ``Rigging/languages/python/persistence/`` unchanged and emits one
generated module beside them, so the repository surface a build implements is the one the plan
declared rather than one re-derived from prose.

The generated module contains no SQL. It carries the declared tables, the declared operations, and
a row dataclass per read or create; statements are constructed by the driver for the engine in use.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from drydock.database_contract import (
    AccessPattern,
    parse_database_contract,
    schema_sql,
    sqlite_schema_tables,
)
from drydock.paths import get_database_dir, get_language_dir

#: Copied verbatim into the build. ``schema.py`` is generated beside them.
SHIPPED_MODULES = ("db.py", "sqlite.py", "postgres.py")
PACKAGE = "persistence"

_HEADER = (get_language_dir("python") / "templates" / "schema_header.py.tmpl").read_text(
    encoding="utf-8"
)

_FOOTER = (get_language_dir("python") / "templates" / "schema_footer.py.tmpl").read_text(
    encoding="utf-8"
)


#: The ``db_session`` fixture the Rigging foundation contract publishes. Generated with the package
#: because the build never writes under ``persistence/``.
_TESTING_MODULE = (get_language_dir("python") / "templates" / "testing.py.tmpl").read_text(
    encoding="utf-8"
)


def _identifier(name: str) -> str:
    """Turn a DTO name into a class name without inventing one when it is already usable."""
    cleaned = "".join(part for part in name if part.isalnum() or part == "_")
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"Row{cleaned}"
    return cleaned[0].upper() + cleaned[1:]


#: Declared DTO types, SQL or Python spelling, as the Python type a row field holds. Derived DTOs
#: carry the column's SQL type, and an annotation of ``INTEGER`` names nothing in Python.
_PYTHON_TYPES = {
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


def _python_type(declared: str) -> str:
    """Map a declared field type to Python; a type outside the map is kept as written."""
    value = declared.strip()
    if not value:
        return "object"
    lowered = value.lower()
    if lowered.endswith(" | none"):
        return f"{_python_type(value[: -len(' | none')])} | None"
    # A SQL column type such as VARCHAR(12) maps by its base name; the length is the schema's.
    return _PYTHON_TYPES.get(re.sub(r"\s*\(.*\)$", "", lowered), value)


def _row_classes(patterns: tuple[AccessPattern, ...]) -> dict[str, tuple[str, str]]:
    """One dataclass per distinct read or create output, keyed by pattern id.

    A create returns its declared Output row, as a read does. Two patterns naming the same DTO share one class. Field annotations are emitted in
    Python as mapped by ``_python_type`` and never evaluated — ``from __future__ import annotations``
    keeps them strings — so a declared type outside the map is preserved rather than dropped.
    """
    emitted: dict[str, str] = {}
    by_pattern: dict[str, tuple[str, str]] = {}
    for pattern in patterns:
        verbs = {operation.partition(".")[2] for operation in pattern.operations}
        if not pattern.outputs or not verbs & {"get", "list", "create"}:
            continue
        name = _identifier(pattern.output_name or f"{pattern.identifier}Row")
        annotations = "\n".join(
            f"    {field.name}: {_python_type(field.type)}" for field in pattern.outputs
        )
        body = f"@dataclass(frozen=True)\nclass {name}:\n{annotations}\n"
        emitted.setdefault(name, body)
        by_pattern[pattern.identifier] = (name, emitted[name])
    return by_pattern


def render_schema_module(text: str, *, source: str = "DATABASE.md") -> str:
    """Render ``schema.py`` from a ``DATABASE.md`` body."""
    tables = sqlite_schema_tables(text, source=source)
    contract = parse_database_contract(text)
    columns_of = {table.name: table.columns for table in tables}
    rows = _row_classes(contract.patterns)

    classes: list[str] = []
    seen: set[str] = set()
    for name, body in rows.values():
        if name not in seen:
            seen.add(name)
            classes.append(body)

    operations: list[str] = []
    for pattern in contract.patterns:
        for operation in pattern.operations:
            table, _, verb = operation.partition(".")
            declared = tuple(column.name for column in columns_of.get(table, ()))
            inputs = tuple(field.name for field in pattern.inputs)
            row_name = rows.get(pattern.identifier, (None, ""))[0]
            selected: tuple[str, ...] = ()
            if row_name is not None:
                selected = (
                    tuple(field.name for field in pattern.outputs if field.name in declared)
                    or declared
                )
            operations.append(
                f"    Operation(\n"
                f"        identifier={pattern.identifier!r},\n"
                f"        table={table!r},\n"
                f"        verb={verb!r},\n"
                f"        inputs={inputs!r},\n"
                f"        row={row_name or None},\n"
                f"        columns={selected!r},\n"
                f"    ),"
            )

    table_entries = "\n".join(
        f"        Table(name={table.name!r}, columns={tuple(column.name for column in table.columns)!r}, "
        f"primary_key={next((column.name for column in table.columns if column.primary_key), None)!r}),"
        for table in tables
    )
    extra = "".join(f', "{name}"' for name in sorted(seen))
    parts = [_HEADER.format(extra=extra)]
    if classes:
        parts.append("\n" + "\n\n".join(classes))
    parts.append(
        "\n\nSCHEMA = Schema(\n    tables=(\n"
        + table_entries
        + "\n    ),\n    operations=(\n"
        + "\n".join(operations)
        + "\n    ),\n)\n"
    )
    parts.append(_FOOTER)
    return "".join(parts)


def write_python_persistence(blueprint_dir: Path, build_dir: Path) -> tuple[Path, ...]:
    """Copy the shipped engines and emit the generated schema beside them.

    Returns every file written. A declaration with no tables writes nothing: a project without
    persistence gets no persistence package rather than an empty one.
    """
    database_path = blueprint_dir / "DATABASE.md"
    if not database_path.is_file():
        return ()
    text = database_path.read_text(encoding="utf-8")
    if not sqlite_schema_tables(text):
        return ()
    module = render_schema_module(text)

    package = build_dir / PACKAGE
    package.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name in SHIPPED_MODULES:
        destination = package / name
        shutil.copyfile(get_database_dir() / name, destination)
        written.append(destination)
    (package / "schema.py").write_text(module, encoding="utf-8", newline="\n")
    written.append(package / "schema.py")
    (package / "__init__.py").write_text(
        (get_language_dir("python") / "templates/init.py.tmpl").read_text(encoding="utf-8"),
        encoding="utf-8",
        newline="\n",
    )
    written.append(package / "__init__.py")
    (package / "testing.py").write_text(_TESTING_MODULE, encoding="utf-8", newline="\n")
    written.append(package / "testing.py")

    rendered = schema_sql(text)
    if rendered:
        path = build_dir / "schema.sql"
        path.write_text(
            "-- Generated by Drydock from DATABASE.md. Edit the declaration, not this file.\n"
            + rendered
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        written.append(path)
    from drydock.database_verification import write_verification

    written.append(write_verification(text, build_dir))
    return tuple(written)


__all__ = [
    "PACKAGE",
    "SHIPPED_MODULES",
    "render_schema_module",
    "write_python_persistence",
]
