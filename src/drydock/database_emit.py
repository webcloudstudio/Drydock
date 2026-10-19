"""Dispatch DATABASE.md generation to the selected language implementation."""

from __future__ import annotations

from pathlib import Path

from drydock.database_contract import sqlite_schema_tables
from drydock.database_emit_python import PACKAGE, SHIPPED_MODULES, render_schema_module
from drydock.errors import SpecificationError
from drydock.technology_stack import declared_language


def write_persistence_package(
    blueprint_dir: Path, build_dir: Path, *, language: str | None = None
) -> tuple[Path, ...]:
    """Generate only declared persistence, using the Target's selected language."""
    path = blueprint_dir / "DATABASE.md"
    if not path.is_file():
        return ()
    text = path.read_text(encoding="utf-8")
    if not sqlite_schema_tables(text):
        return ()
    selected = language or declared_language(blueprint_dir.parent) or "python"
    if selected == "python":
        from drydock.database_emit_python import write_python_persistence

        return write_python_persistence(blueprint_dir, build_dir)
    if selected == "go":
        from drydock.database_emit_go import write_go_persistence

        return write_go_persistence(text, build_dir)
    raise SpecificationError(f"No persistence generator for {selected!r}")


__all__ = ["PACKAGE", "SHIPPED_MODULES", "render_schema_module", "write_persistence_package"]
