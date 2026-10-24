"""Dispatch DATABASE.md generation to the selected language implementation."""

from __future__ import annotations

from pathlib import Path

from drydock.database_apply import record_provenance
from drydock.database_contract import sqlite_schema_tables
from drydock.database_emit_python import PACKAGE, SHIPPED_MODULES, render_schema_module
from drydock.errors import SpecificationError
from drydock.technology_stack import declared_language


def write_persistence_package(
    blueprint_dir: Path, build_dir: Path, *, language: str | None = None
) -> tuple[Path, ...]:
    """Generate only declared persistence, using the Target's selected language.

    Records Drydock's provenance beside what it writes, so later verification knows the DATABASE
    step ran rather than inferring it from files a build agent can also write. The record is not
    returned: it is Drydock's, not part of the persistence contract a planner or builder reads.
    """
    path = blueprint_dir / "DATABASE.md"
    if not path.is_file():
        return ()
    text = path.read_text(encoding="utf-8")
    if not sqlite_schema_tables(text):
        return ()
    selected = language or declared_language(blueprint_dir.parent) or "python"
    if selected == "python":
        from drydock.database_emit_python import write_python_persistence

        written = write_python_persistence(blueprint_dir, build_dir)
    elif selected == "go":
        from drydock.database_emit_go import write_go_persistence

        written = write_go_persistence(text, build_dir)
    else:
        raise SpecificationError(f"No persistence generator for {selected!r}")
    if written:
        record_provenance(build_dir, written)
    return written


__all__ = ["PACKAGE", "SHIPPED_MODULES", "render_schema_module", "write_persistence_package"]
