from pathlib import Path

import pytest

from drydock.database_contract import (
    create_ticket_migration_records,
    mark_migrations_built,
    migration_records,
    parse_database_contract,
    parse_database_interface,
    staged_operation_ids,
    validate_database_interfaces,
)
from drydock.errors import SpecificationError

_DATABASE = """# DATABASE: Orders

## Access Patterns

### FEATURE-ORDER-001 — Create order

| Field | Value |
|---|---|
| Owner | FEATURE-Order.md |
| Access | write |
| Repository operation | OrderRepository.create(CreateOrder) -> Order |
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
| Repository operation | OrderRepository.get(UUID) -> Order |
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


def test_parses_typed_feature_owned_access_pattern():
    contract = parse_database_contract(_DATABASE)

    pattern = contract.by_id()["FEATURE-ORDER-001"]
    assert pattern.owner == "FEATURE-Order.md"
    assert pattern.access == "write"
    assert {field.name for field in pattern.inputs if field.required} == {"customer_id", "items"}
    assert [field.name for field in pattern.outputs] == ["id", "status"]


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
