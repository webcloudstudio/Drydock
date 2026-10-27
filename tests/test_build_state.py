"""Real SQLite state isolation and preservation; all resources belong to tmp_path."""

import sqlite3
from pathlib import Path

import pytest

from drydock.build_state import AgentStore, persistence_recovery
from drydock.database_apply import SchemaApplication


def rows(path):
    with sqlite3.connect(path) as db:
        return db.execute("SELECT value FROM records ORDER BY value").fetchall()


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    build, target = tmp_path / "build", tmp_path / "target"
    (build / "data").mkdir(parents=True)
    (build / ".drydock-persistence.json").write_text('{"source":"DATABASE.md"}')
    canonical = build / "data/app.db"
    with sqlite3.connect(canonical) as db:
        db.execute("CREATE TABLE records (value TEXT)")
        db.execute("INSERT INTO records VALUES ('existing')")

    def provision(build_dir, *, env):
        with sqlite3.connect(env["DATABASE_URL"]) as db:
            db.execute("CREATE TABLE records (value TEXT)")
        return SchemaApplication(True, "provisioned")

    monkeypatch.setattr("drydock.build_state.apply_schema", provision)
    return build, target, canonical


def test_test_writes_are_disposable_and_repeatable_without_changing_managed_store(store):
    build, target, canonical = store
    paths = []
    for _ in range(2):
        with AgentStore(build, target) as state:
            test_path = Path(state.environment["DATABASE_URL"])
            paths.append(test_path)
            assert state.environment["DATABASE_PATH"] == str(test_path)
            assert rows(test_path) == []
            with sqlite3.connect(test_path) as db:
                db.execute("INSERT INTO records VALUES ('test')")
            assert rows(test_path) == [("test",)]
        assert not state.violation
        assert not test_path.exists()
        assert not state.backup_path.exists()
        assert rows(canonical) == [("existing",)]
    assert paths[0] != paths[1]


@pytest.mark.parametrize("change", ["delete", "modify"])
def test_managed_state_violation_retains_backup_and_never_overwrites_new_state(store, change):
    build, target, canonical = store
    with AgentStore(build, target) as state:
        if change == "delete":
            canonical.unlink()
        else:
            with sqlite3.connect(canonical) as db:
                db.execute("INSERT INTO records VALUES ('concurrent')")
    assert "Managed SQLite state changed" in state.violation
    assert rows(state.backup_path) == [("existing",)]
    if change == "delete":
        assert not canonical.exists()
    else:
        assert rows(canonical) == [("concurrent",), ("existing",)]


def test_provider_exception_also_preserves_deleted_store_snapshot(store):
    build, target, canonical = store
    with pytest.raises(ValueError, match="provider"):
        with AgentStore(build, target) as state:
            canonical.unlink()
            raise ValueError("provider failed")
    assert state.violation
    assert rows(state.backup_path) == [("existing",)]


def test_external_sqlite_store_is_not_copied_or_modified(store, monkeypatch, tmp_path):
    build, target, canonical = store
    external = tmp_path / "external.db"
    external.write_bytes(b"not read or overwritten")
    monkeypatch.setenv("DATABASE_URL", str(external))
    with AgentStore(build, target) as state:
        assert state.backup_path is None
        assert Path(state.environment["DATABASE_URL"]) != external
    assert external.read_bytes() == b"not read or overwritten"


def test_remote_store_is_not_silently_claimed_to_be_isolated(store, monkeypatch):
    build, target, canonical = store
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured/service")
    with AgentStore(build, target) as state:
        assert state.environment == {}
        assert state.backup_path is None


def test_recovery_names_owner_and_requires_data_preservation():
    text = persistence_recovery("Example", "database", "snapshot retained")
    assert "DATABASE story `database`" in text
    assert "not data recovery" in text
    assert "snapshot retained" in text
    assert "--step block-6" not in text


def test_missing_managed_store_stops_before_agent_tests(store):
    build, target, canonical = store
    canonical.unlink()
    state = AgentStore(build, target)
    with pytest.raises(RuntimeError, match="DATABASE owner"):
        with state:
            pytest.fail("a missing managed store cannot launch an agent")
    assert not state.ready
    assert not state.environment


def test_provider_failure_without_mutation_keeps_canonical_and_discards_snapshot(store):
    build, target, canonical = store
    with pytest.raises(ValueError, match="provider"):
        with AgentStore(build, target) as state:
            with sqlite3.connect(state.environment["DATABASE_URL"]) as db:
                db.execute("INSERT INTO records VALUES ('test')")
            raise ValueError("provider failed")
    assert not state.violation
    assert not state.backup_path.exists()
    assert rows(canonical) == [("existing",)]


_COMMITTING_TESTS = """
import os
import sqlite3


def _rows():
    with sqlite3.connect(os.environ["DATABASE_URL"]) as db:
        return db.execute("SELECT value FROM records").fetchall()


def test_{first}_commits_a_row():
    with sqlite3.connect(os.environ["DATABASE_URL"]) as db:
        db.execute("INSERT INTO records VALUES ('{first}')")
    assert _rows() == [("{first}",)]


def test_{second}_commits_a_row():
    with sqlite3.connect(os.environ["DATABASE_URL"]) as db:
        db.execute("INSERT INTO records VALUES ('{second}')")
    assert _rows() == [("{second}",)]
"""


@pytest.mark.parametrize(("first", "second"), [("a", "b"), ("b", "a")])
def test_two_project_tests_in_one_agent_call_cannot_contaminate_each_other(
    store, tmp_path, first, second
):
    """FxRates 20261026.173232: committed project-test writes collided within one call."""
    import os
    import subprocess
    import sys

    build, target, canonical = store
    project = tmp_path / "project"
    project.mkdir()
    (project / "test_store.py").write_text(
        _COMMITTING_TESTS.format(first=first, second=second), encoding="utf-8"
    )
    with AgentStore(build, target) as state:
        template = Path(state.environment["DATABASE_URL"])
        child = {**os.environ, **state.environment}
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", "-p", "no:cacheprovider"],
            cwd=project,
            env=child,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert "2 passed" in completed.stdout
        assert rows(template) == []
    assert rows(canonical) == [("existing",)]
    assert not (project / "drydock_store_isolation.py").exists()


def test_without_the_plugin_the_same_tests_collide(store, tmp_path):
    """Falsifier: the shared call store alone lets the second test see the first's row."""
    import os
    import subprocess
    import sys

    build, target, _ = store
    project = tmp_path / "project"
    project.mkdir()
    (project / "test_store.py").write_text(
        _COMMITTING_TESTS.format(first="a", second="b"), encoding="utf-8"
    )
    with AgentStore(build, target) as state:
        child = {**os.environ, **state.environment}
        child.pop("PYTEST_ADDOPTS")
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", "-p", "no:cacheprovider"],
            cwd=project,
            env=child,
            capture_output=True,
            text=True,
            check=False,
        )
    assert completed.returncode == 1
    assert "1 failed, 1 passed" in completed.stdout


def test_wal_checkpoint_without_logical_change_does_not_stop(store):
    build, target, canonical = store
    writer = sqlite3.connect(canonical)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("INSERT INTO records VALUES ('wal row')")
    writer.commit()
    with AgentStore(build, target) as state:
        writer.close()
    assert not state.violation
    assert rows(canonical) == [("existing",), ("wal row",)]


def test_agent_receives_the_acceptance_helper(store):
    build, target, _ = store
    with AgentStore(build, target) as state:
        plugin = Path(state.environment["PYTHONPATH"].split(__import__("os").pathsep)[0])
        assert (plugin / "drydock_acceptance.py").is_file()
        import os
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from drydock_acceptance import database_environment; "
                "assert callable(database_environment)",
            ],
            cwd=build,
            env={**os.environ, **state.environment},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr


def test_rowid_change_is_a_managed_change(store):
    build, target, canonical = store
    with AgentStore(build, target) as state:
        with sqlite3.connect(canonical) as db:
            db.execute("UPDATE records SET rowid = 100")
    assert state.violation
    assert rows(state.backup_path) == [("existing",)]


def test_unreadable_managed_database_stops_and_preserves_backup(store):
    build, target, canonical = store
    with AgentStore(build, target) as state:
        canonical.write_bytes(b"not sqlite")
    assert state.violation
    assert rows(state.backup_path) == [("existing",)]
