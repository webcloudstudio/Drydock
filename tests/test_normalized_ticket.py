from __future__ import annotations

from datetime import UTC, datetime

import pytest

from drydock.errors import SpecificationError
from drydock.normalized_ticket import (
    parse_normalized_ticket,
    render_normalized_ticket,
    split_front_matter,
)


def test_split_front_matter_preserves_unknown_fields():
    parsed = split_front_matter("---\nissue_key: OPS-481\nlabels: ui\n---\n\nAdd a button.\n")
    assert parsed.fields == {"issue_key": "OPS-481", "labels": "ui"}
    assert parsed.body.strip() == "Add a button."


def test_render_preserves_source_front_matter_and_adds_drydock_namespace(tmp_path):
    source = tmp_path / "OPS-481.md"
    text = "---\nissue_key: OPS-481\nsummary: Add order status\n---\n\nReturn status.\n"
    rendered = render_normalized_ticket(
        source,
        text,
        ticket_id="TICKET-001",
        amends="FEATURE-Order.md#Database-Interface",
        now=datetime(2026, 9, 12, 18, 0, tzinfo=UTC),
    )
    output = tmp_path / "TICKET-001-Add-Order-Status.md"
    output.write_text(rendered, encoding="utf-8")
    normalized = parse_normalized_ticket(output)
    assert normalized is not None
    assert normalized.drydock_fields["drydock_parent"] == "OPS-481"
    assert normalized.amends == "FEATURE-Order.md#Database-Interface"
    assert "issue_key: OPS-481" in rendered
    assert "drydock_id: TICKET-001" in rendered
    assert "## Source Evidence" in rendered


def test_source_ticket_using_reserved_namespace_is_rejected(tmp_path):
    with pytest.raises(SpecificationError, match="reserved Drydock fields"):
        render_normalized_ticket(
            tmp_path / "source.md",
            "---\ndrydock_id: upstream-value\n---\n\nChange.\n",
            ticket_id="TICKET-001",
            amends="FEATURE-Order.md",
        )


def test_database_access_pattern_requires_compatibility(tmp_path):
    with pytest.raises(SpecificationError, match="require a valid compatibility"):
        render_normalized_ticket(
            tmp_path / "source.md",
            "Change.",
            ticket_id="TICKET-001",
            amends="DATABASE.md#Access-Patterns",
            kind="database-access-pattern",
        )
