"""Every operation states its name, which rows it reaches, what it takes, and what it returns.

FxRates ``20261023.234755``: the source rule "a stored (date, currency) is replaced" had no
operation that could express it, because ``update`` matched only the primary key and no verb
inserted-or-replaced. The plan stalled on a Blueprint that could not state its own acceptance.
An operation is a named method with a Kind, so a table may carry several of one Kind, and its
fingerprint moves only when what a caller depends on moves.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from drydock.database_apply import apply_schema
from drydock.database_contract import (
    _legacy_operation_fingerprints,
    changed_operation_contracts,
    database_contract_defects,
    database_operation_fingerprints,
    operation_sql,
    operation_surface,
    parse_database_operation_fingerprints,
    resolved_operations,
    sqlite_schema_tables,
)
from drydock.database_emit import PACKAGE, write_persistence_package
from drydock.database_schema import compact_declaration
from tests.test_database_emit import _run_in_build
from tests.test_database_go import go_env  # noqa: F401 - fixture


def _type(name: str) -> str:
    return "INTEGER" if name == "id" else "TEXT"


def _pattern(
    ident: str,
    operation: str,
    inputs: str,
    output: str,
    match: str = "",
    dto: str = "Rate",
    kind: str = "",
) -> str:
    match_row = f"| Match | {match} |\n" if match else ""
    kind_row = f"| Kind | {kind} |\n" if kind else ""
    output_rows = "".join(f"| {name} | {_type(name)} |\n" for name in output.split())
    input_rows = "".join(f"| {name} | {_type(name)} | yes |\n" for name in inputs.split())
    return (
        f"### {ident} — {operation}\n\n| Field | Value |\n|---|---|\n"
        f"| Owner | FEATURE-RateStorage.md |\n| Access | write |\n"
        f"| Repository operation | `{operation}` |\n{kind_row}{match_row}"
        f"| Compatibility | unchanged |\n\n"
        f"Input: In\n\n| Field | Type | Required |\n|---|---|---|\n{input_rows}\n"
        f"Output: {dto}\n\n| Field | Type |\n|---|---|\n{output_rows}\n"
    )


_ROW = "id date currency rate"
_DC = "`date`, `currency`"
_PATTERNS = {
    "create": _pattern("FEATURE-RATE-001", "rates.create", "date currency rate", _ROW),
    "get": _pattern("FEATURE-RATE-002", "rates.get", "date currency", _ROW, _DC),
    "list": _pattern("FEATURE-RATE-003", "rates.list", "currency", _ROW),
    "replace": _pattern(
        "FEATURE-RATE-004", "rates.replace_rate", "date currency rate", _ROW, _DC, kind="upsert"
    ),
    "reprice": _pattern(
        "FEATURE-RATE-005",
        "rates.reprice_currency",
        "currency rate",
        "",
        "`currency`",
        kind="update",
    ),
    "update": _pattern("FEATURE-RATE-006", "rates.update", "id rate", _ROW),
    "delete": _pattern("FEATURE-RATE-007", "rates.delete", "id", "id", dto="RateKey"),
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


def _declaration(schema: str = _SCHEMA, **replace: str) -> str:
    patterns = {**_PATTERNS, **replace}
    return (
        "# DATABASE: FxRates\n\n## Access Patterns\n\n"
        + "".join(item for item in patterns.values() if item)
        + "## Schemas\n\n"
        + schema
    )


def _block(surface: str, heading: str) -> str:
    return surface.split(f"#### `db.{heading}`", 1)[1].split("####", 1)[0]


def test_the_fxrates_surface_is_a_valid_declaration():
    assert database_contract_defects(_declaration()) == ()


def test_each_operation_resolves_its_name_kind_rows_and_writes():
    shapes = {
        item.operation: (item.verb, item.match, item.filters, item.sets, item.many)
        for item in resolved_operations(_declaration())
    }

    assert shapes["rates.get"] == ("get", ("date", "currency"), (), (), False)
    assert shapes["rates.list"] == ("list", (), ("currency",), (), True)
    assert shapes["rates.create"] == ("create", (), (), ("date", "currency", "rate"), False)
    assert shapes["rates.replace_rate"] == ("upsert", ("date", "currency"), (), ("rate",), False)
    assert shapes["rates.reprice_currency"] == ("update", ("currency",), (), ("rate",), True)
    assert shapes["rates.update"] == ("update", ("id",), (), ("rate",), False)
    assert shapes["rates.delete"] == ("delete", ("id",), (), (), False)


def test_the_surface_states_each_call_its_json_and_its_sql():
    surface = operation_surface(_declaration())

    assert "Unique keys: (`id`), (`date`, `currency`)" in surface
    replace = _block(surface, "rates.replace_rate")
    assert "| upsert | 1 | `date`, `currency` | `rate` | `" in replace
    assert '- Input: `{"date": "str", "currency": "str", "rate": "str"}`' in replace
    assert '- Output: `{"id": "int", "date": "str", "currency": "str", "rate": "str"}`' in replace
    assert (
        'INSERT INTO "rates" ("date", "currency", "rate") VALUES (?, ?, ?) '
        'ON CONFLICT ("date", "currency") DO UPDATE SET "rate" = excluded."rate";' in replace
    )
    reprice = _block(surface, "rates.reprice_currency")
    assert "| update | 0..n | `currency` | `rate` |" in reprice
    assert '- Input: `{"currency": "str", "rate": "str?"}`' in reprice
    assert '- Output: `"int" (rows changed)`' in reprice
    assert 'UPDATE "rates" SET "rate" = ? WHERE "currency" = ?;' in reprice
    assert '- Input: `{"currency": "str?"}`' in _block(surface, "rates.list")


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
            {
                "replace": _pattern(
                    "FEATURE-RATE-004",
                    "rates.replace_rate",
                    "date currency rate",
                    _ROW,
                    kind="upsert",
                )
            },
            "names exactly one unique key of `rates`",
        ),
        (
            {
                "replace": _pattern(
                    "FEATURE-RATE-004",
                    "rates.replace_rate",
                    "date currency",
                    _ROW,
                    _DC,
                    kind="upsert",
                )
            },
            "missing `rate`",
        ),
        (
            {
                "reprice": _pattern(
                    "FEATURE-RATE-005",
                    "rates.reprice_currency",
                    "currency rate",
                    _ROW,
                    "`currency`",
                    kind="update",
                )
            },
            "reaches many rows and returns their count",
        ),
        (
            {"update": _pattern("FEATURE-RATE-006", "rates.update", "rate", _ROW, "`id`")},
            "Match names `id`, which is not Input fields",
        ),
        (
            {"update": _pattern("FEATURE-RATE-006", "rates.update", "id", _ROW)},
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
                    "FEATURE-RATE-007", "rates.delete", "id currency", "", "`id`", "RateKey"
                )
            },
            "its Input fields are exactly its Match fields",
        ),
        (
            {"extra": _pattern("FEATURE-RATE-008", "rates.list", "date", _ROW)},
            "which FEATURE-RATE-003 already declares",
        ),
        (
            {
                "extra": _pattern(
                    "FEATURE-RATE-008", "rates.find_by_currency", "currency", _ROW, kind="list"
                )
            },
            "runs exactly what FEATURE-RATE-003 runs",
        ),
    ],
)
def test_an_operation_the_runtime_cannot_honor_exactly_is_a_defect(replace, message):
    defects = database_contract_defects(_declaration(**replace))

    assert len(defects) == 1, defects
    assert message in defects[0]


@pytest.mark.parametrize(
    ("operation", "kind", "message"),
    [
        ("rates.replace_rate", "", "declares `| Kind | <kind> |`"),
        ("rates.replace_rate", "merge", "invalid Kind 'merge'"),
        ("rates.get", "list", "A verb name is its own Kind"),
    ],
)
def test_a_named_operation_states_a_valid_kind(operation, kind, message):
    replaced = _pattern("FEATURE-RATE-004", operation, "date currency rate", _ROW, _DC, kind=kind)
    defects = database_contract_defects(_declaration(replace=replaced, get=""))

    assert any(message in defect for defect in defects), defects


def _fingerprints(text: str) -> dict[str, str]:
    return parse_database_operation_fingerprints(database_operation_fingerprints(text))


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("| rate | TEXT NOT NULL | |", "| rate | VARCHAR(40) NOT NULL | |"),
        ("| rate | TEXT NOT NULL | |", "| rate | TEXT | |"),
        ("| rate | TEXT NOT NULL | |", "| rate | TEXT NOT NULL DEFAULT '0' | |"),
    ],
)
def test_a_storage_change_moves_no_contract(old, new):
    assert _fingerprints(_declaration(_SCHEMA.replace(old, new))) == _fingerprints(_declaration())


def test_a_field_length_or_required_change_in_a_dto_moves_no_contract():
    widened = _declaration().replace("| rate | TEXT | yes |", "| rate | VARCHAR(12) | no |")

    assert _fingerprints(widened) == _fingerprints(_declaration())


def test_a_caller_facing_change_moves_exactly_that_contract():
    baseline = _fingerprints(_declaration())
    retyped = _fingerprints(
        _declaration(update=_pattern("FEATURE-RATE-006", "rates.update", "id rate", "id rate"))
    )
    renamed = _fingerprints(
        _declaration(replace=_PATTERNS["replace"].replace("rates.replace_rate", "rates.store_rate"))
    )

    assert {key for key in baseline if baseline[key] != retyped[key]} == {"FEATURE-RATE-006"}
    assert {key for key in baseline if baseline[key] != renamed[key]} == {"FEATURE-RATE-004"}


def test_a_manifest_recorded_with_the_legacy_fingerprint_reads_unchanged():
    text = _declaration()
    legacy = parse_database_operation_fingerprints(_legacy_operation_fingerprints(text))

    assert changed_operation_contracts(legacy, text) == set()
    assert changed_operation_contracts({**legacy, "FEATURE-RATE-001": "0" * 64}, text) == {
        "FEATURE-RATE-001"
    }


def _built(tmp_path: Path) -> Path:
    blueprint_dir = tmp_path / "blueprint"
    build_dir = tmp_path / "build"
    blueprint_dir.mkdir()
    (blueprint_dir / "DATABASE.md").write_text(_declaration(), encoding="utf-8")
    write_persistence_package(blueprint_dir, build_dir)
    return build_dir


def test_python_operations_reach_the_declared_rows(tmp_path: Path):
    script = f"""
from {PACKAGE} import PersistenceError, open_database
db = open_database("app.db")
db.execute_script(open("schema.sql").read())
first = db.rates.replace_rate(date="2025-01-31", currency="USD", rate="1.0393")
again = db.rates.replace_rate(date="2025-01-31", currency="USD", rate="1.0400")
assert (again.id, again.rate) == (first.id, "1.0400"), again
assert len(db.rates.list(currency="USD")) == 1
assert db.rates.get(date="2025-01-31", currency="USD").rate == "1.0400"
db.rates.create(date="2025-01-30", currency="USD", rate="1.0403")
db.rates.create(date="2025-01-30", currency="JPY", rate="161.00")
assert db.rates.reprice_currency(currency="USD", rate="9") == 2
assert {{row.rate for row in db.rates.list(currency="USD")}} == {{"9"}}
assert db.rates.update(id=first.id, rate="8").rate == "8"
assert db.rates.list(currency="JPY")[0].rate == "161.00"
try:
    db.rates.get(date="2025-01-31")
except PersistenceError as exc:
    assert "requires currency" in str(exc)
else:
    raise AssertionError("a get missing a Match field ran")
print("OPERATIONS OK")
"""
    result = _run_in_build(_built(tmp_path), script)

    assert result.returncode == 0, result.stderr
    assert "OPERATIONS OK" in result.stdout


def test_the_surface_sql_is_the_sql_the_runtime_builds(tmp_path: Path):
    text = _declaration()
    table = sqlite_schema_tables(text)[0]
    expected = {item.name: list(operation_sql(item, table)) for item in resolved_operations(text)}
    calls = {
        "create": {"date": "2025-01-01", "currency": "USD", "rate": "1"},
        "get": {"date": "2025-01-01", "currency": "USD"},
        "list": {"currency": "USD"},
        "replace_rate": {"date": "2025-01-01", "currency": "USD", "rate": "2"},
        "reprice_currency": {"currency": "USD", "rate": "3"},
        "update": {"id": 1, "rate": "4"},
        "delete": {"id": 1},
    }
    script = f"""
import json
from {PACKAGE} import open_database
db = open_database("app.db")
db.execute_script(open("schema.sql").read())
driver = db.driver
built, depth = [], [0]
def recorded(original):
    # Only the statement the runtime executes is kept; upsert builds its INSERT internally.
    def call(*args, **kwargs):
        depth[0] += 1
        try:
            statement = original(*args, **kwargs)
        finally:
            depth[0] -= 1
        if not depth[0]:
            built.append(statement)
        return statement
    return call
for method in ("select", "insert", "update", "upsert", "delete"):
    setattr(driver, method, recorded(getattr(driver, method)))
seen = {{}}
for name, arguments in json.loads({json.dumps(json.dumps(calls))}).items():
    built.clear()
    getattr(db.rates, name)(**arguments)
    seen[name] = list(built)
print(json.dumps(seen))
"""
    result = _run_in_build(_built(tmp_path), script)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == expected


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
 first,err:=db.Rates.ReplaceRate(ctx,persistence.RatesReplaceRateInput{Date:day,Currency:usd,Rate:r1})
 if err!=nil || first==nil {t.Fatalf("replace: %v %v",first,err)}
 again,err:=db.Rates.ReplaceRate(ctx,persistence.RatesReplaceRateInput{Date:day,Currency:usd,Rate:r2})
 if err!=nil || again==nil || again.Id!=first.Id || again.Rate!=r2 {t.Fatalf("again: %v %v",again,err)}
 if _,err:=db.Rates.Create(ctx,persistence.RatesCreateInput{Date:day,Currency:jpy,Rate:r3});err!=nil {t.Fatal(err)}
 nine:="9"
 count,err:=db.Rates.RepriceCurrency(ctx,persistence.RatesRepriceCurrencyInput{Currency:usd,Rate:nine})
 if err!=nil || count!=1 {t.Fatalf("reprice: %v %v",count,err)}
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
