"""Tests for foundation contracts published by Rigging files."""

from __future__ import annotations

import pytest

from drydock.rigging_contract import (
    APPLICATION_TIER,
    PLATFORM_ORDER,
    TIER_ORDER,
    chain_rank,
    contract_section,
    declared_kind,
    declared_tier,
    exclusivity_conflicts,
    foundation_contracts,
    foundation_kinds,
    import_defects,
    order_rigging,
    parse_contract,
    published_packages,
    sub_rank,
    tier_label,
    tier_number,
    tier_rank,
)

_FASTAPI = """# FastAPI Best Practices

**Version:** 20260521 V1
**Category:** Web Server
**Foundation:** web-server
**Tier:** platform
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


_PYTHON = """# Python Best Practices

**Version:** 20260920 V4
**Foundation:** language
**Tier:** language
**Category:** Language
**Description:** Python conventions.

---

## Foundation Contract

- source_root: ./
- test_command: pytest -q

---

## 1. Configuration

Prose.
"""


def test_a_foundation_file_publishes_its_shape():
    contract = parse_contract(_FASTAPI, filename="fastapi.md")

    assert contract is not None
    assert contract.kind == "web-server"
    assert contract.package == "app_server"
    assert contract.entry == "create_app() -> FastAPI"
    assert contract.entry_callable == "create_app"
    assert contract.fixture == "web_client"
    assert contract.fixture_source == "conftest.py"
    assert contract.tier == "platform"
    assert contract.shape == "api"


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


def test_a_language_publishes_the_environment_shape_not_an_api():
    """A language foundation has no package to import and no client to construct. Requiring the
    API trio of one is why `language` sat outside the foundation set while being the most
    exclusive choice a Target makes."""
    contract = parse_contract(_PYTHON, filename="python.md")

    assert contract is not None
    assert contract.kind == "language"
    assert contract.tier == "language"
    assert contract.shape == "environment"
    assert contract.source_root == "./"
    assert contract.test_command == "pytest -q"
    assert contract.package == ""


def test_a_contract_completing_neither_shape_is_an_authoring_error():
    text = _PYTHON.replace("- test_command: pytest -q\n", "")

    with pytest.raises(ValueError, match="missing: test_command"):
        parse_contract(text, filename="python.md")


def test_a_foundation_without_a_tier_cannot_be_ordered():
    text = _FASTAPI.replace("**Tier:** platform\n", "")

    with pytest.raises(ValueError, match="no \\*\\*Tier:\\*\\*"):
        parse_contract(text, filename="fastapi.md")


def test_declared_tier_is_read_from_the_header_block():
    assert declared_tier(_FASTAPI) == "platform"
    assert declared_tier(_ADDITIVE) is None


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

    assert {
        "fastapi.md",
        "flask.md",
        "django.md",
        "sqlite.md",
        "postgres.md",
        "cli.md",
        "python.md",
        "go.md",
        "typescript.md",
    } <= set(contracts)
    for name, contract in contracts.items():
        assert contract.kind, name
        assert contract.tier, name
        assert contract.section.startswith("## Foundation Contract"), name
        if contract.shape == "api":
            assert contract.package and contract.entry and contract.fixture, name
        else:
            assert contract.source_root and contract.test_command, name


def test_shipped_kinds_name_one_package_each():
    """Every web server builds app_server; every database builds persistence. The criterion author
    writes one name whichever framework the Commander picked."""
    by_kind: dict[str, set[str]] = {}
    for contract in foundation_contracts().values():
        by_kind.setdefault(contract.kind, set()).add(contract.package)

    assert by_kind["web-server"] == {"app_server"}
    assert by_kind["database"] == {"persistence"}
    assert by_kind["cli"] == {"cli"}
    assert by_kind["language"] == {""}  # a language publishes no importable package


# ── Tiers and build order ───────────────────────────────────────────────────────


def test_the_six_tiers_are_ordered_as_the_work_is_done():
    assert [tier_rank(name) for name in TIER_ORDER] == [0, 1, 2, 3, 4, 5]
    assert TIER_ORDER == (
        "language",
        "platform",
        "branding",
        "interface",
        "screen-foundation",
        "application",
    )
    assert [tier_number(name) for name in TIER_ORDER] == [1, 2, 3, 4, 5, 6]


def test_the_application_tier_is_where_an_undeclared_tier_lands():
    """Declaring no tier is not a missing answer: it is tier 6, claiming no order against peers."""
    assert tier_rank("") == tier_rank(APPLICATION_TIER)
    assert tier_rank("service") == tier_rank(APPLICATION_TIER)
    assert tier_number("") == 6
    assert tier_rank("") > tier_rank("screen-foundation")


def test_tier_two_sub_orders_its_three_independent_kinds():
    """Neither of the three is built into another, so the order is by what imports what."""
    assert PLATFORM_ORDER == ("database", "web-server", "cli")
    assert [sub_rank(kind) for kind in PLATFORM_ORDER] == [1, 2, 3]
    assert sub_rank("language") == 0
    assert tier_label("platform", "database") == "2.1"
    assert tier_label("platform", "cli") == "2.3"
    assert tier_label("language", "language") == "1"
    assert tier_label("") == "6"


def test_chain_rank_orders_the_whole_foundation():
    chain = [
        chain_rank("language", "language"),
        chain_rank("platform", "database"),
        chain_rank("platform", "web-server"),
        chain_rank("platform", "cli"),
        chain_rank("branding", "branding"),
        chain_rank("interface", "interface"),
        chain_rank("screen-foundation", "screen-foundation"),
        chain_rank("", ""),
    ]

    assert chain == sorted(chain)
    assert len(set(chain)) == len(chain)


def test_shipped_rigging_orders_the_whole_chain():
    """bootstrap5.md and BRANDING_MAIN.md are the question this answers: neither is a foundation,
    but both carry an ordering claim — the palette before the shell, the shell before a screen.
    uv_ruff.md declares no tier and so claims nothing."""
    ordered = order_rigging([
        "ui-flask.bootstrap-client.md",
        "uv_ruff.md",
        "bootstrap5.md",
        "BRANDING_MAIN.md",
        "fastapi.md",
        "python.md",
    ])

    assert ordered == [
        "python.md",
        "fastapi.md",
        "BRANDING_MAIN.md",
        "bootstrap5.md",
        "ui-flask.bootstrap-client.md",
        "uv_ruff.md",
    ]


def test_foundation_kinds_lead_with_the_language():
    kinds = [kind for _layer, kind, _options in foundation_kinds()]

    assert kinds[0] == "language"
    assert set(kinds[1:]) == {"web-server", "database", "cli"}


def test_two_languages_conflict_exactly_as_two_web_servers_do():
    assert exclusivity_conflicts(["python.md", "go.md"]) == {"language": ["go.md", "python.md"]}


# ── Unknown packages ────────────────────────────────────────────────────────────


def test_published_packages_are_reserved_across_every_web_server():
    packages = published_packages()

    assert {"app_server", "persistence", "cli"} <= set(packages)
    assert {c.filename for c in packages["app_server"]} == {
        "django.md",
        "fastapi.md",
        "flask.md",
    }


def _imports(code: str):
    from drydock.acceptance import imported_modules

    return imported_modules(code)


def test_importing_a_package_no_selected_foundation_publishes_is_refused():
    defects = import_defects(_imports("import persistence\n"), ["fastapi.md", "python.md"])

    assert len(defects) == 1
    assert "selects no database" in defects[0]


def test_importing_the_entry_from_the_wrong_package_is_refused():
    """The Marina_Luna defect exactly: 98 imports of `app`, 77 of `marina_app`, all of
    `create_app`, against a foundation that publishes it in `app_server`."""
    defects = import_defects(_imports("from marina_app import create_app\n"), ["fastapi.md"])

    assert len(defects) == 1
    assert "`app_server`" in defects[0]
    assert "fastapi.md" in defects[0]


def test_the_entry_module_is_the_one_the_contract_imports_from():
    contracts = foundation_contracts()

    assert contracts["fastapi.md"].entry_module == "app_server.main"
    assert contracts["flask.md"].entry_module == "app_server"


def test_the_published_names_verify_clean():
    code = "from app_server.main import create_app\nimport persistence\nimport json\n"

    assert import_defects(_imports(code), ["fastapi.md", "sqlite.md"]) == []


def test_an_ordinary_third_party_import_is_never_judged():
    """Whether `requests` resolves is a fact about the build environment, not the Blueprint.
    Guessing at it refuses working plans, which is how the retracted analyzers failed."""
    code = "import requests\nimport pytest\nfrom mypackage.util import helper\n"

    assert import_defects(_imports(code), ["fastapi.md"]) == []


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
