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
