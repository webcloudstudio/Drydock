"""Tests for foundation contracts published by Rigging files."""

from __future__ import annotations

import pytest

from drydock.rigging_contract import (
    contract_section,
    declared_kind,
    exclusivity_conflicts,
    foundation_contracts,
    parse_contract,
)

_FASTAPI = """# FastAPI Best Practices

**Version:** 20260521 V1
**Category:** Web Server
**Foundation:** web-server
**Description:** FastAPI patterns.

---

## Foundation Contract

- package: app_server
- entry: create_app() -> FastAPI
- fixture: web_client
- fixture_source: conftest.py

```python
def create_app() -> FastAPI: ...
```

---

## 1. Directory Layout

Prose the compactor may shorten.
"""

_ADDITIVE = """# SQLAlchemy

**Version:** 20260919 V1
**Category:** Persistence
**Description:** ORM guidance selected alongside a database, never instead of one.

Prose.
"""


def test_a_file_declaring_no_foundation_publishes_no_contract():
    """Most Rigging is additive. sqlalchemy.md and alembic.md sit beside the one database."""
    assert declared_kind(_ADDITIVE) is None
    assert parse_contract(_ADDITIVE, filename="sqlalchemy.md") is None


def test_a_foundation_file_publishes_its_shape():
    contract = parse_contract(_FASTAPI, filename="fastapi.md")

    assert contract is not None
    assert contract.kind == "web-server"
    assert contract.package == "app_server"
    assert contract.entry == "create_app() -> FastAPI"
    assert contract.entry_callable == "create_app"
    assert contract.fixture == "web_client"
    assert contract.fixture_source == "conftest.py"


def test_the_section_is_captured_verbatim_and_stops_at_the_next_heading():
    section = contract_section(_FASTAPI)

    assert section is not None
    assert section.startswith("## Foundation Contract")
    assert "package: app_server" in section
    assert "Directory Layout" not in section


def test_declaring_a_kind_without_a_contract_is_an_authoring_error():
    """Drydock's own Rigging failing loudly beats a Target inheriting a half-written contract."""
    text = _FASTAPI.replace("## Foundation Contract", "## Something Else")

    with pytest.raises(ValueError, match="no '## Foundation Contract' section"):
        parse_contract(text, filename="fastapi.md")


def test_a_contract_missing_a_required_field_is_an_authoring_error():
    text = _FASTAPI.replace("- fixture: web_client\n", "")

    with pytest.raises(ValueError, match="missing: fixture"):
        parse_contract(text, filename="fastapi.md")


def test_two_files_of_one_kind_conflict():
    """FastAPI and Flask are two application shapes in one build tree, not a richer stack."""
    assert exclusivity_conflicts(["fastapi.md", "flask.md"]) == {
        "web-server": ["fastapi.md", "flask.md"]
    }


def test_one_of_each_kind_plus_additive_files_is_clean():
    assert exclusivity_conflicts(["fastapi.md", "sqlite.md", "sqlalchemy.md", "alembic.md"]) == {}


def test_every_shipped_foundation_file_publishes_a_complete_contract():
    """A shipped Rigging file that declares a kind must be usable; this is the guard on authoring."""
    contracts = foundation_contracts()

    assert {"fastapi.md", "flask.md", "django.md", "sqlite.md", "postgres.md", "cli.md"} <= set(
        contracts
    )
    for name, contract in contracts.items():
        assert contract.kind, name
        assert contract.package, name
        assert contract.entry, name
        assert contract.fixture, name
        assert contract.section.startswith("## Foundation Contract"), name


def test_shipped_kinds_name_one_package_each():
    """Every web server builds app_server; every database builds persistence. The criterion author
    writes one name whichever framework the Commander picked."""
    by_kind: dict[str, set[str]] = {}
    for contract in foundation_contracts().values():
        by_kind.setdefault(contract.kind, set()).add(contract.package)

    assert by_kind["web-server"] == {"app_server"}
    assert by_kind["database"] == {"persistence"}
    assert by_kind["cli"] == {"cli"}


# ── Compaction splice ───────────────────────────────────────────────────────────


def test_compaction_withholds_the_contract_from_the_model_and_splices_it_back():
    """Compaction shortens prose. A shortened contract is a changed contract, so the model never
    sees it: it is cut before assembly and re-inserted verbatim afterwards."""
    from drydock.rigging_compact import _finalize, _split_foundation_contract

    model_text, contract = _split_foundation_contract(_FASTAPI)

    assert contract is not None
    assert "## Foundation Contract" not in model_text
    assert "package: app_server" not in model_text
    assert "Directory Layout" in model_text

    out = _finalize(
        "# FastAPI — Usage Surface\n\ncompacted prose",
        rel_source="stack/fastapi.md",
        today="2026-09-20",
        source_sha="abc123",
        contract=contract,
    )

    assert contract.strip() in out
    assert "compacted prose" in out


def test_a_model_that_returns_garbage_still_yields_an_intact_contract():
    """The splice is a guarantee, not a request: the contract does not depend on the model."""
    from drydock.rigging_compact import _finalize, _split_foundation_contract

    _, contract = _split_foundation_contract(_FASTAPI)
    out = _finalize(
        "lorem ipsum", rel_source="s.md", today="2026-09-20", source_sha="x", contract=contract
    )

    assert "- package: app_server" in out
    assert "- entry: create_app() -> FastAPI" in out
    assert "- fixture: web_client" in out


def test_a_file_with_no_contract_compacts_unchanged():
    from drydock.rigging_compact import _finalize, _split_foundation_contract

    model_text, contract = _split_foundation_contract(_ADDITIVE)

    assert contract is None
    assert model_text == _ADDITIVE
    out = _finalize("surface", rel_source="s.md", today="2026-09-20", source_sha="x", contract=None)
    assert "Foundation Contract" not in out
