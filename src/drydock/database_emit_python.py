"""Generate the Target's persistence package from ``DATABASE.md``.

The declaration is the source of the persistence layer, not merely a description checked against
it. Drydock copies the shipped engines from ``Rigging/languages/python/persistence/`` unchanged and emits one
generated module beside them, so the repository surface a build implements is the one the plan
declared rather than one re-derived from prose.

The generated module contains no SQL. It carries the declared tables, the declared operations, and
a row dataclass per read or create; statements are constructed by the driver for the engine in use.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from drydock.database_contract import (
    AccessPattern,
    output_row_defects,
    parse_database_contract,
    resolve_operation,
    schema_sql,
    sqlite_schema_tables,
)
from drydock.database_row_types import row_class_name, row_field_type
from drydock.errors import SpecificationError
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


def _row_classes(
    patterns: tuple[AccessPattern, ...], *, source: str = "DATABASE.md"
) -> dict[str, tuple[str, str]]:
    """One dataclass per distinct output, keyed by pattern id.

    A create or update returns its declared Output row, as a read does, and a delete returns its
    Output built from the key it was given. Two patterns naming the same DTO share one class, and
    a name declared with two different field sets is refused. Field annotations are emitted in
    Python as mapped by ``row_field_type`` and never evaluated — ``from __future__ import annotations``
    keeps them strings — so a declared type outside the map is preserved rather than dropped.
    """
    if defects := output_row_defects(patterns, source=source):
        raise SpecificationError("; ".join(defects))
    emitted: dict[str, str] = {}
    by_pattern: dict[str, tuple[str, str]] = {}
    for pattern in patterns:
        # Every Kind returns its Output row when one is declared; a count or key otherwise.
        if not pattern.outputs:
            continue
        name = row_class_name(pattern.output_name or f"{pattern.identifier}Row")
        annotations = "\n".join(
            f"    {field.name}: {row_field_type(field.type)}" for field in pattern.outputs
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
    tables_by_name = {table.name: table for table in tables}
    rows = _row_classes(contract.patterns, source=source)

    classes: list[str] = []
    seen: set[str] = set()
    for name, body in rows.values():
        if name not in seen:
            seen.add(name)
            classes.append(body)

    operations: list[str] = []
    for pattern in contract.patterns:
        for operation in pattern.operations:
            table, _, name = operation.partition(".")
            verb = pattern.kind
            declared = tuple(column.name for column in columns_of.get(table, ()))
            inputs = tuple(field.name for field in pattern.inputs)
            row_name = rows.get(pattern.identifier, (None, ""))[0]
            selected: tuple[str, ...] = ()
            match: tuple[str, ...] = ()
            if table in tables_by_name:
                match = resolve_operation(pattern, tables_by_name[table]).match
            if row_name is not None:
                # Validation holds every Output field to a column, so nothing falls back to
                # the whole table and a wrapper Output cannot build an empty row.
                selected = tuple(field.name for field in pattern.outputs if field.name in declared)
            operations.append(
                f"    Operation(\n"
                f"        identifier={pattern.identifier!r},\n"
                f"        table={table!r},\n"
                f"        verb={verb!r},\n"
                f"        inputs={inputs!r},\n"
                f"        row={row_name or None},\n"
                f"        columns={selected!r},\n"
                f"        match={match!r},\n"
                f"        name={name!r},\n"
                + (f"        compare={pattern.compare!r},\n" if pattern.compare else "")
                + (f"        order={pattern.order!r},\n" if pattern.order else "")
                + "    ),"
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
