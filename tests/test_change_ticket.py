from __future__ import annotations

import pytest

from drydock.change_ticket import (
    TicketBody,
    TicketHeader,
    changes_dir,
    next_ticket_number,
    parse_ticket_header,
    render_ticket,
    scope_clause,
    scope_for_delta,
    slugify_ticket_name,
    ticket_filename,
    ticket_version,
)
from drydock.errors import SpecificationError

_PARENT = """# DATABASE: Demo

| Field       | Value |
|-------------|-------|
| Version     | 20260806 V1 |
| Depends On  | ARCHITECTURE.md |

## Schema

Books are stored in a table.

## Operations

Insert, read, delete.
"""

_HAND_AUTHORED = """# CHANGE: Legacy Ticket

| Field       | Value |
|-------------|-------|
| Version     | 20260801 V1 |
| Description | Something a person wrote. |
| Amends      | DATABASE.md |
| Depends On  | DATABASE.md, ARCHITECTURE.md |

## Specification

Do the thing.
"""


def _header(**overrides) -> TicketHeader:
    values = {
        "version": "20260806 V1",
        "description": "Persist per-book read state.",
        "amends": "DATABASE.md",
        "depends_on": ("DATABASE.md", "ARCHITECTURE.md"),
        "scope": "additive",
        "origin": "reading-list.md@6e87e04",
        "created": "2026-08-06",
        "stories": ("mark-read-schema",),
    }
    values.update(overrides)
    return TicketHeader(**values)


def test_next_ticket_number_starts_at_one_without_a_changes_directory(tmp_path):
    assert next_ticket_number(tmp_path) == 1


def test_next_ticket_number_continues_past_existing_tickets(tmp_path):
    directory = changes_dir(tmp_path)
    directory.mkdir(parents=True)
    (directory / "TICKET-001-One.md").write_text("x", encoding="utf-8")
    (directory / "TICKET-007-Seven.md").write_text("x", encoding="utf-8")
    (directory / "notes.md").write_text("x", encoding="utf-8")

    assert next_ticket_number(tmp_path) == 8


def test_slugify_and_filename_follow_the_ticket_convention():
    assert slugify_ticket_name("mark a book read") == "Mark-A-Book-Read"
    assert slugify_ticket_name("!!!") == "Change"
    assert ticket_filename(7, "mark read") == "TICKET-007-Mark-Read.md"


def test_ticket_version_increments_only_within_the_same_day():
    assert ticket_version(None, "2026-08-06") == "20260806 V1"
    assert ticket_version(_HAND_AUTHORED, "2026-08-06") == "20260806 V1"
    same_day = _HAND_AUTHORED.replace("20260801 V1", "20260806 V1")
    assert ticket_version(same_day, "2026-08-06") == "20260806 V2"


def test_scope_for_delta_maps_added_to_additive():
    assert scope_for_delta("added") == "additive"
    assert scope_for_delta("changed") == "amending"
    assert scope_for_delta("removed") == "amending"
    assert scope_for_delta(None) == "amending"


def test_additive_scope_clause_supersedes_nothing():
    clause = scope_clause("additive", "DATABASE.md")

    assert "supersedes nothing" in clause
    assert "every assertion in DATABASE.md remains in force" in clause


def test_amending_scope_clause_names_only_its_sections():
    clause = scope_clause("amending", "DATABASE.md")

    assert "supersedes only the sections named" in clause
    assert "Amended Sections" in clause


def test_render_ticket_emits_the_normative_header_rows():
    text = render_ticket(
        _header(),
        name="Mark Read",
        body=TicketBody(
            summary="Persist read state.",
            specification="Add a read column.",
            requirements=(("mark-book-read", "The reader can mark a book as read."),),
        ),
    )

    assert text.startswith("# CHANGE: Mark Read\n")
    for row in (
        "| Version | 20260806 V1 |",
        "| Description | Persist per-book read state. |",
        "| Amends | DATABASE.md |",
        "| Depends On | DATABASE.md, ARCHITECTURE.md |",
        "| Scope | additive |",
        "| Origin | reading-list.md@6e87e04 |",
        "| Created | 2026-08-06 |",
        "| Stories | mark-read-schema |",
    ):
        assert row in text
    assert "> The reader can mark a book as read." in text
    assert text.endswith("\n")


def test_render_ticket_rejects_an_unknown_scope():
    with pytest.raises(SpecificationError, match="Unknown ticket scope"):
        render_ticket(_header(scope="whatever"), name="Mark Read", body=TicketBody())


def test_render_ticket_accepts_amended_sections_present_in_the_parent():
    text = render_ticket(
        _header(scope="amending"),
        name="Mark Read",
        body=TicketBody(specification="x", amended_sections=("Schema",)),
        parent_text=_PARENT,
    )

    assert "## Amended Sections" in text
    assert "- Schema" in text


def test_render_ticket_rejects_amended_sections_absent_from_the_parent():
    with pytest.raises(SpecificationError, match="absent from DATABASE.md"):
        render_ticket(
            _header(scope="amending"),
            name="Mark Read",
            body=TicketBody(specification="x", amended_sections=("Nonexistent",)),
            parent_text=_PARENT,
        )


def test_render_ticket_records_downstream_impact_without_blocking():
    text = render_ticket(
        _header(scope="amending"),
        name="Mark Read",
        body=TicketBody(specification="x", downstream_impact=("add-book consumes books table",)),
        parent_text=_PARENT,
    )

    assert "## Downstream Impact" in text
    assert "- add-book consumes books table" in text


def test_parse_ticket_header_round_trips_render_ticket():
    text = render_ticket(_header(), name="Mark Read", body=TicketBody(specification="x"))

    header = parse_ticket_header(text)

    assert header == _header()


def test_parse_ticket_header_reads_a_hand_authored_ticket_without_the_new_fields():
    header = parse_ticket_header(_HAND_AUTHORED)

    assert header.amends == "DATABASE.md"
    assert header.depends_on == ("DATABASE.md", "ARCHITECTURE.md")
    assert header.scope == "amending"
    assert header.stories == ()


def test_parse_ticket_header_returns_none_without_an_amends_row():
    assert parse_ticket_header("# CHANGE: Nothing\n\nNo table here.\n") is None
