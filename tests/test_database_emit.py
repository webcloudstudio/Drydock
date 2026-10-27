"""The generated persistence package is the declaration as Python, and it has to run."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from drydock.database_apply import DEFAULT_DSN, apply_schema, premature_artifacts
from drydock.database_emit import PACKAGE, render_schema_module, write_persistence_package
from drydock.errors import SpecificationError
from drydock.paths import get_language_dir

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


def test_one_dto_name_with_two_field_sets_is_refused():
    # FxRates 20261024.070101: the first pattern's class was reused for a delete whose Output
    # held only its key, so the build raised on the missing fields.
    declared = _DATABASE.replace("Output: TicketId", "Output: Ticket", 1)

    with pytest.raises(SpecificationError, match="Conflicting Python row class Ticket"):
        render_schema_module(declared)


def _rates_database(delete_output: str = "Rate") -> str:
    """Synthetic FxRates-shaped declaration; never reads published UAT evidence."""
    patterns = []
    for index, verb in enumerate(("get", "list", "upsert", "delete"), 1):
        inputs = "| date | str |\n| currency | str |\n"
        if verb == "upsert":
            inputs += "| rate | str |\n"
        outputs = "| date | str |\n| currency | str |\n"
        if verb != "delete":
            outputs += "| rate | str |\n"
        access = "read" if verb in ("get", "list") else "write"
        match = "| Match | `date`, `currency` |\n" if verb != "list" else ""
        output_name = delete_output if verb == "delete" else "Rate"
        patterns.append(
            f"### FEATURE-RATES-{index:03d} — {verb}\n\n"
            "| Field | Value |\n|---|---|\n| Owner | DATABASE.md |\n"
            f"| Access | {access} |\n| Repository operation | `rates.{verb}` |\n"
            f"| Compatibility | unchanged |\n{match}\n"
            f"Input: Rates{verb.title()}Input\n\n| Field | Type |\n|---|---|\n{inputs}\n"
            f"Output: {output_name}\n\n| Field | Type |\n|---|---|\n{outputs}\n"
        )
    return (
        "# DATABASE: Rates\n\n## Access Patterns\n\n"
        + "".join(patterns)
        + "## Schemas\n\n## `rates`\n\n| Field | Type |\n|---|---|\n"
        "| id | INTEGER PK |\n| date | TEXT NOT NULL |\n"
        "| currency | TEXT NOT NULL |\n| rate | TEXT NOT NULL |\n\n"
        "- UNIQUE (date, currency)\n\n"
        "## Programmatic Acceptance\n\n"
        "=== AC rates-round-trip ===\nIntent: Declared operations store and retrieve a rate.\n\n"
        "from persistence.testing import db_session\n\n"
        "with db_session() as db:\n"
        "    saved = db.rates.upsert(date='2099-12-31', currency='ZZZ', rate='1.23')\n"
        "    assert saved.rate == '1.23'\n"
        "    found = db.rates.get(date='2099-12-31', currency='ZZZ')\n"
        "    assert found.rate == '1.23'\n"
        "    rows = db.rates.list(date='2099-12-31', currency='ZZZ')\n"
        "    assert len(rows) == 1 and rows[0].rate == '1.23'\n"
        "    removed = db.rates.delete(date='2099-12-31', currency='ZZZ')\n"
        "    assert removed.date == '2099-12-31'\n"
        "    assert db.rates.get(date='2099-12-31', currency='ZZZ') is None\n"
        "=== END AC rates-round-trip ===\n"
    )


def test_rates_distinct_delete_output_generates_both_row_contracts(tmp_path):
    with pytest.raises(SpecificationError, match="Conflicting Python row class Rate"):
        render_schema_module(_rates_database())

    module = render_schema_module(_rates_database("RatesDeleteOutput"))
    assert module.count("class Rate:") == 1
    assert "class RatesDeleteOutput:\n    date: str\n    currency: str\n" in module
    assert "row=RatesDeleteOutput," in module

    blueprint = tmp_path / "blueprint"
    blueprint.mkdir()
    (blueprint / "DATABASE.md").write_text(_rates_database("RatesDeleteOutput"))
    build = tmp_path / "build"
    write_persistence_package(blueprint, build)
    result = _run_in_build(
        build,
        """
from pathlib import Path
from persistence import open_database

with open_database('rates.db') as db:
    db.execute_script(Path('schema.sql').read_text())
    saved = db.rates.upsert(date='2099-12-31', currency='ZZZ', rate='1.23')
    assert type(saved).__name__ == 'Rate' and saved.rate == '1.23'
    found = db.rates.get(date='2099-12-31', currency='ZZZ')
    assert found == saved
    assert db.rates.list(date='2099-12-31', currency='ZZZ') == [saved]
    removed = db.rates.delete(date='2099-12-31', currency='ZZZ')
    assert type(removed).__name__ == 'RatesDeleteOutput'
    assert (removed.date, removed.currency) == ('2099-12-31', 'ZZZ')
    assert db.rates.get(date='2099-12-31', currency='ZZZ') is None
""",
    )
    assert result.returncode == 0, result.stderr


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


_UPDATE_PATTERN = """### FEATURE-TICKET-004 — Close ticket

| Field | Value |
|---|---|
| Owner | FEATURE-Ticket.md |
| Access | write |
| Repository operation | `tickets.update` |
| Compatibility | rebuild |

Input: TicketUpdate

| Field | Type | Required |
|---|---|---|
| id | int | yes |
| status | str | yes |

Output: Ticket

| Field | Type |
|---|---|
| id | int |
| status | str |
| title | str |

"""


def test_an_update_returns_its_declared_output_row_read_back_by_key(tmp_path: Path):
    declared = _DATABASE.replace("## `tickets`", _UPDATE_PATTERN + "## `tickets`")
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
updated = db.tickets.update(id=created.id, status="closed")
assert (updated.id, updated.status, updated.title) == (created.id, "closed", "Plan discovery")
assert db.tickets.update(id=created.id + 1000, status="closed") is None
print("UPDATE OK")
"""
    result = _run_in_build(build_dir, script)

    assert result.returncode == 0, result.stderr
    assert "UPDATE OK" in result.stdout


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


def _run_criterion(build_dir: Path, tmp_path: Path, script: str):
    """Run a criterion the way acceptance does: through the shipped runner, harness flag set."""
    criterion = tmp_path / "criterion.py"
    criterion.write_text(script, encoding="utf-8")
    runner = get_language_dir("python") / "acceptance" / "runner.py"
    return subprocess.run(
        [sys.executable, str(runner), str(criterion)],
        cwd=build_dir,
        env={"PYTHONPATH": str(build_dir), "DRYDOCK_ACCEPTANCE_TRANSACTION": "1"},
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


def test_apply_schema_skips_agent_written_ddl_before_the_database_step(tmp_path: Path):
    # FxRates 20261024.073528: foundation copied the shipped engines and hand-wrote schema.sql
    # before the DATABASE step, and verification failed the block unexecuted as missing
    # DATABASE artifacts.
    (tmp_path / "persistence").mkdir()
    (tmp_path / "persistence" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "schema.sql").write_text("CREATE TABLE IF NOT EXISTS rates (x TEXT);\n", "utf-8")

    assert apply_schema(tmp_path, verify_only=True) is None
    assert premature_artifacts(tmp_path) == ("schema.sql",)


def test_apply_schema_names_artifacts_missing_after_the_database_step(tmp_path: Path):
    blueprint_dir = tmp_path / "blueprint"
    build_dir = tmp_path / "build"
    blueprint_dir.mkdir()
    (blueprint_dir / "DATABASE.md").write_text(_DATABASE, encoding="utf-8")
    write_persistence_package(blueprint_dir, build_dir)
    assert premature_artifacts(build_dir) == ()
    (build_dir / "schema-verification.json").unlink()

    application = apply_schema(build_dir, verify_only=True)

    assert application is not None and not application.applied
    assert application.detail == (
        "persistence artifacts missing after the DATABASE step: schema-verification.json; "
        "rebuild the DATABASE step"
    )


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


def test_harness_rollback_spans_the_whole_criterion(tmp_path, monkeypatch):
    """FxRates 20261024.051856: setup in ``db_session()`` must survive to a later request."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    build = _emitted_build(tmp_path)
    assert apply_schema(build).applied
    result = _run_criterion(
        build,
        tmp_path,
        "import threading\n"
        "from pathlib import Path\n"
        "from persistence import open_database\n"
        "from persistence.testing import committed_session, db_session\n"
        "with db_session() as db:\n"
        "    row = db.tickets.create(status='open', title='seeded')\n"
        "with committed_session() as db:\n"
        "    db.tickets.create(status='open', title='committed')\n"
        "seen = []\n"
        "def request():\n"
        "    app = open_database(str(Path('data/app.db').resolve()))\n"
        "    seen.extend(r.title for r in app.tickets.list(status='open'))\n"
        "    app.close()\n"
        "thread = threading.Thread(target=request)\n"
        "thread.start()\n"
        "thread.join()\n"
        "assert seen == ['seeded', 'committed']\n",
    )
    assert result.returncode == 0, result.stderr
    check = _run_in_build(
        build,
        "from persistence import open_database\n"
        "assert open_database('data/app.db').tickets.list(status='open') == []\n",
    )
    assert check.returncode == 0, check.stderr


@pytest.mark.parametrize("ending", ["raise AssertionError('failed')", "os._exit(17)"])
def test_harness_rolls_back_a_failed_or_killed_criterion(tmp_path, monkeypatch, ending):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    build = _emitted_build(tmp_path)
    assert apply_schema(build).applied
    result = _run_criterion(
        build,
        tmp_path,
        "import os\nfrom persistence.testing import db_session\n"
        "with db_session() as db:\n"
        "    db.tickets.create(status='open', title='owned')\n"
        f"{ending}\n",
    )
    assert result.returncode != 0
    check = _run_in_build(
        build,
        "from persistence import open_database\n"
        "assert open_database('data/app.db').tickets.list(status='open') == []\n",
    )
    assert check.returncode == 0, check.stderr


def test_a_launched_process_does_not_inherit_the_harness(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    build = _emitted_build(tmp_path)
    assert apply_schema(build).applied
    result = _run_criterion(
        build,
        tmp_path,
        "import os, subprocess, sys\n"
        "assert 'DRYDOCK_ACCEPTANCE_TRANSACTION' not in os.environ\n"
        "child = subprocess.run([sys.executable, '-c', 'import os; "
        'print(os.environ.get("DRYDOCK_ACCEPTANCE_TRANSACTION", "absent"))\'],\n'
        "    capture_output=True, text=True)\n"
        "assert child.stdout.strip() == 'absent'\n",
    )
    assert result.returncode == 0, result.stderr


def test_generated_initializer_creates_fresh_store_and_preserves_rows_on_repeat(tmp_path):
    build = _emitted_build(tmp_path)
    result = _run_in_build(
        build,
        "from persistence import initialize_database\n"
        "with initialize_database('nested/fresh.db') as db:\n"
        "    assert db.tickets.list(status='open') == []\n"
        "    key = db.tickets.create(status='open', title='Keep this record')\n"
        "with initialize_database('sqlite://nested/fresh.db') as db:\n"
        "    rows = db.tickets.list(status='open')\n"
        "    assert [(r.id, r.title) for r in rows] == [(key.id, 'Keep this record')]\n",
    )
    assert result.returncode == 0, result.stderr


def test_generated_initializer_locates_schema_independently_of_cwd(tmp_path):
    build = _emitted_build(tmp_path)
    result = _run_in_build(
        build,
        "import os\n"
        "from persistence import initialize_database\n"
        "os.chdir('..')\n"
        "with initialize_database('elsewhere.db') as db:\n"
        "    assert db.tickets.list(status='open') == []\n",
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "elsewhere.db").is_file()


def test_generated_initializer_does_not_hide_missing_schema_or_apply_on_open(tmp_path):
    build = _emitted_build(tmp_path)
    result = _run_in_build(
        build,
        "from pathlib import Path\n"
        "from persistence import initialize_database, open_database\n"
        "with open_database('ordinary.db') as db:\n"
        "    try:\n"
        "        db.tickets.list(status='open')\n"
        "    except Exception as error:\n"
        "        assert 'no such table' in str(error), error\n"
        "    else:\n"
        "        raise AssertionError('ordinary open unexpectedly initialized schema')\n"
        "Path('schema.sql').unlink()\n"
        "try:\n"
        "    initialize_database('missing-schema.db')\n"
        "except FileNotFoundError:\n"
        "    pass\n"
        "else:\n"
        "    raise AssertionError('missing schema was silently ignored')\n"
        "assert not Path('missing-schema.db').exists()\n",
    )
    assert result.returncode == 0, result.stderr


def test_generated_initializer_is_safe_inside_acceptance_rollback(tmp_path):
    build = _emitted_build(tmp_path)
    assert apply_schema(build).applied
    seed = _run_in_build(
        build,
        "from persistence import open_database\n"
        "with open_database('data/app.db') as db:\n"
        "    db.tickets.create(status='open', title='Canonical record')\n",
    )
    assert seed.returncode == 0, seed.stderr
    result = _run_criterion(
        build,
        tmp_path,
        "from persistence import initialize_database\n"
        "with initialize_database('data/app.db') as db:\n"
        "    assert [r.title for r in db.tickets.list(status='open')] == ['Canonical record']\n"
        "    db.tickets.create(status='open', title='Rolled back')\n",
    )
    assert result.returncode == 0, result.stderr
    after = _run_in_build(
        build,
        "from persistence import open_database\n"
        "with open_database('data/app.db') as db:\n"
        "    assert [r.title for r in db.tickets.list(status='open')] == ['Canonical record']\n",
    )
    assert after.returncode == 0, after.stderr


def test_generated_initializer_cannot_execute_destructive_schema_sql(tmp_path):
    build = _emitted_build(tmp_path)
    assert apply_schema(build).applied
    result = _run_in_build(
        build,
        "from pathlib import Path\n"
        "from persistence import initialize_database, open_database, PersistenceError\n"
        "with open_database('data/app.db') as db:\n"
        "    db.tickets.create(status='open', title='Preserved')\n"
        "Path('schema.sql').write_text('CREATE TABLE IF NOT EXISTS surprise (id INTEGER); DROP TABLE tickets;')\n"
        "try:\n"
        "    initialize_database('data/app.db')\n"
        "except PersistenceError as error:\n"
        "    assert 'idempotent' in str(error)\n"
        "else:\n"
        "    raise AssertionError('destructive initialization succeeded')\n"
        "with open_database('data/app.db') as db:\n"
        "    assert [r.title for r in db.tickets.list(status='open')] == ['Preserved']\n"
        "    assert db.driver.connect().execute(\"SELECT name FROM sqlite_master WHERE name='surprise'\").fetchall() == []\n",
    )
    assert result.returncode == 0, result.stderr


def test_product_init_can_initialize_scratch_store_inside_acceptance_fixture(tmp_path):
    build = _emitted_build(tmp_path)
    assert apply_schema(build).applied
    result = _run_criterion(
        build,
        tmp_path,
        "from drydock_acceptance import database_environment\n"
        "from persistence import initialize_database\n"
        "with database_environment(url='new.db') as root:\n"
        "    with initialize_database(str(root / 'new.db')) as db:\n"
        "        db.tickets.create(status='open', title='Keep on repeat')\n"
        "    with initialize_database(str(root / 'new.db')) as db:\n"
        "        assert [r.title for r in db.tickets.list(status='open')] == ['Keep on repeat']\n",
    )
    assert result.returncode == 0, result.stderr
    assert not (build / "new.db").exists()
