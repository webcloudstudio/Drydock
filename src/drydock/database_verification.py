"""Generate read-only runtime schema probes from the declared persistence contract."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from drydock.database_contract import schema_sql, sqlite_schema_tables


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def verification_probes(text: str) -> dict[str, list[dict[str, object]]]:
    """Catalog checks and nonnegative row counts; never insert test data or alter the store."""
    probes: dict[str, list[dict[str, object]]] = {"sqlite": [], "postgres": []}

    def add(engine: str, name: str, sql: str, expected: int = 1) -> None:
        probes[engine].append({"name": name, "sql": sql, "expected": expected})

    add("sqlite", "foreign-key-enforcement", "SELECT foreign_keys FROM pragma_foreign_keys")
    with sqlite3.connect(":memory:") as reference:
        reference.executescript(schema_sql(text))
        for table in sqlite_schema_tables(text):
            name = table.name
            literal = _literal(name)
            add(
                "sqlite",
                f"{name}:table",
                f"SELECT count(*) FROM sqlite_master WHERE name={literal} AND type='table'",
            )
            add(
                "postgres",
                f"{name}:table",
                f"SELECT count(*) FROM pg_class WHERE oid={literal}::regclass AND relkind IN ('r','p')",
            )
            for engine in probes:
                add(engine, f"{name}:rows", f'SELECT count(*) FROM "{name}"', -1)
            for column in table.columns:
                col = _literal(column.name)
                row = next(
                    r
                    for r in reference.execute(f"PRAGMA table_info({literal})")
                    if r[1] == column.name
                )
                # Compare SQL's own normalized column metadata, including defaults.
                sql = (
                    f"SELECT count(*) FROM pragma_table_info({literal}) WHERE name={col} "
                    f'AND upper(type)={_literal(row[2].upper())} AND "notnull"={row[3]} '
                    f"AND pk={row[5]} AND dflt_value IS "
                    + ("NULL" if row[4] is None else _literal(row[4]))
                )
                add("sqlite", f"{name}.{column.name}:column", sql)
                pg_type = {
                    "INTEGER": "integer",
                    "TEXT": "text",
                    "REAL": "real",
                    "NUMERIC": "numeric",
                }.get(column.sql_type, "character varying")
                sql = (
                    "SELECT count(*) FROM information_schema.columns WHERE table_schema=current_schema() "
                    f"AND table_name={literal} AND column_name={col} AND data_type={_literal(pg_type)} "
                    f"AND is_nullable={_literal('NO' if column.not_null or column.primary_key else 'YES')}"
                )
                if column.sql_type.startswith("VARCHAR("):
                    sql += f" AND character_maximum_length={column.sql_type[8:-1]}"
                if column.default is not None:
                    # PostgreSQL deparses literal defaults with casts and parentheses.
                    default = column.default
                    casts = {pg_type}
                    if pg_type == "character varying":
                        casts.add("text")
                    if pg_type in {"integer", "real", "numeric"}:
                        casts.update({"integer", "bigint", "numeric", "real", "double precision"})
                    literals = {default, f"({default})"}
                    if default.lstrip("-").replace(".", "", 1).isdigit():
                        literals.add(_literal(default))
                    forms = literals | {f"{value}::{cast}" for value in literals for cast in casts}
                    test = (
                        "column_default IN (" + ",".join(_literal(v) for v in sorted(forms)) + ")"
                    )
                    if default.upper() == "NULL":
                        test = "column_default IS NULL OR " + test
                    sql += " AND (" + test + ")"
                elif column.primary_key and column.sql_type == "INTEGER":
                    sql += " AND is_identity='YES'"
                else:
                    sql += " AND column_default IS NULL"
                add("postgres", f"{name}.{column.name}:column", sql)
                if column.primary_key:
                    add(
                        "postgres",
                        f"{name}.{column.name}:primary-key",
                        _pg_constraint(name, [column.name], "p"),
                    )
                if column.references:
                    parent, field = column.references
                    add(
                        "sqlite",
                        f"{name}.{column.name}:foreign-key",
                        f'SELECT count(*) FROM pragma_foreign_key_list({literal}) WHERE "from"={col} AND "table"={_literal(parent)} AND "to"={_literal(field)}',
                    )
                    add(
                        "postgres",
                        f"{name}.{column.name}:foreign-key",
                        _pg_constraint(name, [column.name], "f", parent, field),
                    )
            for index in reference.execute(f"PRAGMA index_list({literal})").fetchall():
                _, idx, unique, origin, _ = index
                columns = [r[2] for r in reference.execute(f"PRAGMA index_info({_literal(idx)})")]
                if origin == "pk":
                    continue  # column metadata above covers primary keys
                # Match column order, not engine-generated constraint/index names.
                joined = ",".join(columns)
                sql = (
                    f'SELECT count(*) FROM pragma_index_list({literal}) AS i WHERE i."unique"={unique} '
                    "AND (SELECT group_concat(name, ',') FROM "
                    "(SELECT name FROM pragma_index_info(i.name) ORDER BY seqno))="
                    + _literal(joined)
                )
                if origin == "c":
                    sql += f" AND i.name={_literal(idx)}"
                add("sqlite", f"{name}:{idx}", sql)
                if unique:
                    add("postgres", f"{name}:{idx}", _pg_constraint(name, columns, "u"))
                else:
                    add(
                        "postgres",
                        f"{name}:{idx}",
                        "SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid "
                        f"WHERE i.indrelid={literal}::regclass AND c.relname={_literal(idx)} "
                        "AND i.indisvalid AND (SELECT string_agg(a.attname, ',' ORDER BY k.n) "
                        "FROM unnest(i.indkey) WITH ORDINALITY k(attnum,n) JOIN pg_attribute a "
                        "ON a.attrelid=i.indrelid AND a.attnum=k.attnum)=" + _literal(joined),
                    )
    return probes


def _pg_constraint(
    table: str, columns: list[str], kind: str, parent: str = "", field: str = ""
) -> str:
    sql = (
        f"SELECT count(*) FROM pg_constraint c WHERE c.conrelid={_literal(table)}::regclass "
        f"AND c.contype={_literal(kind)} AND c.convalidated "
        "AND (SELECT string_agg(a.attname, ',' ORDER BY k.n) FROM unnest(c.conkey) "
        "WITH ORDINALITY k(attnum,n) JOIN pg_attribute a ON a.attrelid=c.conrelid "
        "AND a.attnum=k.attnum)=" + _literal(",".join(columns))
    )
    if parent:
        sql += f" AND c.confrelid={_literal(parent)}::regclass AND (SELECT a.attname FROM pg_attribute a WHERE a.attrelid=c.confrelid AND a.attnum=c.confkey[1])={_literal(field)}"
    return sql


def write_verification(text: str, build_dir: Path) -> Path:
    path = build_dir / "schema-verification.json"
    path.write_text(json.dumps(verification_probes(text), indent=2) + "\n", encoding="utf-8")
    return path
