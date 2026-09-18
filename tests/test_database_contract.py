from pathlib import Path

import pytest

from drydock.database_contract import (
    changed_operation_ids_since,
    create_ticket_migration_records,
    database_operation_fingerprints,
    mark_migrations_built,
    migration_records,
    parse_database_contract,
    parse_database_interface,
    sqlite_schema_sql,
    sqlite_schema_tables,
    staged_operation_ids,
    validate_database_interfaces,
    validate_sqlite_schema,
)
from drydock.errors import SpecificationError

_DATABASE = """# DATABASE: Orders

## Access Patterns

### FEATURE-ORDER-001 — Create order

| Field | Value |
|---|---|
| Owner | FEATURE-Order.md |
| Access | write |
| Repository operation | `orders.create` |
| Compatibility | rebuild |

Input: CreateOrder

| Field | Type | Required |
|---|---|---|
| customer_id | UUID | yes |
| items | list[OrderItem] | yes |

Output: Order

| Field | Type |
|---|---|
| id | UUID |
| status | OrderStatus |

### FEATURE-ORDER-002 — Find order

| Field | Value |
|---|---|
| Owner | FEATURE-Order.md |
| Access | read |
| Repository operation | `orders.get` |
| Compatibility | data |

Input: FindOrder

| Field | Type | Required |
|---|---|---|
| order_id | UUID | yes |

Output: Order

| Field | Type |
|---|---|
| id | UUID |
| status | OrderStatus |
"""


_INTERFACE = """# FEATURE: Order

## Database Interface

- `FEATURE-ORDER-001` — write: create an order - supplies: `customer_id`, `items` - returns: `id`, `status`
"""


_SQLITE_SCHEMA = """# DATABASE: Registry

## `settings`

| Field | Type | Notes |
|---|---|---|
| key | TEXT PK | Setting name |
| value | TEXT | Serialized value |

## `projects`

| Field | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| name | TEXT | Display name |
| archived | INTEGER | Boolean |
"""


def test_parses_typed_feature_owned_access_pattern():
    contract = parse_database_contract(_DATABASE)

    pattern = contract.by_id()["FEATURE-ORDER-001"]
    assert pattern.owner == "FEATURE-Order.md"
    assert pattern.access == "write"
    assert {field.name for field in pattern.inputs if field.required} == {"customer_id", "items"}
    assert [field.name for field in pattern.outputs] == ["id", "status"]


def test_sqlite_schema_invariant_creates_and_connects_declared_tables():
    tables = validate_sqlite_schema(_SQLITE_SCHEMA)

    assert [table.name for table in tables] == ["settings", "projects"]
    assert 'CREATE TABLE IF NOT EXISTS "settings"' in sqlite_schema_sql(tables)


def test_sqlite_schema_rejects_duplicate_columns():
    duplicate = _SQLITE_SCHEMA.replace(
        "| value | TEXT | Serialized value |", "| key | TEXT | Again |"
    )

    with pytest.raises(SpecificationError, match="more than once"):
        sqlite_schema_tables(duplicate)


def test_interface_validates_owner_access_and_fields():
    contract = parse_database_contract(_DATABASE)
    use = parse_database_interface(_INTERFACE, source="FEATURE-Order.md")

    validate_database_interfaces(contract, {"FEATURE-Order.md": use})


def test_interface_cannot_escape_repository_contract():
    contract = parse_database_contract(_DATABASE)
    interface = _INTERFACE.replace("`id`, `status`", "`id`, `table_name`")

    with pytest.raises(SpecificationError, match="undeclared field"):
        validate_database_interfaces(
            contract,
            {"FEATURE-Order.md": parse_database_interface(interface)},
        )


def test_interface_requires_each_declared_required_input():
    contract = parse_database_contract(_DATABASE)
    interface = _INTERFACE.replace("`customer_id`, `items`", "`customer_id`")

    with pytest.raises(SpecificationError, match="omits required field"):
        validate_database_interfaces(
            contract,
            {"FEATURE-Order.md": parse_database_interface(interface)},
        )


def test_migration_ledger_advances_only_from_planned(tmp_path: Path):
    ledger = tmp_path / "migrations"
    ledger.mkdir()
    path = ledger / "MIGRATION-FEATURE-ORDER-001.md"
    path.write_text(
        """# Migration: FEATURE-ORDER-001

| Field | Value |
|---|---|
| Access Pattern | FEATURE-ORDER-001 |
| Revision | add_orders |
| Compatibility | rebuild |
| State | planned |

## Upgrade

```python
op.create_table("orders")
```

## Downgrade

```python
op.drop_table("orders")
```
""",
        encoding="utf-8",
    )

    assert staged_operation_ids(tmp_path) == ("FEATURE-ORDER-001",)
    assert mark_migrations_built(tmp_path) == (path,)
    assert migration_records(tmp_path)[0].state == "built"
    assert staged_operation_ids(tmp_path) == ()


def test_database_ticket_creates_a_planned_migration_ledger_record(tmp_path: Path):
    (tmp_path / "DATABASE.md").write_text(_DATABASE, encoding="utf-8")

    created = create_ticket_migration_records(
        tmp_path,
        ["Change FEATURE-ORDER-001 to add a required status field."],
    )

    assert [path.name for path in created] == ["MIGRATION-FEATURE-ORDER-001.md"]
    record = migration_records(tmp_path)[0]
    assert record.access_pattern == "FEATURE-ORDER-001"
    assert record.compatibility == "rebuild"
    assert record.state == "planned"


def test_public_contract_fingerprint_excludes_private_database_sections():
    private_edit = _DATABASE + "\n## Schemas\n\norders gains a private audit column.\n"
    assert database_operation_fingerprints(_DATABASE) == database_operation_fingerprints(
        private_edit
    )
    changed_contract = _DATABASE.replace("orders.create", "orders.create_v2")
    assert database_operation_fingerprints(_DATABASE) != database_operation_fingerprints(
        changed_contract
    )


def test_each_normalized_database_ticket_has_its_own_migration_record(tmp_path: Path):
    (tmp_path / "DATABASE.md").write_text(_DATABASE, encoding="utf-8")
    first = tmp_path / "TICKET-001.md"
    second = tmp_path / "TICKET-002.md"
    for path, ticket_id in ((first, "TICKET-001"), (second, "TICKET-002")):
        path.write_text(
            f"---\ndrydock_id: {ticket_id}\ndrydock_kind: database-access-pattern\n"
            "drydock_compatibility: rebuild\n---\n\nFEATURE-ORDER-001\n",
            encoding="utf-8",
        )

    created = create_ticket_migration_records(tmp_path, (first, second))

    assert [path.name for path in created] == [
        "MIGRATION-TICKET-001-FEATURE-ORDER-001.md",
        "MIGRATION-TICKET-002-FEATURE-ORDER-001.md",
    ]


def test_database_ticket_amends_scope_prevents_unrelated_operation_migrations(tmp_path: Path):
    (tmp_path / "DATABASE.md").write_text(_DATABASE, encoding="utf-8")
    ticket = tmp_path / "TICKET-001.md"
    ticket.write_text(
        "---\ndrydock_id: TICKET-001\ndrydock_kind: database-access-pattern\n"
        "drydock_compatibility: rebuild\n"
        "drydock_amends: DATABASE.md#Access-Patterns/FEATURE-ORDER-001\n---\n\n" + _DATABASE,
        encoding="utf-8",
    )

    created = create_ticket_migration_records(tmp_path, (ticket,))

    assert [path.name for path in created] == ["MIGRATION-TICKET-001-FEATURE-ORDER-001.md"]


def test_git_contract_diff_names_only_changed_operations(tmp_path: Path):
    import subprocess

    blueprint = tmp_path / "blueprint"
    blueprint.mkdir()
    database = blueprint / "DATABASE.md"
    database.write_text(_DATABASE, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "blueprint/DATABASE.md"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "database",
        ],
        check=True,
    )
    baseline = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    database.write_text(
        _DATABASE.replace("| Compatibility | rebuild |", "| Compatibility | data |", 1),
        encoding="utf-8",
    )

    assert changed_operation_ids_since(blueprint, baseline) == ("FEATURE-ORDER-001",)


def test_a_combined_repository_surface_declares_read_write():
    """``settings.get``/``set``/``delete`` is one repository surface. Forcing it into two patterns
    invents a split the declaration never intended, so ``read-write`` is a declared level."""
    contract = parse_database_contract(
        _DATABASE.replace("| Access | write |", "| Access | read-write |")
    )

    assert contract.by_id()["FEATURE-ORDER-001"].access == "read-write"


def test_a_citation_may_claim_less_access_than_the_pattern_grants():
    """A read-only consumer of a read-write surface is a real and useful claim."""
    contract = parse_database_contract(
        _DATABASE.replace("| Access | write |", "| Access | read-write |")
    )

    for claimed in ("read", "write", "read-write"):
        use = parse_database_interface(
            _INTERFACE.replace("— write:", f"— {claimed}:"), source="FEATURE-Order.md"
        )
        validate_database_interfaces(contract, {"FEATURE-Order.md": use})


def test_a_citation_may_never_claim_more_access_than_the_pattern_grants():
    contract = parse_database_contract(_DATABASE)
    use = parse_database_interface(
        _INTERFACE.replace("— write:", "— read-write:"), source="FEATURE-Order.md"
    )

    with pytest.raises(SpecificationError, match="which write does not grant"):
        validate_database_interfaces(contract, {"FEATURE-Order.md": use})


def test_a_blueprint_that_reaches_no_repository_declares_none():
    """A Screen that delegates persistence must be able to say so without failing the plan."""
    interface = _INTERFACE.replace(
        "- `FEATURE-ORDER-001` — write: create an order"
        " - supplies: `customer_id`, `items` - returns: `id`, `status`",
        "- None — persistence is owned by FEATURE-Order.md.",
    )

    assert parse_database_interface(interface, source="SCREEN-Orders.md") == ()


def test_prose_in_the_interface_section_names_the_line_and_the_accepted_form():
    interface = _INTERFACE.replace(
        "- `FEATURE-ORDER-001` — write: create an order"
        " - supplies: `customer_id`, `items` - returns: `id`, `status`",
        "- **Orders** — Read and write through the order repository declared by DATABASE.md.",
    )

    with pytest.raises(SpecificationError) as excinfo:
        parse_database_interface(interface, source="FEATURE-Order.md")
    message = str(excinfo.value)
    assert "**Orders**" in message
    assert "supplies:" in message
    assert "- None" in message


def test_every_bullet_must_parse_not_merely_one_of_them():
    """One well-formed citation must not license prose beside it."""
    interface = _INTERFACE + "- The remaining state lives in the session, not the database.\n"

    with pytest.raises(SpecificationError, match="malformed ## Database Interface entry"):
        parse_database_interface(interface, source="FEATURE-Order.md")


def test_none_cannot_be_declared_beside_a_citation():
    interface = _INTERFACE + "- None — nothing else is persisted.\n"

    with pytest.raises(SpecificationError, match="declares None and also cites"):
        parse_database_interface(interface, source="FEATURE-Order.md")
