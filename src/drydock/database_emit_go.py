"""Generate typed Go repositories from the shared DATABASE.md declaration."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from string import Template

from drydock.database_contract import (
    parse_database_contract,
    resolve_operation,
    schema_sql,
    sqlite_schema_tables,
)
from drydock.errors import SpecificationError
from drydock.paths import get_language_dir


def _export(name: str) -> str:
    result = "".join(
        part[:1].upper() + part[1:] for part in re.split(r"[^a-zA-Z0-9]+", name) if part
    )
    if not result or not result[0].isalpha():
        raise SpecificationError(f"Invalid Go declaration name: {name!r}")
    return result


def _type(name: str) -> str:
    types = {
        "int": "int64",
        "integer": "int64",
        "int64": "int64",
        "str": "string",
        "string": "string",
        "text": "string",
        "bool": "bool",
        "boolean": "bool",
        "float": "float64",
        "float64": "float64",
        "number": "float64",
        "bytes": "[]byte",
        "any": "any",
        "object": "any",
        "varchar": "string",
        "char": "string",
        "character varying": "string",
        "date": "string",
        "timestamp": "string",
        "bigint": "int64",
        "smallint": "int64",
        "real": "float64",
        "double precision": "float64",
        "numeric": "float64",
        "decimal": "float64",
    }
    value = name.strip().lower()
    if value.endswith(" | none"):
        return "*" + _type(value.removesuffix(" | none"))
    # A SQL column type such as VARCHAR(12) maps by its base name; the length is the schema's.
    value = re.sub(r"\s*\(.*\)$", "", value)
    if value not in types:
        raise SpecificationError(
            f"Unsupported Go persistence field type {name!r}; declare a scalar type"
        )
    return types[value]


def _strings(values) -> str:
    return "[]string{" + ",".join(json.dumps(v) for v in values) + "}"


def render_go_schema(text: str) -> str:
    tables = sqlite_schema_tables(text)
    patterns = parse_database_contract(text).patterns
    declarations: dict[str, str] = {}
    methods: dict[tuple[str, str], str] = {}
    operations = []
    table_map = {t.name: t for t in tables}

    reserved = {"Database", "Schema", "Operation", "Table", "Result", "Store"}
    reserved.update(_export(table.name) + "Repository" for table in tables)

    def declare(name, fields):
        member_names = [field.split()[0] for field in fields]
        if name in reserved or len(member_names) != len(set(member_names)):
            raise SpecificationError(f"Go declaration name collision: {name}")
        body = f"type {name} struct {{\n" + "\n".join(fields) + "\n}"
        if name in declarations and declarations[name] != body:
            raise SpecificationError(f"Conflicting Go type declaration {name}")
        declarations[name] = body

    for pattern in patterns:
        for operation in pattern.operations:
            table, name = operation.split(".")
            verb = pattern.kind
            if table not in table_map:
                raise SpecificationError(f"Go operation {operation} refers to an undeclared table")
            declared = table_map[table]
            column_names = {column.name for column in declared.columns}
            # A keyed create or update returns its declared Output row, read back by key, as a
            # get does, and a keyed delete returns its Output built from the key.
            keyed = any(column.primary_key for column in declared.columns)
            returns_row = verb in ("get", "list") or (
                verb in ("create", "update", "upsert", "delete") and keyed and bool(pattern.outputs)
            )
            for field in (*pattern.inputs, *(pattern.outputs if returns_row else ())):
                if field.name not in column_names:
                    raise SpecificationError(
                        f"Go operation {operation} refers to undeclared column {field.name}"
                    )
            repo = _export(table) + "Repository"
            input_type = _export(table) + _export(name) + "Input"
            members, args = [], []
            used = set()
            for field in pattern.inputs:
                field_name = _export(field.name)
                if field_name in used:
                    raise SpecificationError(f"Go input field collision: {field_name}")
                used.add(field_name)
                native = _type(field.type)
                optional = not field.required
                members.append(
                    f'{field_name} {"*" if optional else ""}{native} `json:"{field.name}"`'
                )
                if optional:
                    args.append(
                        f"if input.{field_name} != nil {{ args[{json.dumps(field.name)}] = *input.{field_name} }}"
                    )
                else:
                    args.append(f"args[{json.dumps(field.name)}] = input.{field_name}")
            declare(input_type, members)
            columns = [
                f.name for f in pattern.outputs if f.name in {c.name for c in declared.columns}
            ]
            native = "any"
            if returns_row:
                row = _export(pattern.output_name or table + "Row")
                declare(
                    row,
                    [
                        f'{_export(f.name)} {_type(f.type)} `json:"{f.name}"`'
                        for f in pattern.outputs
                    ],
                )
                native = "[]" + row if verb == "list" else "*" + row
                if verb == "delete":
                    # The declared Output, built from the key it was given; nil when nothing matched.
                    finish = f"if result.Count==0 {{return nil,nil}}; row,err:=Decode[{row}](args); return &row,err"
                elif verb != "list":
                    finish = f"if len(result.Rows)==0 {{return nil,nil}}; row,err:=Decode[{row}](result.Rows[0]); return &row,err"
                else:
                    finish = f"return Decode[[]{row}](result.Rows)"
                zero = "nil"
            elif verb == "create":
                key = next((c for c in declared.columns if c.primary_key), None)
                native = (
                    ("int64" if key.sql_type.upper() == "INTEGER" else "string") if key else "any"
                )
                zero = "0" if native == "int64" else ('""' if native == "string" else "nil")
                finish = f"return Decode[{native}](result.ID)"
            else:
                native, zero, finish = "int64", "0", "return result.Count,nil"
            body = (
                f"func (repo {repo}) {_export(name)}(ctx context.Context, input {input_type}) ({native},error) {{\n"
                "args:=map[string]any{}\n" + "\n".join(args) + "\n"
                f"result,err:=repo.db.Run(ctx,{json.dumps(table)},{json.dumps(name)},args)\n"
                f"if err!=nil {{return {zero},err}}\n{finish}\n}}"
            )
            if (table, name) in methods:
                if methods[table, name] != body:
                    raise SpecificationError(f"Conflicting Go operation declaration {operation}")
                continue
            methods[table, name] = body
            match = resolve_operation(pattern, declared).match
            operations.append(
                "{"
                + f"ID:{json.dumps(pattern.identifier)}, Table:{json.dumps(table)}, Verb:{json.dumps(verb)}, Name:{json.dumps(name)}, Inputs:{_strings(f.name for f in pattern.inputs)}, Columns:{_strings(columns)}, Match:{_strings(match)}"
                + "},"
            )
    fields, initializers, repositories, entries = [], [], [], []
    exported = set()
    for table in tables:
        name = _export(table.name)
        if name in exported or name in ("Database", "Close", "ApplySchema", "Run"):
            raise SpecificationError(f"Go table name collision: {name}")
        exported.add(name)
        fields.append(f"{name} {name}Repository")
        initializers.append(f"{name}:{name}Repository{{db:db}}")
        repositories.append(f"type {name}Repository struct {{db *Database}}")
        key = next((c.name for c in table.columns if c.primary_key), "")
        entries.append(
            "{"
            + f"Name:{json.dumps(table.name)}, Columns:{_strings(c.name for c in table.columns)}, Key:{json.dumps(key)}"
            + "},"
        )
    template = (get_language_dir("go") / "templates/schema.go.tmpl").read_text()
    return Template(template).substitute(
        declarations="\n\n".join(declarations.values()),
        tables="\n".join(entries),
        operations="\n".join(operations),
        fields="\n".join(fields),
        initializers=",".join(initializers),
        repositories="\n\n".join([*repositories, *methods.values()]),
    )


def write_go_persistence(text: str, build_dir: Path) -> tuple[Path, ...]:
    """Write a reusable nested module and link it into the existing Target module."""
    module = render_go_schema(text)  # Validate before any writes.
    if not (build_dir / "go.mod").is_file():
        raise SpecificationError(
            "Go persistence requires the language foundation to create go.mod first"
        )
    go = shutil.which("go")
    if not go:
        raise SpecificationError("Go persistence generation requires the Go toolchain")
    root = get_language_dir("go")
    package = build_dir / "persistence"
    package.mkdir(parents=True, exist_ok=True)
    written = []
    for name in ("db.go", "sqlite.go", "postgres.go", "go.mod", "go.sum"):
        dest = package / name
        shutil.copyfile(root / "persistence" / name, dest)
        written.append(dest)
    for name, content in [
        ("schema.go", module),
        ("testing.go", (root / "templates/testing.go.tmpl").read_text()),
    ]:
        path = package / name
        path.write_text(content)
        written.append(path)
    schema = build_dir / "schema.sql"
    schema.write_text("-- Generated from DATABASE.md.\n" + schema_sql(text) + "\n")
    written.append(schema)
    command = package / "cmd/drydock-schema/main.go"
    command.parent.mkdir(parents=True, exist_ok=True)
    command.write_text((root / "templates/apply.go.tmpl").read_text())
    written.append(command)
    edits = [
        "-require=drydock.local/persistence@v0.0.0",
        "-replace=drydock.local/persistence=./persistence",
    ]
    for name, version in re.findall(
        r"^\s*(github.com/\S+) (v\S+)", (package / "go.mod").read_text(), re.M
    ):
        edits.append(f"-require={name}@{version}")
    try:
        subprocess.run(
            [go, "mod", "edit", *edits],
            cwd=build_dir,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        subprocess.run(
            ["gofmt", "-w", *[str(p.resolve()) for p in written if p.suffix == ".go"]],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SpecificationError(f"Go persistence generation failed: {exc}") from exc
    sums = build_dir / "go.sum"
    lines = set(sums.read_text().splitlines()) if sums.exists() else set()
    lines.update((package / "go.sum").read_text().splitlines())
    sums.write_text("\n".join(sorted(lines)) + "\n")
    from drydock.database_verification import write_verification

    written.append(write_verification(text, build_dir))
    return tuple([*written, build_dir / "go.mod", sums])
