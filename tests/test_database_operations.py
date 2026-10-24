"""Every operation states which rows it reaches, what it writes, and what it returns.

FxRates ``20261023.234755``: the source rule "a stored (date, currency) is replaced" had no
operation that could express it, because ``update`` matched only the primary key and no verb
inserted-or-replaced. The plan stalled on a Blueprint that could not state its own acceptance.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from drydock.database_apply import apply_schema
from drydock.database_contract import (
    database_contract_defects,
    operation_surface,
    resolved_operations,
)
from drydock.database_emit import PACKAGE, write_persistence_package
from drydock.database_schema import compact_declaration
from tests.test_database_emit import _run_in_build
from tests.test_database_go import go_env  # noqa: F401 - fixture


def _type(name: str) -> str:
    return "INTEGER" if name == "id" else "TEXT"


def _pattern(
    ident: str, operation: str, inputs: str, output: str, match: str = "", dto: str = "Rate"
) -> str:
    match_row = f"| Match | {match} |\n" if match else ""
    output_rows = "".join(f"| {name} | {_type(name)} |\n" for name in output.split())
    input_rows = "".join(f"| {name} | {_type(name)} | yes |\n" for name in inputs.split())
    return (
        f"### {ident} — {operation}\n\n| Field | Value |\n|---|---|\n"
        f"| Owner | FEATURE-RateStorage.md |\n| Access | write |\n"
        f"| Repository operation | `{operation}` |\n{match_row}| Compatibility | unchanged |\n\n"
        f"Input: In\n\n| Field | Type | Required |\n|---|---|---|\n{input_rows}\n"
        f"Output: {dto}\n\n| Field | Type |\n|---|---|\n{output_rows}\n"
    )


_ROW = "id date currency rate"
_PATTERNS = {
    "create": _pattern("FEATURE-RATE-001", "rates.create", "date currency rate", _ROW),
    "get": _pattern("FEATURE-RATE-002", "rates.get", "date currency", _ROW, "`date`, `currency`"),
    "list": _pattern("FEATURE-RATE-003", "rates.list", "currency", _ROW),
    "upsert": _pattern(
        "FEATURE-RATE-004", "rates.upsert", "date currency rate", _ROW, "`date`, `currency`"
    ),
    "update": _pattern("FEATURE-RATE-005", "rates.update", "currency rate", "", "`currency`"),
    "delete": _pattern("FEATURE-RATE-006", "rates.delete", "id", "id", dto="RateKey"),
}
_SCHEMA = """## `rates`

| Field | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| date | TEXT NOT NULL | |
| currency | TEXT NOT NULL | |
| rate | TEXT NOT NULL | |

- UNIQUE (date, currency)
"""


def _declaration(**replace: str) -> str:
    patterns = {**_PATTERNS, **replace}
    return (
        "# DATABASE: FxRates\n\n## Access Patterns\n\n"
        + "".join(item for item in patterns.values() if item)
        + "## Schemas\n\n"
        + _SCHEMA
    )


def test_the_fxrates_surface_is_a_valid_declaration():
    assert database_contract_defects(_declaration()) == ()


def test_each_operation_resolves_its_rows_and_writes():
    shapes = {
        item.verb: (item.match, item.filters, item.sets, item.many)
        for item in resolved_operations(_declaration())
    }

    assert shapes["get"] == (("date", "currency"), (), (), False)
    assert shapes["list"] == ((), ("currency",), (), True)
    assert shapes["create"] == ((), (), ("date", "currency", "rate"), False)
    assert shapes["upsert"] == (("date", "currency"), (), ("rate",), False)
    assert shapes["update"] == (("currency",), (), ("rate",), True)
    assert shapes["delete"] == (("id",), (), (), False)


def test_an_update_without_a_match_row_matches_the_primary_key():
    declared = _declaration(update=_pattern("FEATURE-RATE-005", "rates.update", "id rate", _ROW))
    update = next(item for item in resolved_operations(declared) if item.verb == "update")

    assert database_contract_defects(declared) == ()
    assert (update.match, update.sets, update.many) == (("id",), ("rate",), False)


def test_the_surface_states_every_call_match_and_return():
    surface = operation_surface(_declaration())

    assert "### `rates`" in surface
    assert "Unique keys: (`id`), (`date`, `currency`)" in surface
    assert (
        "| FEATURE-RATE-004 | `db.rates.upsert(date, currency, rate)` | `date`, `currency` | "
        "`rate` | 1 | `Rate` |" in surface
    )
    assert (
        "| FEATURE-RATE-005 | `db.rates.update(currency, rate)` | `currency` | `rate` | 0..n | count |"
        in surface
    )
    assert (
        "| FEATURE-RATE-003 | `db.rates.list(currency?)` | `currency`? | — | 0..n | list of `Rate` |"
        in surface
    )
    assert (
        "| FEATURE-RATE-002 | `db.rates.get(date, currency)` | `date`, `currency` | — | 0..1 | `Rate` or None |"
        in surface
    )


def test_the_compact_declaration_carries_the_surface():
    assert "## Operation Surface" in compact_declaration(_declaration())


@pytest.mark.parametrize(
    ("replace", "message"),
    [
        (
            {"get": _pattern("FEATURE-RATE-002", "rates.get", "currency", _ROW, "`currency`")},
            "identifies no single row of `rates`",
        ),
        (
            {"upsert": _pattern("FEATURE-RATE-004", "rates.upsert", "date currency rate", _ROW)},
            "names exactly one unique key of `rates`",
        ),
        (
            {
                "upsert": _pattern(
                    "FEATURE-RATE-004", "rates.upsert", "date currency", _ROW, "`date`, `currency`"
                )
            },
            "missing `rate`",
        ),
        (
            {
                "update": _pattern(
                    "FEATURE-RATE-005", "rates.update", "currency rate", _ROW, "`currency`"
                )
            },
            "reaches many rows and returns their count",
        ),
        (
            {"update": _pattern("FEATURE-RATE-005", "rates.update", "rate", "", "`currency`")},
            "Match names `currency`, which is not Input fields",
        ),
        (
            {"update": _pattern("FEATURE-RATE-005", "rates.update", "currency", "", "`currency`")},
            "sets nothing",
        ),
        (
            {
                "create": _pattern(
                    "FEATURE-RATE-001", "rates.create", "date currency rate", _ROW, "`date`"
                )
            },
            "declares no Match",
        ),
        (
            {
                "delete": _pattern(
                    "FEATURE-RATE-006", "rates.delete", "id currency", "", "`id`", "RateKey"
                )
            },
            "its Input fields are exactly its Match fields",
        ),
        (
            {"extra": _pattern("FEATURE-RATE-007", "rates.list", "date", _ROW)},
            "which FEATURE-RATE-003 already declares",
        ),
    ],
)
def test_an_operation_the_runtime_cannot_honor_exactly_is_a_defect(replace, message):
    defects = database_contract_defects(_declaration(**replace))

    assert len(defects) == 1, defects
    assert message in defects[0]


def test_python_operations_reach_the_declared_rows(tmp_path: Path):
    blueprint_dir = tmp_path / "blueprint"
    build_dir = tmp_path / "build"
    blueprint_dir.mkdir()
    (blueprint_dir / "DATABASE.md").write_text(_declaration(), encoding="utf-8")
    write_persistence_package(blueprint_dir, build_dir)
    script = f"""
from {PACKAGE} import PersistenceError, open_database
db = open_database("app.db")
db.execute_script(open("schema.sql").read())
first = db.rates.upsert(date="2025-01-31", currency="USD", rate="1.0393")
again = db.rates.upsert(date="2025-01-31", currency="USD", rate="1.0400")
assert (again.id, again.rate) == (first.id, "1.0400"), again
assert len(db.rates.list(currency="USD")) == 1
assert db.rates.get(date="2025-01-31", currency="USD").rate == "1.0400"
db.rates.create(date="2025-01-30", currency="USD", rate="1.0403")
db.rates.create(date="2025-01-30", currency="JPY", rate="161.00")
assert db.rates.update(currency="USD", rate="9") == 2
assert {{row.rate for row in db.rates.list(currency="USD")}} == {{"9"}}
assert db.rates.list(currency="JPY")[0].rate == "161.00"
try:
    db.rates.get(date="2025-01-31")
except PersistenceError as exc:
    assert "requires currency" in str(exc)
else:
    raise AssertionError("a get missing a Match field ran")
print("OPERATIONS OK")
"""
    result = _run_in_build(build_dir, script)

    assert result.returncode == 0, result.stderr
    assert "OPERATIONS OK" in result.stdout


def test_go_operations_reach_the_declared_rows(tmp_path, go_env):  # noqa: F811
    if not shutil.which("gcc"):
        pytest.skip("C compiler required for Go SQLite")
    go_env = dict(go_env)
    go_env.pop("DRYDOCK_TEST_POSTGRES_DSN", None)
    blueprint = tmp_path / "blueprint"
    blueprint.mkdir()
    (blueprint / "DATABASE.md").write_text(_declaration())
    build = tmp_path / "build"
    build.mkdir()
    (build / "go.mod").write_text("module example.test/target\n\ngo 1.22\n")
    from drydock.technology_stack import StackEntry, write

    write(tmp_path, [StackEntry("Go", "go.md"), StackEntry("SQLite", "sqlite.md")])
    write_persistence_package(blueprint, build)
    assert apply_schema(build, env=go_env).applied
    (build / "store_test.go").write_text("""package target
import (
 "context"
 "os"
 "testing"
 "drydock.local/persistence"
)
func TestOperations(t *testing.T) {
 ctx:=context.Background()
 db,cleanup,err:=persistence.OpenSession(ctx,os.Getenv("DATABASE_URL"))
 if err!=nil {t.Fatal(err)};defer func(){if err:=cleanup();err!=nil {t.Error(err)}}()
 day,usd,jpy,r1,r2,r3:="2025-01-31","USD","JPY","1.0393","1.0400","161.00"
 first,err:=db.Rates.Upsert(ctx,persistence.RatesUpsertInput{Date:day,Currency:usd,Rate:r1})
 if err!=nil || first==nil {t.Fatalf("upsert: %v %v",first,err)}
 again,err:=db.Rates.Upsert(ctx,persistence.RatesUpsertInput{Date:day,Currency:usd,Rate:r2})
 if err!=nil || again==nil || again.Id!=first.Id || again.Rate!=r2 {t.Fatalf("replace: %v %v",again,err)}
 if _,err:=db.Rates.Create(ctx,persistence.RatesCreateInput{Date:day,Currency:jpy,Rate:r3});err!=nil {t.Fatal(err)}
 nine:="9"
 count,err:=db.Rates.Update(ctx,persistence.RatesUpdateInput{Currency:usd,Rate:nine})
 if err!=nil || count!=1 {t.Fatalf("update many: %v %v",count,err)}
 row,err:=db.Rates.Get(ctx,persistence.RatesGetInput{Date:day,Currency:jpy})
 if err!=nil || row==nil || row.Rate!=r3 {t.Fatalf("get: %v %v",row,err)}
}
""")
    result = subprocess.run(
        ["go", "test", "./..."], cwd=build, env=go_env, capture_output=True, text=True, timeout=180
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_rigging_compaction_splices_the_generated_surface(tmp_path: Path):
    # The model's summary never stands in for the surface: it is spliced in verbatim.
    from drydock.rigging_compact import compact
    from tests.test_rigging_compact import _blueprint, fake_runner

    name, root = _blueprint(tmp_path, **{"DATABASE.md": _declaration()})
    result = compact(name, root / name, runner=fake_runner())

    assert result.exit_code() == 0
    written = (root / name / "DATABASE_compact.md").read_text(encoding="utf-8")
    assert operation_surface(_declaration()).strip() in written
