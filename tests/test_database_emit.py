"""The generated persistence package is the declaration as Python, and it has to run."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from drydock.database_apply import DEFAULT_DSN, apply_schema
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
        "testing.py",
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


def _emitted_build(tmp_path: Path) -> Path:
    blueprint_dir = tmp_path / "blueprint"
    build_dir = tmp_path / "build"
    blueprint_dir.mkdir()
    (blueprint_dir / "DATABASE.md").write_text(_DATABASE, encoding="utf-8")
    write_persistence_package(blueprint_dir, build_dir)
    return build_dir


def _run_in_build(build_dir: Path, script: str, env: dict[str, str] | None = None):
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=build_dir,
        env={"PYTHONPATH": str(build_dir), **(env or {})},
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_generated_db_session_opens_a_store_with_the_schema_applied(tmp_path: Path):
    build_dir = _emitted_build(tmp_path)

    result = _run_in_build(
        build_dir,
        "from persistence.testing import db_session\n"
        "with db_session() as db:\n"
        "    identity = db.tickets.create(status='open', title='T')\n"
        "    assert [row.id for row in db.tickets.list(status='open')] == [identity]\n"
        "print('SESSION OK')\n",
    )

    assert result.returncode == 0, result.stderr
    assert "SESSION OK" in result.stdout


def test_apply_schema_creates_the_tables_in_the_default_store(tmp_path: Path, monkeypatch):
    # Regression shape from ReadingList Haiku 20261013.235724: the application opened
    # data/app.db, which nothing had applied schema.sql to, so every write raised
    # "no such table".
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    build_dir = _emitted_build(tmp_path)

    application = apply_schema(build_dir)

    assert application is not None and application.applied, application
    result = _run_in_build(
        build_dir,
        "from persistence import open_database\n"
        f"db = open_database({DEFAULT_DSN!r})\n"
        "db.tickets.create(status='open', title='T')\n"
        "print('STORE OK')\n",
    )
    assert result.returncode == 0, result.stderr


def test_apply_schema_is_idempotent_and_honours_database_path(tmp_path: Path):
    build_dir = _emitted_build(tmp_path)
    env = {"DATABASE_PATH": "elsewhere/books.db", "PATH": ""}

    first = apply_schema(build_dir, env=env)
    second = apply_schema(build_dir, env=env)

    assert first is not None and first.applied, first
    assert second is not None and second.applied, second
    assert (build_dir / "elsewhere" / "books.db").is_file()
    assert not (build_dir / DEFAULT_DSN).exists()


def test_apply_schema_reports_an_unreachable_store(tmp_path: Path):
    build_dir = _emitted_build(tmp_path)

    application = apply_schema(build_dir, env={"DATABASE_URL": "nosuch://store"})

    assert application is not None and not application.applied
    assert "no persistence driver for 'nosuch'" in application.detail


def test_apply_schema_is_skipped_without_a_generated_schema(tmp_path: Path):
    assert apply_schema(tmp_path) is None


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
