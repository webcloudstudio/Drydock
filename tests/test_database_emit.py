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


def test_a_create_pattern_gets_its_declared_output_row_class():
    module = render_schema_module(_DATABASE)

    assert "class TicketId:" in module
    assert "verb='create',\n        inputs=('status', 'title'),\n        row=TicketId," in module


def test_row_fields_are_annotated_with_python_types_and_a_placeholder_is_no_input():
    declared = _DATABASE.replace(
        "| id | int |\n| status | str |", "| id | INTEGER |\n| status | TEXT |"
    )
    declared = declared.replace(
        "| status | str | yes |\n\nOutput: Ticket", "| (none) | — | no |\n\nOutput: Ticket"
    )
    module = render_schema_module(declared)

    assert "class Ticket:\n    id: int\n    status: str\n    title: str\n" in module
    assert "verb='list',\n        inputs=()," in module


_TEXT_KEY_DATABASE = """# DATABASE: Ledger

## Access Patterns

### FEATURE-ACCOUNT-001 — Create account

| Field | Value |
|---|---|
| Owner | FEATURE-Account.md |
| Access | write |
| Repository operation | `accounts.create` |
| Compatibility | unchanged |

Input: AccountRow

| Field | Type | Notes |
|---|---|---|
| account | VARCHAR(12) | Account code |
| name | VARCHAR(40) | Account name |

Output: AccountRow

| Field | Type | Notes |
|---|---|---|
| account | VARCHAR(12) | Account code |
| name | VARCHAR(40) | Account name |

## `accounts`

| Field | Type | Notes |
|---|---|---|
| account | VARCHAR(12) PK | |
| name | VARCHAR(40) NOT NULL | |
"""


def test_create_on_a_text_key_returns_the_declared_row(tmp_path: Path):
    # Regression shape from LayersTesting Haiku 20261020.132808: create returned SQLite's
    # lastrowid (1), so `result.account` raised AttributeError on a declared AccountRow output.
    blueprint_dir = tmp_path / "blueprint"
    build_dir = tmp_path / "build"
    blueprint_dir.mkdir()
    (blueprint_dir / "DATABASE.md").write_text(_TEXT_KEY_DATABASE, encoding="utf-8")
    write_persistence_package(blueprint_dir, build_dir)

    assert apply_schema(build_dir).applied
    result = _run_in_build(
        build_dir,
        "from persistence.testing import db_session\n"
        "with db_session() as db:\n"
        "    created = db.accounts.create(account='TXNA1', name='Commit Test')\n"
        "    assert type(created).__name__ == 'AccountRow', created\n"
        "    assert (created.account, created.name) == ('TXNA1', 'Commit Test'), created\n"
        "print('CREATE OK')\n",
    )

    assert result.returncode == 0, result.stderr
    assert "CREATE OK" in result.stdout


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
        "schema-verification.json",
    }

    script = f"""
import sys
sys.path.insert(0, {str(build_dir)!r})
from {PACKAGE} import open_database
db = open_database({str(build_dir / "app.db")!r})
db.execute_script(open({str(build_dir / "schema.sql")!r}).read())
created = db.tickets.create(status="open", title="Plan discovery")
rows = db.tickets.list(status="open")
assert [row.id for row in rows] == [created.id], rows
assert rows[0].title == "Plan discovery"
print("ROUNDTRIP OK")
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
    assert "ROUNDTRIP OK" in result.stdout


_DELETE_PATTERN = """### FEATURE-TICKET-003 — Delete ticket

| Field | Value |
|---|---|
| Owner | FEATURE-Ticket.md |
| Access | write |
| Repository operation | `tickets.delete` |
| Compatibility | rebuild |

Input: TicketDelete

| Field | Type | Required |
|---|---|---|
| id | int | yes |

Output: DeletedTicket

| Field | Type |
|---|---|
| id | int |

"""


def test_a_delete_returns_its_declared_output_built_from_the_key(tmp_path: Path):
    # ReadingList 20261023.200606: the delete returned the affected-row count, so a criterion
    # written against the declared Output failed on `deleted.id`.
    declared = _DATABASE.replace("## `tickets`", _DELETE_PATTERN + "## `tickets`")
    module = render_schema_module(declared)
    assert "class DeletedTicket:\n    id: int\n" in module
    assert "verb='delete',\n        inputs=('id',),\n        row=DeletedTicket," in module

    blueprint_dir = tmp_path / "blueprint"
    build_dir = tmp_path / "build"
    blueprint_dir.mkdir()
    (blueprint_dir / "DATABASE.md").write_text(declared, encoding="utf-8")
    write_persistence_package(blueprint_dir, build_dir)
    script = f"""
from {PACKAGE} import open_database
db = open_database("app.db")
db.execute_script(open("schema.sql").read())
created = db.tickets.create(status="open", title="Plan discovery")
deleted = db.tickets.delete(id=created.id)
assert deleted.id == created.id, deleted
assert db.tickets.list(status="open") == []
assert db.tickets.delete(id=created.id) is None
print("DELETE OK")
"""
    result = _run_in_build(build_dir, script)

    assert result.returncode == 0, result.stderr
    assert "DELETE OK" in result.stdout


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


def test_the_generated_db_session_uses_the_provisioned_store(tmp_path: Path):
    build_dir = _emitted_build(tmp_path)

    assert apply_schema(build_dir).applied
    result = _run_in_build(
        build_dir,
        "from persistence.testing import db_session\n"
        "with db_session() as db:\n"
        "    created = db.tickets.create(status='open', title='T')\n"
        "    assert [row.id for row in db.tickets.list(status='open')] == [created.id]\n"
        "print('SESSION OK')\n",
    )

    assert result.returncode == 0, result.stderr
    assert "SESSION OK" in result.stdout


def test_writes_autocommit_with_no_transaction(tmp_path: Path):
    build_dir = _emitted_build(tmp_path)

    result = _run_in_build(
        build_dir,
        "import sys\n"
        "from persistence import open_database\n"
        "first = open_database('app.db')\n"
        "first.execute_script(open('schema.sql').read())\n"
        "created = first.tickets.create(status='open', title='T')\n"
        "assert first.driver.connect().isolation_level is None\n"
        "second = open_database('app.db')\n"
        "assert [row.id for row in second.tickets.list(status='open')] == [created.id]\n"
        "print('AUTOCOMMIT OK')\n",
    )

    assert result.returncode == 0, result.stderr
    assert "AUTOCOMMIT OK" in result.stdout


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


def test_apply_schema_is_skipped_for_a_persistence_package_before_the_database_step(
    tmp_path: Path,
):
    # ReadingList 20261022.220045: foundation stood up persistence/ for create_app before the
    # DATABASE step ran, and verification failed the block as missing DATABASE artifacts.
    (tmp_path / "persistence").mkdir()
    (tmp_path / "persistence" / "__init__.py").write_text("", encoding="utf-8")

    assert apply_schema(tmp_path, verify_only=True) is None


def test_apply_schema_reports_a_partial_database_step(tmp_path: Path):
    (tmp_path / "persistence").mkdir()
    (tmp_path / "schema.sql").write_text("", encoding="utf-8")

    application = apply_schema(tmp_path, verify_only=True)

    assert application is not None and not application.applied
    assert "persistence artifacts missing" in application.detail


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


@pytest.mark.parametrize(
    "rigging", ["sqlite.md", "sqlite_compact.md", "postgres.md", "postgres_compact.md"]
)
def test_the_published_contract_names_exactly_the_files_drydock_writes(
    tmp_path: Path, rigging: str
):
    """The contract a planner reads must describe the build Drydock performs. ReadingList
    20261014.014000 stopped at plan because the contract both claimed a synthesized story built
    the package and that the build never wrote it; the planner asked which, and wrote nothing."""
    import re

    from drydock.paths import get_rigging_root
    from drydock.rigging_contract import contract_section

    section = contract_section((get_rigging_root() / "stack" / rigging).read_text("utf-8"))
    assert section is not None
    table = [line for line in section.splitlines() if line.startswith("| ") and "`" in line]
    published = {
        path
        for line in table
        for path in re.findall(r"`((?:persistence/)?[\w.-]+\.(?:py|sql|json))`", line)
    }

    blueprint_dir = tmp_path / "blueprint"
    build_dir = tmp_path / "build"
    blueprint_dir.mkdir()
    (blueprint_dir / "DATABASE.md").write_text(_DATABASE, encoding="utf-8")
    written = write_persistence_package(blueprint_dir, build_dir)

    assert published == {path.relative_to(build_dir).as_posix() for path in written}
    assert "never writes" not in section


def test_verification_never_recreates_a_missing_store(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    build = _emitted_build(tmp_path)
    result = apply_schema(build, verify_only=True)
    assert not result.applied
    assert "store missing" in result.detail
    assert not (build / DEFAULT_DSN).exists()


def test_runtime_verification_detects_missing_indexes_and_preserves_rows(tmp_path, monkeypatch):
    import sqlite3

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    build = _emitted_build(tmp_path)
    assert apply_schema(build).applied
    with sqlite3.connect(build / DEFAULT_DSN) as conn:
        conn.execute("INSERT INTO tickets(status,title) VALUES ('open','existing')")
        index = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
        ).fetchone()[0]
        conn.execute(f'DROP INDEX "{index}"')
    result = apply_schema(build, verify_only=True)
    assert not result.applied and index in result.detail
    with sqlite3.connect(build / DEFAULT_DSN) as conn:
        assert conn.execute("SELECT count(*) FROM tickets").fetchone()[0] == 1
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name=?", (index,)).fetchall()


def test_fixture_rollback_on_failed_assertion_and_process_exit(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    build = _emitted_build(tmp_path)
    assert apply_schema(build).applied
    for ending in ["raise AssertionError('failed')", "os._exit(17)"]:
        result = _run_in_build(
            build,
            "import os\nfrom persistence.testing import db_session\n"
            "with db_session() as db:\n"
            "    db.tickets.create(status='open', title='owned')\n"
            f"    {ending}\n",
        )
        assert result.returncode != 0
        check = _run_in_build(
            build,
            "from persistence.testing import db_session\n"
            "with db_session() as db:\n"
            "    assert db.tickets.list(status='open') == []\n",
        )
        assert check.returncode == 0, check.stderr


@pytest.mark.parametrize("order", [("first", "second"), ("second", "first")])
def test_criteria_are_order_independent_on_a_populated_store(tmp_path, monkeypatch, order):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    build = _emitted_build(tmp_path)
    assert apply_schema(build).applied
    result = _run_in_build(
        build,
        "from persistence import open_database\n"
        "with open_database('data/app.db') as db:\n"
        "    db.tickets.create(status='open', title='unrelated')\n",
    )
    assert result.returncode == 0, result.stderr
    for owned in (*order, *order):
        result = _run_in_build(
            build,
            "from persistence.testing import db_session\n"
            "with db_session() as db:\n"
            f"    row = db.tickets.create(status='open', title={owned!r})\n"
            "    selected = [r for r in db.tickets.list(status='open') if r.id == row.id]\n"
            "    assert len(selected) == 1\n",
        )
        assert result.returncode == 0, result.stderr
    result = _run_in_build(
        build,
        "from persistence.testing import db_session\n"
        "with db_session() as db:\n"
        "    assert [r.title for r in db.tickets.list(status='open')] == ['unrelated']\n",
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "missing", ["schema.sql", "schema-verification.json", "persistence/schema.py"]
)
def test_missing_persistence_artifact_is_a_failure(tmp_path, monkeypatch, missing):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    build = _emitted_build(tmp_path)
    assert apply_schema(build).applied
    (build / missing).unlink()
    assert not apply_schema(build, verify_only=True).applied


def test_fixture_does_not_create_a_missing_database(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    build = _emitted_build(tmp_path)
    result = _run_in_build(
        build, "from persistence.testing import db_session\nwith db_session() as db:\n    pass\n"
    )
    assert result.returncode != 0 and "store missing" in result.stderr
    assert not (build / DEFAULT_DSN).exists()


def test_committed_fixture_persists_across_connections_without_schema_setup(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    build = _emitted_build(tmp_path)
    assert apply_schema(build).applied
    result = _run_in_build(
        build,
        "from persistence.testing import committed_session, db_session\n"
        "with committed_session() as db:\n"
        "    row = db.tickets.create(status='open', title='durable')\n"
        "with committed_session() as db:\n"
        "    assert [r.title for r in db.tickets.list(status='open') if r.id == row.id] == ['durable']\n"
        "with db_session() as db:\n"
        "    db.tickets.create(status='open', title='temporary')\n"
        "with committed_session() as db:\n"
        "    assert [r.title for r in db.tickets.list(status='open')] == ['durable']\n",
    )
    assert result.returncode == 0, result.stderr
