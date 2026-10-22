"""The persistence declaration accumulates; it never shrinks."""

from __future__ import annotations

from pathlib import Path

import pytest

from drydock.database_schema import (
    DATABASE_BLOCK,
    declared_table_names,
    merge_schema,
    merge_seeded_schema,
    seed_blueprint,
    strip_examples,
    table_sections,
)
from drydock.errors import SpecificationError

BASE = """# DATABASE: Registry

## Access Patterns

### FEATURE-ITEMS-001 — Create item

| Field | Value |
|-------|-------|
| Owner | FEATURE-Items.md |

## Schemas

## `local_checkouts`

Discovered working copies.

| Field | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| path | TEXT | location |

## Guardrails

- None.
"""


def test_a_new_column_is_appended_to_the_table_already_declared():
    addition = """## `local_checkouts`

| Field | Type | Notes |
|--------|------|-------|
| registered | INTEGER | Boolean |
"""

    merged = merge_schema(BASE, addition)

    section = next(item for item in table_sections(merged) if item.name == "local_checkouts")
    assert section.column_names() == ("id", "path", "registered")
    assert "| registered | INTEGER | Boolean |" in merged
    assert "Discovered working copies." in merged


def test_a_held_column_is_never_retyped_reordered_or_removed():
    # The failure this module exists to prevent: a pass restates a table it does not fully hold.
    lossy = """## `local_checkouts`

| Field | Type | Notes |
|--------|------|-------|
| path | BLOB | wrong type, wrong order |
"""

    merged = merge_schema(BASE, lossy)

    section = next(item for item in table_sections(merged) if item.name == "local_checkouts")
    assert section.column_names() == ("id", "path")
    assert "| path | TEXT | location |" in merged
    assert "BLOB" not in merged


def test_a_new_table_lands_before_the_typed_trailer():
    addition = """## `tags`

| Field | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
"""

    merged = merge_schema(BASE, addition)

    assert declared_table_names(merged) == ("local_checkouts", "tags")
    assert merged.index("## `tags`") < merged.index("## Guardrails")


def test_a_first_table_lands_under_the_schemas_heading():
    empty = "# DATABASE: X\n\n## Schemas\n\n## Migrations\n\n- None.\n"
    addition = "## `tags`\n\n| Field | Type | Notes |\n|---|---|---|\n| id | INTEGER PK | |\n"

    merged = merge_schema(empty, addition)

    assert merged.index("## `tags`") < merged.index("## Migrations")


def test_an_unnamed_operation_is_appended_and_a_held_one_is_left_alone():
    addition = """## Access Patterns

### FEATURE-ITEMS-001 — Create item

restated and wrong

### FEATURE-TAGS-002 — List tags

| Field | Value |
|-------|-------|
| Owner | FEATURE-Tags.md |
"""

    merged = merge_schema(BASE, addition)

    assert "restated and wrong" not in merged
    assert "| Owner | FEATURE-Items.md |" in merged
    assert "### FEATURE-TAGS-002 — List tags" in merged
    assert merged.index("FEATURE-ITEMS-001") < merged.index("FEATURE-TAGS-002")


def test_an_empty_addition_changes_nothing():
    assert merge_schema(BASE, "") == BASE
    assert merge_schema(BASE, "## Notes\n\nprose only\n") == BASE


def test_the_seed_carries_the_input_specification_and_drops_the_template_examples():
    template = (Path(__file__).parents[1] / "Rigging" / "spec_template" / DATABASE_BLOCK).read_text(
        encoding="utf-8"
    )
    source = """# Database: Registry

## `settings`

| Field | Type | Notes |
|--------|------|-------|
| key | TEXT PK | |
| value | TEXT | |
"""

    seeded = seed_blueprint(template, source)

    assert declared_table_names(seeded) == ("settings",)
    assert "FEATURE-EXAMPLE-001" not in seeded
    assert "| created_at | TEXT | timestamp |" not in seeded
    assert "## Access Patterns" in seeded
    assert "## Guardrails" in seeded


def test_the_seed_refuses_an_input_declaring_a_type_sqlite_cannot_build():
    template = "# DATABASE: X\n\n## Schemas\n\n## Guardrails\n\n- None.\n"
    source = "## `t`\n\n| Field | Type | Notes |\n|---|---|---|\n| id | UUID | |\n"

    with pytest.raises(SpecificationError):
        seed_blueprint(template, source)


def test_strip_examples_leaves_a_document_without_markers_untouched():
    assert strip_examples(BASE) == BASE


def test_seed_merge_restores_columns_and_composite_constraints():
    from drydock.database_contract import sqlite_schema_tables

    seed = BASE.replace("## Guardrails", "- UNIQUE (id, path)\n- INDEX (path, id)\n\n## Guardrails")
    authored = BASE.replace("| path | TEXT | location |\n", "")
    merged = merge_seeded_schema(authored, seed)

    assert sqlite_schema_tables(merged) == sqlite_schema_tables(seed)
    assert merge_seeded_schema(merged, seed) == merged


@pytest.mark.parametrize("replacement", ["INTEGER", "TEXT NOT NULL", "TEXT UNIQUE"])
def test_seed_merge_refuses_a_changed_source_column(replacement):
    authored = BASE.replace("| path | TEXT |", f"| path | {replacement} |")

    with pytest.raises(SpecificationError, match="local_checkouts.path changes its seeded"):
        merge_seeded_schema(authored, BASE)


def test_compact_preserves_the_executable_database_contract():
    from drydock.database_contract import sqlite_schema_tables
    from drydock.database_schema import compact_declaration

    source = BASE + "\n<!-- Authoring guidance. -->\n"
    compact = compact_declaration(source)
    assert "Authoring guidance" not in compact
    assert sqlite_schema_tables(compact) == sqlite_schema_tables(source)
