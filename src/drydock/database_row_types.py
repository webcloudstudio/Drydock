"""Shared Python output-row naming and field types for validation and generation."""

from __future__ import annotations

import re


def row_class_name(name: str) -> str:
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


def row_field_type(declared: str) -> str:
    """Map a declared field type to Python; a type outside the map is kept as written."""
    value = declared.strip()
    if not value:
        return "object"
    lowered = value.lower()
    if lowered.endswith(" | none"):
        return f"{row_field_type(value[: -len(' | none')])} | None"
    # A SQL column type such as VARCHAR(12) maps by its base name; the length is the schema's.
    return _PYTHON_TYPES.get(re.sub(r"\s*\(.*\)$", "", lowered), value)
