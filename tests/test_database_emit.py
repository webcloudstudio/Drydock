"""The generated persistence package is the declaration as Python, and it has to run."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from drydock.database_emit import PACKAGE, render_schema_module, write_persistence_package
from drydock.errors import SpecificationError

_DATABASE = """# DATABASE: Marina

## Access Patterns

### FEATURE-TICKET-001 — Create ticket

| Field | Value |
|---|---|
| Owner | FEATURE-Ticket.md |
| Access | write |
| Repository operation | `tickets.create` |
| Compatibility | rebuild |

Input: CreateTicket

| Field | Type | Required |
|---|---|---|
| status | str | yes |
| title | str | yes |

Output: TicketId

| Field | Type |
|---|---|
| id | int |

### FEATURE-TICKET-002 — List tickets

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

Output: Ticket

| Field | Type |
|---|---|
| id | int |
| status | str |
| title | str |

## `tickets`

| Field | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| status | TEXT NOT NULL DEFAULT 'open' | |
| title | VARCHAR(200) NOT NULL | |
"""


def test_the_generated_module_carries_the_declaration_and_no_sql():
    module = render_schema_module(_DATABASE)

    assert "class Ticket:" in module
    assert "identifier='FEATURE-TICKET-002'" in module
    assert "verb='list'" in module
    assert "SELECT" not in module and "?" not in module and "%s" not in module


def test_a_write_pattern_gets_no_row_class():
    module = render_schema_module(_DATABASE)

    assert "class Ticketid:" not in module
    assert "row=None" in module


def test_the_emitted_package_runs_against_sqlite(tmp_path: Path):
    blueprint_dir = tmp_path / "blueprint"
    build_dir = tmp_path / "build"
    blueprint_dir.mkdir()
    (blueprint_dir / "DATABASE.md").write_text(_DATABASE, encoding="utf-8")

    written = write_persistence_package(blueprint_dir, build_dir)

    assert {path.name for path in written} == {
        "db.py",
        "sqlite.py",
        "postgres.py",
        "schema.py",
        "__init__.py",
        "schema.sql",
    }

    script = f"""
import sys
sys.path.insert(0, {str(build_dir)!r})
from {PACKAGE} import open_database
db = open_database({str(build_dir / "app.db")!r})
db.execute_script(open({str(build_dir / "schema.sql")!r}).read())
identity = db.tickets.create(status="open", title="Plan discovery")
rows = db.tickets.list(status="open")
assert [row.id for row in rows] == [identity], rows
assert rows[0].title == "Plan discovery"
print("ROUNDTRIP OK")
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
    assert "ROUNDTRIP OK" in result.stdout


def test_a_declaration_with_no_tables_emits_no_package(tmp_path: Path):
    blueprint_dir = tmp_path / "blueprint"
    blueprint_dir.mkdir()
    (blueprint_dir / "DATABASE.md").write_text("# DATABASE: X\n", encoding="utf-8")

    assert write_persistence_package(blueprint_dir, tmp_path / "build") == ()
    assert not (tmp_path / "build" / PACKAGE).exists()


def test_an_unreadable_declaration_is_reported_rather_than_emitted(tmp_path: Path):
    blueprint_dir = tmp_path / "blueprint"
    blueprint_dir.mkdir()
    (blueprint_dir / "DATABASE.md").write_text(
        _DATABASE.replace("| id | INTEGER PK | |", "| id | SERIAL PK | |"), encoding="utf-8"
    )

    with pytest.raises(SpecificationError, match="unsupported type 'SERIAL PK'"):
        write_persistence_package(blueprint_dir, tmp_path / "build")
