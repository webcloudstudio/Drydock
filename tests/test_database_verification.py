"""Runtime schema checks distinguish an existing database from a valid declaration."""

import sqlite3

import pytest

from drydock.database_contract import schema_sql
from drydock.database_verification import verification_probes

DECLARATION = """# DATABASE: Probe

## `parents`
| Field | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| name | TEXT UNIQUE NOT NULL | |

## `children`
| Field | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| parent_id | INTEGER REFERENCES parents(id) | |
| status | TEXT DEFAULT 'open' | |
- UNIQUE (parent_id, status)
- INDEX (status, parent_id)
"""


def failures(connection, probes):
    failed = []
    for probe in probes:
        try:
            count = connection.execute(probe["sql"]).fetchone()[0]
        except sqlite3.Error:
            failed.append(probe["name"])
            continue
        if count < 0 or (probe["expected"] >= 0 and count != probe["expected"]):
            failed.append(probe["name"])
    return failed


@pytest.mark.parametrize(
    "change",
    [
        "",
        "DROP TABLE children",
        "DROP INDEX children_status_parent_id_idx",
        "PRAGMA foreign_keys=OFF",
    ],
)
def test_probes_exercise_all_declared_objects_without_mutation(change):
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(schema_sql(DECLARATION))
    conn.execute("INSERT INTO parents VALUES (1, 'unrelated')")
    if change:
        conn.execute(change)
    probes = verification_probes(DECLARATION)["sqlite"]
    assert bool(failures(conn, probes)) == bool(change)
    assert conn.execute("SELECT name FROM parents").fetchall() == [("unrelated",)]
    conn.close()


@pytest.mark.parametrize(
    "removed", ["UNIQUE", "NOT NULL", "REFERENCES parents(id)", "DEFAULT 'open'"]
)
def test_catalog_detects_wrong_constraints_in_an_existing_store(removed):
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(schema_sql(DECLARATION.replace(removed, "", 1)))
    assert failures(conn, verification_probes(DECLARATION)["sqlite"])
    conn.close()
