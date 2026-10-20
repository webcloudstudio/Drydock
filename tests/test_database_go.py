"""Generated Go stores execute real declared operations against SQLite/PostgreSQL."""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from drydock.database_apply import apply_schema
from drydock.database_emit import write_persistence_package
from drydock.database_emit_go import render_go_schema
from drydock.errors import SpecificationError
from tests.test_database_emit import _DATABASE

_EXTRA_PATTERNS = """
### FEATURE-TICKET-003 — Get ticket

| Field | Value |
|---|---|
| Owner | FEATURE-Ticket.md |
| Access | read |
| Repository operation | `tickets.get` |
| Compatibility | unchanged |

Input: GetTicket

| Field | Type | Required |
|---|---|---|
| id | int | yes |

Output: Ticket

| Field | Type |
|---|---|
| id | int |
| status | str |
| title | str |

### FEATURE-TICKET-004 — Update ticket

| Field | Value |
|---|---|
| Owner | FEATURE-Ticket.md |
| Access | write |
| Repository operation | `tickets.update` |
| Compatibility | unchanged |

Input: UpdateTicket

| Field | Type | Required |
|---|---|---|
| id | int | yes |
| status | str | no |

Output: Count

| Field | Type |
|---|---|
| count | int |

### FEATURE-TICKET-005 — Delete ticket

| Field | Value |
|---|---|
| Owner | FEATURE-Ticket.md |
| Access | write |
| Repository operation | `tickets.delete` |
| Compatibility | unchanged |

Input: DeleteTicket

| Field | Type | Required |
|---|---|---|
| id | int | yes |

Output: Count

| Field | Type |
|---|---|
| count | int |

"""


@pytest.fixture
def go_env(monkeypatch):
    if not shutil.which("go"):
        pytest.skip("Go toolchain required")
    for key, value in {
        "GOCACHE": "/tmp/drydock-go-cache",
        "GOMODCACHE": os.environ.get(
            "GOMODCACHE", subprocess.check_output(["go", "env", "GOMODCACHE"], text=True).strip()
        ),
        "GOPATH": "/tmp/drydock-go-path",
        "GOPROXY": "off",
    }.items():
        monkeypatch.setenv(key, value)
    from pathlib import Path

    cache = Path(os.environ["GOMODCACHE"])
    if (
        not (cache / "github.com/lib/pq@v1.10.9").is_dir()
        or not (cache / "github.com/mattn/go-sqlite3@v1.14.24").is_dir()
    ):
        pytest.skip("Pinned Go drivers must be downloaded before offline integration tests")
    return dict(os.environ)


@pytest.mark.parametrize("engine", ["sqlite", "postgres"])
def test_generated_go_store_and_schema_application(tmp_path, go_env, engine):
    if engine == "postgres" and not go_env.get("DRYDOCK_TEST_POSTGRES_DSN"):
        pytest.skip("Set DRYDOCK_TEST_POSTGRES_DSN for PostgreSQL integration")
    go_env = dict(go_env)
    if engine == "sqlite":
        go_env.pop("DRYDOCK_TEST_POSTGRES_DSN", None)
        if not shutil.which("gcc"):
            pytest.skip("C compiler required for Go SQLite")
    blueprint = tmp_path / "blueprint"
    blueprint.mkdir()
    (blueprint / "DATABASE.md").write_text(
        _DATABASE.replace("## `tickets`", _EXTRA_PATTERNS + "## `tickets`")
    )
    build = tmp_path / "build"
    build.mkdir()
    (build / "go.mod").write_text("module example.test/target\n\ngo 1.22\n")
    from drydock.technology_stack import StackEntry, write

    write(tmp_path, [StackEntry("Go", "go.md"), StackEntry("SQLite", "sqlite.md")])
    files = write_persistence_package(blueprint, build)
    assert build / "persistence/schema.go" in files
    applied = apply_schema(build, env=go_env)
    assert applied.applied, applied.detail
    (build / "store_test.go").write_text("""package target
import (
 "context"
 "os"
 "testing"
 "drydock.local/persistence"
)
func TestDeclaredOperations(t *testing.T) {
 ctx:=context.Background()
 ddl,err:=os.ReadFile("schema.sql");if err!=nil {t.Fatal(err)}
 db,cleanup,err:=persistence.OpenSession(ctx,os.Getenv("DRYDOCK_TEST_POSTGRES_DSN"),string(ddl))
 if err!=nil {t.Fatal(err)};defer cleanup()
 id,err:=db.Tickets.Create(ctx,persistence.TicketsCreateInput{Status:"open",Title:"bound ' value"})
 if err!=nil {t.Fatal(err)}
 rows,err:=db.Tickets.List(ctx,persistence.TicketsListInput{Status:"open"})
 if err!=nil {t.Fatal(err)}
 found:=false;for _,row:=range rows {if row.Id==id && row.Title=="bound ' value" {found=true}}
 if !found {t.Fatal("created row not returned")}
 if _,err=db.Run(ctx,"tickets","delete",nil);err==nil {t.Fatal("keyless delete accepted")}
 if _,err=db.Run(ctx,"tickets","create",nil);err==nil {t.Fatal("required columns not enforced")}
 preserved,err:=db.Tickets.Get(ctx,persistence.TicketsGetInput{Id:id})
 if err!=nil || preserved==nil {t.Fatal("keyless delete removed row")}
 status:="closed"
 count,err:=db.Tickets.Update(ctx,persistence.TicketsUpdateInput{Id:id,Status:&status})
 if err!=nil || count!=1 {t.Fatalf("update: %v %v",count,err)}
 row,err:=db.Tickets.Get(ctx,persistence.TicketsGetInput{Id:id})
 if err!=nil || row==nil || row.Status!="closed" {t.Fatalf("get: %v %v",row,err)}
 count,err=db.Tickets.Delete(ctx,persistence.TicketsDeleteInput{Id:id})
 if err!=nil || count!=1 {t.Fatalf("delete: %v %v",count,err)}
 row,err=db.Tickets.Get(ctx,persistence.TicketsGetInput{Id:id})
 if err!=nil || row!=nil {t.Fatalf("deleted row: %v %v",row,err)}
 if _,err=db.Run(ctx,"tickets","drop",nil);err==nil {t.Fatal("undeclared operation accepted")}
}
""")
    result = subprocess.run(
        ["go", "test", "./..."], cwd=build, env=go_env, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_go_generator_rejects_unknown_field_type():
    with pytest.raises(SpecificationError, match="Unsupported Go persistence field type"):
        render_go_schema(_DATABASE.replace("| status | str |", "| status | Mystery |"))


def test_go_generator_refuses_a_projection_it_cannot_supply():
    with pytest.raises(SpecificationError, match="undeclared column"):
        render_go_schema(_DATABASE.replace("| title | str |\n", "| invented | str |\n"))


def test_go_persistence_requires_language_initialization_first(tmp_path):
    from drydock.technology_stack import StackEntry, write

    blueprint = tmp_path / "blueprint"
    blueprint.mkdir()
    (blueprint / "DATABASE.md").write_text(_DATABASE)
    write(tmp_path, [StackEntry("Go", "go.md")])
    build = tmp_path / "build"
    build.mkdir()
    with pytest.raises(SpecificationError, match="create go.mod first"):
        write_persistence_package(blueprint, build)
    assert not (build / "persistence").exists()
