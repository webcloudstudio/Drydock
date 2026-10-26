"""Declared-order and server-readiness regressions; all fixtures are synthetic."""

import pytest

from drydock.acceptance import ProgrammaticAcceptance
from drydock.acceptance_oracle import ordered_expectation_defects, process_readiness_defect
from drydock.plan_verify import verify

_DATABASE = """# DATABASE: Demo

## Access Patterns

### FEATURE-RATE-001 — List stored rates

| Field | Value |
|---|---|
| Owner | FEATURE-Rates.md |
| Access | read |
| Repository operation | rates.list |
| Compatibility | unchanged |
| Order | date asc, currency asc |

Input: ListRates

| Field | Type |
|---|---|
| (none) | — |

Output: Rate

| Field | Type |
|---|---|
| date | str |
| currency | str |
| rate | str |

## `rates`

| Field | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| date | TEXT | |
| currency | TEXT | |
| rate | TEXT | |
"""
_CODE = """from persistence.testing import db_session
currency = "ZZZ"
other_currency = "YYY"
with db_session() as db:
    rows = db.rates.list()
assert [(row.date, row.currency, row.rate) for row in rows] == [
    ("2099-01-01", currency, "1.00"),
    ("2099-01-01", other_currency, "8.00"),
]
"""
_PROCESS = """import subprocess
process = subprocess.Popen(["./demo", "serve"])
try:
    assert process.poll() is None
finally:
    process.terminate()
    process.wait(timeout=10)
"""


def check(code=_CODE):
    return ProgrammaticAcceptance("ordered", "DATABASE.md", "Ordered rates", code)


def test_declared_secondary_sort_key_refuses_inverted_expected_fixture():
    from drydock.database_contract import parse_database_contract

    assert parse_database_contract(_DATABASE).patterns[0].order == (
        ("date", "asc"),
        ("currency", "asc"),
    )
    reasons = ordered_expectation_defects(check(), _DATABASE)
    assert len(reasons) == 1
    assert "rates.list Order (date asc, currency asc)" in reasons[0]
    assert not ordered_expectation_defects(
        check(), _DATABASE.replace("currency asc", "currency desc")
    )
    correct = _CODE.replace('currency = "ZZZ"', 'currency = "AAA"')
    assert not ordered_expectation_defects(check(correct), _DATABASE)


@pytest.mark.parametrize(
    "code",
    [
        _CODE.replace('currency = "ZZZ"', "currency = load_currency()"),
        _CODE.replace('currency = "ZZZ"', 'currency = "AAA"\ncurrency = load_currency()'),
        _CODE.replace("== [", "== sorted([").replace("]\n", "])\n"),
        _CODE.replace("db.rates.list()", "db.rates.get()"),
        _CODE.replace("row.currency, row.rate", "row.rate"),
    ],
)
def test_unknown_runtime_values_and_derived_oracles_are_not_executed_or_guessed(code):
    assert not ordered_expectation_defects(check(code), _DATABASE)


def test_ordered_oracle_checks_fixture_aliases_without_executing_proof():
    code = _CODE.replace('currency = "ZZZ"', 'values = ["ZZZ"]\ncurrency = values[0]')
    assert ordered_expectation_defects(check(code), _DATABASE)
    assert not ordered_expectation_defects(check(code), "not a database declaration")


def test_verify_and_admission_share_the_ordering_gate(tmp_path):
    from drydock.planning_session import CriteriaDefect, _validate_plan_output
    from tests.test_planning_session import _SPEC_HEADER, FakeRun, _llm_output, _manifest

    blueprint = tmp_path / "blueprint"
    blueprint.mkdir()
    body = (
        "# DATABASE: Demo\n\n## Programmatic Acceptance\n\n=== AC ordered ===\n"
        + _CODE
        + "=== END AC ordered ===\n"
    )
    (blueprint / "DATABASE.md").write_text(_DATABASE + body)
    assert any(d.kind == "ordered-oracle" for d in verify("Demo", tmp_path).defects)
    manifest = _manifest()
    blocks = {
        "ARCHITECTURE.md": _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None."),
        "DATABASE.md": _DATABASE,
        "FEATURE-Status.md": body.replace("# DATABASE: Demo", "# FEATURE: Status"),
        "MANIFEST.md": manifest,
    }
    with pytest.raises(CriteriaDefect) as raised:
        _validate_plan_output(blocks, blueprint, FakeRun(text=_llm_output(manifest)))
    assert any(kind == "ordered-oracle" for kind, _ in raised.value.defects)


def test_immediate_spawn_poll_is_refused_but_a_readiness_probe_is_allowed():
    assert process_readiness_defect(_PROCESS)
    bounded = _PROCESS.replace(
        "    assert process.poll() is None",
        """    from urllib.request import urlopen
    import time
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            with urlopen("http://127.0.0.1:8000/health", timeout=0.2) as response:
                assert response.status == 200
                break
        except OSError:
            assert process.poll() is None
            time.sleep(0.05)
    else:
        raise AssertionError("service did not become ready")""",
    )
    assert not process_readiness_defect(bounded)
    assert not process_readiness_defect(
        'import subprocess\nassert subprocess.run(["demo"]).returncode == 0'
    )


def test_mechanical_repair_preserves_order_and_readiness_intent(tmp_path):
    from drydock.plan_repair import repair

    blueprint = tmp_path / "blueprint"
    blueprint.mkdir()
    (blueprint / "DATABASE.md").write_text(_DATABASE)
    original = (
        "# FEATURE: Rates\n\n## Programmatic Acceptance\n\n=== AC ordered ===\n"
        + _CODE
        + "=== END AC ordered ===\n=== AC serve ===\n"
        + _PROCESS
        + "=== END AC serve ===\n"
    )
    path = blueprint / "FEATURE-Rates.md"
    path.write_text(original)

    def runner(*args, **kwargs):
        raise AssertionError("mechanical repair must not rewrite acceptance intent")

    outcome = repair("Demo", tmp_path, runner=runner)
    assert not outcome.ok
    assert path.read_text() == original
    assert {item.check_id for item in outcome.outstanding} >= {"ordered", "serve"}


def test_mutated_expected_sequences_are_left_for_runtime_verification():
    code = _CODE.replace(
        "assert [(row.date",
        'expected = [("2099-01-01", currency, "1.00"), ("2099-01-01", other_currency, "8.00")]\nexpected.reverse()\nassert [(row.date',
    )
    code = code[: code.index(" == [")] + " == expected\n"
    assert not ordered_expectation_defects(check(code), _DATABASE)


def test_function_local_fixture_values_do_not_leak_into_module_oracles():
    code = _CODE.replace(
        'currency = "ZZZ"',
        'from app import currency\ndef helper():\n    currency = "ZZZ"\n    return currency',
    )
    assert not ordered_expectation_defects(check(code), _DATABASE)


def test_verify_and_admission_reject_immediate_spawn_only_readiness(tmp_path):
    from drydock.planning_session import CriteriaDefect, _validate_plan_output
    from tests.test_planning_session import _SPEC_HEADER, FakeRun, _llm_output, _manifest

    blueprint = tmp_path / "blueprint"
    blueprint.mkdir()
    body = (
        "# FEATURE: Status\n\n## Programmatic Acceptance\n\n=== AC serve ===\n"
        + _PROCESS
        + "=== END AC serve ===\n"
    )
    (blueprint / "FEATURE-Status.md").write_text(body)
    assert any(d.kind == "process-readiness" for d in verify("Demo", tmp_path).defects)
    manifest = _manifest()
    blocks = {
        "ARCHITECTURE.md": _SPEC_HEADER.format(ftype="ARCHITECTURE", name="Example", ac="None."),
        "FEATURE-Status.md": body,
        "MANIFEST.md": manifest,
    }
    with pytest.raises(CriteriaDefect) as raised:
        _validate_plan_output(blocks, blueprint, FakeRun(text=_llm_output(manifest)))
    assert any(kind == "process-readiness" for kind, _ in raised.value.defects)


def test_numeric_storage_with_string_projection_is_not_assumed_lexicographic():
    numeric = _DATABASE.replace("| currency | TEXT | |", "| currency | NUMERIC | |")
    code = _CODE.replace('"ZZZ"', '"10"').replace('"YYY"', '"2"')
    assert not ordered_expectation_defects(check(code), numeric)
