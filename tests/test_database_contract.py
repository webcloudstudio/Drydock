from pathlib import Path

import pytest

from drydock.database_contract import (
    changed_operation_ids_since,
    create_ticket_migration_records,
    database_operation_fingerprints,
    derived_indexes,
    mark_migrations_built,
    migration_records,
    parse_database_contract,
    parse_database_interface,
    schema_sql,
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
    changed_contract = _DATABASE.replace("orders.create", "orders.update")
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


_COLUMN_GRAMMAR = """# DATABASE: Grammar

## `projects`

| Field | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| name | VARCHAR(80) NOT NULL UNIQUE | |
| status | TEXT NOT NULL DEFAULT 'active' | |
| created_at | TEXT DEFAULT CURRENT_TIMESTAMP | |

## `tickets`

| Field | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| project_id | INTEGER NOT NULL REFERENCES projects(id) | |
| title | VARCHAR(200) NOT NULL | |
| opened_on | TEXT | |

- UNIQUE (project_id, title)
- INDEX (project_id, opened_on)
"""


def test_column_grammar_renders_every_declared_constraint():
    tables = validate_sqlite_schema(_COLUMN_GRAMMAR)
    sql = sqlite_schema_sql(tables)

    assert '"name" VARCHAR(80) NOT NULL UNIQUE' in sql
    assert "\"status\" TEXT NOT NULL DEFAULT 'active'" in sql
    assert '"created_at" TEXT DEFAULT CURRENT_TIMESTAMP' in sql
    assert '"project_id" INTEGER NOT NULL REFERENCES "projects"("id")' in sql
    assert 'UNIQUE ("project_id", "title")' in sql
    assert 'CREATE INDEX IF NOT EXISTS "tickets_project_id_opened_on_idx"' in sql


def test_a_referenced_table_is_created_before_the_table_citing_it():
    reversed_order = _COLUMN_GRAMMAR.replace("# DATABASE: Grammar\n", "")
    head, _, tail = reversed_order.partition("## `tickets`")
    tables = sqlite_schema_tables("# DATABASE: Grammar\n\n## `tickets`" + tail + "\n" + head)
    sql = sqlite_schema_sql(tables)

    assert sql.index('CREATE TABLE IF NOT EXISTS "projects"') < sql.index(
        'CREATE TABLE IF NOT EXISTS "tickets"'
    )


def test_a_foreign_key_to_an_undeclared_table_fails():
    orphan = _COLUMN_GRAMMAR.replace("REFERENCES projects(id)", "REFERENCES clients(id)")

    with pytest.raises(SpecificationError, match="references table 'clients'"):
        sqlite_schema_tables(orphan)


def test_a_foreign_key_to_an_undeclared_column_fails():
    orphan = _COLUMN_GRAMMAR.replace("REFERENCES projects(id)", "REFERENCES projects(slug)")

    with pytest.raises(SpecificationError, match="which projects does not declare"):
        sqlite_schema_tables(orphan)


def test_a_foreign_key_cycle_is_named_rather_than_rendered():
    cyclic = _COLUMN_GRAMMAR.replace(
        "| opened_on | TEXT | |", "| opened_on | TEXT | |\n| owner_id | INTEGER | |"
    ).replace(
        "| created_at | TEXT DEFAULT CURRENT_TIMESTAMP | |",
        "| created_at | TEXT | |\n| lead_ticket | INTEGER REFERENCES tickets(id) | |",
    )

    with pytest.raises(SpecificationError, match="foreign keys form a cycle"):
        sqlite_schema_sql(sqlite_schema_tables(cyclic))


def test_an_unknown_column_modifier_names_the_accepted_form():
    bogus = _COLUMN_GRAMMAR.replace(
        "| title | VARCHAR(200) NOT NULL |", "| title | VARCHAR(200) AUTOINCREMENT |"
    )

    with pytest.raises(SpecificationError, match="unknown column modifier.*VARCHAR\\(<n>\\)"):
        sqlite_schema_tables(bogus)


def test_blob_is_no_longer_a_declarable_type():
    blob = _COLUMN_GRAMMAR.replace("| opened_on | TEXT | |", "| payload | BLOB | |")

    with pytest.raises(SpecificationError, match="unsupported type 'BLOB'"):
        sqlite_schema_tables(blob)


def test_an_unquoted_default_literal_is_refused():
    injected = _COLUMN_GRAMMAR.replace("DEFAULT 'active'", "DEFAULT active")

    with pytest.raises(SpecificationError, match="unreadable DEFAULT value"):
        sqlite_schema_tables(injected)


def test_a_composite_constraint_over_an_undeclared_column_fails():
    bogus = _COLUMN_GRAMMAR.replace("- UNIQUE (project_id, title)", "- UNIQUE (project_id, slug)")

    with pytest.raises(SpecificationError, match="constrains undeclared column"):
        sqlite_schema_tables(bogus)


def test_a_single_column_composite_constraint_is_refused():
    single = _COLUMN_GRAMMAR.replace("- UNIQUE (project_id, title)", "- UNIQUE (title)")

    with pytest.raises(SpecificationError, match="composite UNIQUE over 1 column"):
        sqlite_schema_tables(single)


def test_one_access_pattern_declares_one_repository_operation():
    paired = _DATABASE.replace("| `orders.create` |", "| `orders.create`, `orders.update` |")

    with pytest.raises(SpecificationError, match="names 2 repository operations"):
        parse_database_contract(paired)


def test_a_verb_outside_the_closed_set_is_refused():
    invented = _DATABASE.replace("| `orders.create` |", "| `orders.archive` |")

    with pytest.raises(SpecificationError, match="get, list, create, update, delete"):
        parse_database_contract(invented)


_DERIVATION = """# DATABASE: Derivation

## Access Patterns

### FEATURE-TICKET-001 — Find tickets

| Field | Value |
|---|---|
| Owner | FEATURE-Ticket.md |
| Access | read |
| Repository operation | `tickets.list` |
| Compatibility | unchanged |

Input: FindTickets

| Field | Type | Required |
|---|---|---|
| status | str | yes |
| ignored_by_schema | str | no |

Output: Ticket

| Field | Type |
|---|---|
| id | int |

### FEATURE-TICKET-002 — Save ticket

| Field | Value |
|---|---|
| Owner | FEATURE-Ticket.md |
| Access | write |
| Repository operation | `tickets.update` |
| Compatibility | unchanged |

Input: SaveTicket

| Field | Type | Required |
|---|---|---|
| title | str | yes |

Output: Ticket

| Field | Type |
|---|---|
| id | int |

## `projects`

| Field | Type | Notes |
|---|---|---|
| id | INTEGER PK | |

## `tickets`

| Field | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| project_id | INTEGER NOT NULL REFERENCES projects(id) | |
| status | TEXT NOT NULL | |
| title | VARCHAR(200) | |
"""


def test_indexes_are_derived_from_foreign_keys_and_read_predicates():
    tables = sqlite_schema_tables(_DERIVATION)
    contract = parse_database_contract(_DERIVATION)

    assert derived_indexes(tables, contract) == (
        ("tickets", ("project_id",)),
        ("tickets", ("status",)),
    )


def test_a_write_pattern_contributes_no_index():
    sql = schema_sql(_DERIVATION)

    assert '"tickets_title_idx"' not in sql


def test_a_derived_index_is_not_repeated_when_already_declared():
    declared = _DERIVATION.replace(
        "| status | TEXT NOT NULL | |", "| status | TEXT NOT NULL UNIQUE | |"
    )
    tables = sqlite_schema_tables(declared)

    assert ("tickets", ("status",)) not in derived_indexes(
        tables, parse_database_contract(declared)
    )


def test_the_rendered_schema_creates_tables_and_indexes_on_sqlite():
    import sqlite3

    with sqlite3.connect(":memory:") as connection:
        connection.executescript(schema_sql(_DERIVATION))
        indexes = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }

    assert "tickets_project_id_idx" in indexes
    assert "tickets_status_idx" in indexes
