from pathlib import Path

import pytest

from drydock.database_contract import (
    changed_operation_ids_since,
    create_ticket_migration_records,
    database_contract_defects,
    database_operation_fingerprints,
    derive_missing_dtos,
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


def test_a_shared_pattern_may_be_cited_by_any_blueprint():
    """A log is owned by no single Feature: every Feature appends to it. `DATABASE.md` as Owner
    says exactly that, and a citation of one is legal from anywhere."""
    shared = _DATABASE.replace("| Owner | FEATURE-Order.md |", "| Owner | DATABASE.md |", 1)
    contract = parse_database_contract(shared)

    validate_database_interfaces(
        contract,
        {
            "FEATURE-Shipping.md": parse_database_interface(
                "## Database Interface\n\n- `FEATURE-ORDER-001` — write: create an order "
                "- supplies: `customer_id`, `items` - returns: `id`\n",
                source="FEATURE-Shipping.md",
            )
        },
    )


def test_a_feature_owned_pattern_is_still_cited_only_by_its_owner():
    """The boundary shared ownership must not dissolve."""
    contract = parse_database_contract(_DATABASE)

    with pytest.raises(SpecificationError, match="is owned by 'FEATURE-Order.md'"):
        validate_database_interfaces(
            contract,
            {"FEATURE-Shipping.md": parse_database_interface(_INTERFACE)},
        )


def test_only_a_feature_in_the_plan_or_the_declaration_may_own_a_pattern():
    from drydock.database_contract import legal_owner

    blueprints = {"FEATURE-Order.md", "SCREEN-Orders.md"}

    assert legal_owner("FEATURE-Order.md", blueprints)
    assert legal_owner("DATABASE.md", blueprints)
    # A Screen renders data through a Feature's service; it never holds a repository.
    assert not legal_owner("SCREEN-Orders.md", blueprints)
    assert not legal_owner("order_service", blueprints)
    assert not legal_owner("FEATURE-Absent.md", blueprints)


def test_an_owner_that_owns_no_data_in_the_plan_is_rewritten_to_the_declaration():
    """Deterministic, because nothing is left to decide: no Feature here claims the pattern."""
    from drydock.database_contract import declared_owners, rewrite_illegal_owners

    text = _DATABASE.replace("| Owner | FEATURE-Order.md |", "| Owner | order_service |", 1)

    rewritten, changed = rewrite_illegal_owners(text, {"FEATURE-Order.md"})

    assert changed == ("order_service",)
    assert declared_owners(rewritten) == ("DATABASE.md", "FEATURE-Order.md")
    # The table around the cell is untouched.
    assert rewritten.count("| Access | write |") == text.count("| Access | write |")
    assert rewrite_illegal_owners(rewritten, {"FEATURE-Order.md"}) == (rewritten, ())


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


def test_bracketed_modifiers_copied_from_the_form_are_unwrapped():
    bracketed = _COLUMN_GRAMMAR.replace(
        "| title | VARCHAR(200) NOT NULL |", "| title | VARCHAR(200) [NOT NULL] [UNIQUE] |"
    ).replace("DEFAULT 'active'", "[DEFAULT '[]']")

    sql = sqlite_schema_sql(sqlite_schema_tables(bracketed))

    assert '"title" VARCHAR(200) NOT NULL UNIQUE' in sql
    assert "\"status\" TEXT NOT NULL DEFAULT '[]'" in sql


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


_BARE_PATTERNS = """# DATABASE: Accounts

## Access Patterns

### FEATURE-GITHUB-001 — Update accounts
| Field | Value |
|-------|-------|
| Owner | FEATURE-GITHUB.md |
| Access | read-write |
| Repository operation | `git_accounts.update` |
| Compatibility | data |

### FEATURE-GITHUB-002 — Add accounts
| Field | Value |
|-------|-------|
| Owner | FEATURE-GITHUB.md |
| Access | write |
| Repository operation | `git_accounts.create` |
| Compatibility | data |

### FEATURE-GITHUB-003 — List accounts
| Field | Value |
|-------|-------|
| Owner | FEATURE-GITHUB.md |
| Access | read |
| Repository operation | `git_accounts.list` |
| Compatibility | unchanged |

Input: `AccountQuery`
| Field | Type |
|-------|------|
| login | TEXT |

## Schema

## `git_accounts`

| Field | Type | Notes |
|-------|------|-------|
| id | INTEGER PK | |
| login | TEXT NOT NULL | |
| verified_at | TEXT | |
"""


def test_missing_dtos_are_derived_from_the_schema_table():
    """Marina_Luna: a repair pass told to reach fifteen uncited tables added fifteen patterns with
    no DTO tables, and the run died on its last pass. The table fixes the DTOs; code writes them."""
    assert len(database_contract_defects(_BARE_PATTERNS)) == 3

    text, completed = derive_missing_dtos(_BARE_PATTERNS)

    assert completed == ("FEATURE-GITHUB-001", "FEATURE-GITHUB-002", "FEATURE-GITHUB-003")
    assert database_contract_defects(text) == ()
    patterns = parse_database_contract(text).by_id()
    update, create, listing = (patterns[f"FEATURE-GITHUB-00{n}"] for n in (1, 2, 3))
    assert update.input_name == "GitAccountsUpdate"
    assert [(f.name, f.required) for f in update.inputs] == [
        ("id", True),
        ("login", False),
        ("verified_at", False),
    ]
    assert [(f.name, f.required) for f in create.inputs] == [
        ("login", True),
        ("verified_at", False),
    ]
    assert [f.name for f in update.outputs] == ["id", "login", "verified_at"]
    # A declared DTO is kept; only the missing half is derived.
    assert listing.input_name == "AccountQuery" and listing.output_name == "GitAccountsRow"
    assert derive_missing_dtos(text) == (text, ())


def test_dtos_are_not_invented_for_an_undeclared_table():
    text = _BARE_PATTERNS.replace("`git_accounts.update`", "`ghosts.update`")

    derived, completed = derive_missing_dtos(text)

    assert "FEATURE-GITHUB-001" not in completed
    assert "requires Input and Output tables" in "".join(database_contract_defects(derived))


_READING_LIST = """# DATABASE: ReadingList

## Access Patterns

### FEATURE-BOOK-001 — List books

| Field | Value |
|---|---|
| Owner | FEATURE-BookList.md |
| Access | read |
| Repository operation | `books.list` |
| Compatibility | unchanged |

Input: BookListQuery

| Field | Type | Notes |
|---|---|---|
| (none) | — | No input. |

Output: Book

| Field | Type | Notes |
|---|---|---|
| id | INTEGER | |
| title | TEXT | |

### FEATURE-BOOK-002 — Delete a book

| Field | Value |
|---|---|
| Owner | FEATURE-BookRemove.md |
| Access | write |
| Repository operation | `books.delete` |
| Compatibility | unchanged |

Input: BookDelete

| Field | Type | Notes |
|---|---|---|
| book_id | INTEGER | Identifier of the book to remove. |

Output: Removal

| Field | Type | Notes |
|---|---|---|
| book_id | INTEGER | |

## `books`

| Field | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| title | TEXT NOT NULL | |
"""


def test_an_input_field_that_is_not_a_column_of_its_table_is_a_defect():
    # ReadingList 20261022.180908: `book_id` was bound as a column of `books(id)`, and SQLite read
    # `"book_id" = ?` as a string comparison, so every delete removed nothing.
    defects = database_contract_defects(_READING_LIST)

    assert len(defects) == 1
    assert (
        "FEATURE-BOOK-002 Input field `book_id` is not a column of `books` (id, title)"
        in (defects[0])
    )
    assert database_contract_defects(_READING_LIST.replace("| book_id |", "| id |")) == ()


def test_a_list_output_that_wraps_its_rows_is_a_defect():
    # ReadingList 20261023.200606: `books.list` declared Output `BookList { books: list[Book] }`;
    # the repository built one BookList per record from columns it does not have.
    wrapped = _READING_LIST.replace("| book_id |", "| id |").replace(
        "Output: Book\n\n| Field | Type | Notes |\n|---|---|---|\n| id | INTEGER | |\n"
        "| title | TEXT | |\n",
        "Output: BookList\n\n| Field | Type | Notes |\n|---|---|---|\n| books | list[Book] | |\n",
    )
    defects = database_contract_defects(wrapped)

    assert len(defects) == 1
    assert (
        "FEATURE-BOOK-001 Output field `books` is not a column of `books` (id, title)"
        in (defects[0])
    )
    assert "never a collection of rows" in defects[0]


def test_a_delete_output_names_only_its_input_key():
    # ReadingList 20261023.200606: `books.delete` returned the affected-row count, so a criterion
    # reading `deleted.id` failed on an int. A delete Output is built from the key it was given.
    renamed = _READING_LIST.replace("| book_id |", "| id |", 1)
    defects = database_contract_defects(renamed.replace("| book_id |", "| removed |"))

    assert len(defects) == 1
    assert "FEATURE-BOOK-002 Output field `removed` is not an Input field (id)" in defects[0]
    assert database_contract_defects(renamed.replace("| book_id |", "| id |")) == ()


def test_a_placeholder_input_row_declares_no_field():
    contract = parse_database_contract(_READING_LIST)

    assert contract.by_id()["FEATURE-BOOK-001"].inputs == ()
    uses = parse_database_interface(
        "## Database Interface\n\n"
        "- `FEATURE-BOOK-001` — read: books.list - supplies: (none) - returns: `id`\n"
    )
    assert uses[0].supplies == ()
