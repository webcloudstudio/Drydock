"""Tests for comparing a criterion's expected exit with the staged harness's expectation."""

from __future__ import annotations

from drydock.harness_exits import contradictions, criterion_calls, load_harness
from drydock.plan_verify import verify
from drydock.prompts import load_prompt

#: The LayersTesting ``run.sh`` shape: ``check <id> <exit> <args...> <<'EOF'``.
_RUN_SH = """#!/usr/bin/env bash
SEED=sources
check A1 0 init
check B2 0 load categories "$SEED/seed_categories.csv" <<'EOF'
table,loaded
categories,7
EOF
check C4 3 load categories "$SEED/seed_categories.csv"   # duplicate keys
check D1 4 txn get 999
check G5 3 txn delete 1 < /dev/null
"""

#: LayersTesting ``20261020.183046`` ``transaction-post-read``, reduced.
_CONTRADICTING = """from cli.testing import cli_runner

category = "SALES"
assert cli_runner("init")[0] == 0
assert cli_runner("load", "categories", "sources/seed_categories.csv")[0] == 1
assert cli_runner("txn", "post", "CASH9", category, "45.50")[0] == 3
"""


def _sources(tmp_path, text=_RUN_SH):
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "run.sh").write_text(text, encoding="utf-8")
    (sources / "seed_categories.csv").write_text("code,name\n", encoding="utf-8")
    return load_harness(sources)


def test_harness_lines_yield_the_arguments_after_their_exit(tmp_path):
    found = _sources(tmp_path).expectations

    b2 = [line for line in found if line.line == 4]
    assert (("load", "categories", "$SEED/seed_categories.csv"), 0) in {
        (line.argv, line.exit_code) for line in b2
    }
    # The heredoc redirection ends the command.
    assert all("<<" not in "".join(line.argv) for line in found)
    # The trailing comment is not an argument.
    assert all("duplicate" not in line.argv for line in found)


def test_criterion_calls_read_literal_and_bound_arguments_in_source_order():
    calls = criterion_calls(_CONTRADICTING)

    assert [(call.argv, call.exit_code) for call in calls] == [
        (("init",), 0),
        (("load", "categories", "sources/seed_categories.csv"), 1),
        (("txn", "post", "CASH9", "SALES", "45.50"), 3),
    ]


def test_an_exit_the_harness_does_not_expect_is_a_contradiction(tmp_path):
    (found,) = contradictions(_CONTRADICTING, _sources(tmp_path))

    call, line = found
    assert call.exit_code == 1
    assert line.exit_code == 0
    assert (line.source, line.line) == ("run.sh", 4)


def test_only_the_first_call_of_a_command_is_compared(tmp_path):
    """A second load is a duplicate: its exit depends on the setup, not on the harness line."""
    code = """from cli.testing import cli_runner

assert cli_runner("load", "categories", "sources/seed_categories.csv")[0] == 0
assert cli_runner("load", "categories", "sources/seed_categories.csv")[0] == 1
"""
    assert contradictions(code, _sources(tmp_path)) == []


def test_an_exit_any_matching_harness_line_expects_is_not_a_contradiction(tmp_path):
    code = """from cli.testing import cli_runner

assert cli_runner("load", "categories", "sources/seed_categories.csv")[0] == 3
"""
    assert contradictions(code, _sources(tmp_path)) == []


def test_a_call_addressing_state_is_not_compared(tmp_path):
    """Run ``20261020.191708``: the harness rejects ``txn delete 1`` at its point in the sequence,
    while a criterion deleting its own fresh transaction correctly expects ``0``."""
    code = """from cli.testing import cli_runner

assert cli_runner("txn", "delete", "1")[0] == 0
"""
    assert contradictions(code, _sources(tmp_path)) == []


def test_unrecognized_shapes_yield_nothing(tmp_path):
    code = """from cli.testing import cli_runner

path = make_path()
code, out, err = cli_runner("txn", "get", "999")
assert code == 2
assert cli_runner("load", "categories", path)[0] == 1
"""
    assert contradictions(code, _sources(tmp_path)) == []
    assert load_harness(tmp_path / "absent").expectations == ()


def test_plan_verify_reports_a_harness_contradiction_for_repair(tmp_path):
    target = tmp_path / "Demo"
    blueprint = target / "blueprint"
    blueprint.mkdir(parents=True)
    (blueprint / "sources").mkdir()
    (blueprint / "sources" / "run.sh").write_text(_RUN_SH, encoding="utf-8")
    (blueprint / "sources" / "seed_categories.csv").write_text("code,name\n", encoding="utf-8")
    (blueprint / "FEATURE-TRANSACTIONS.md").write_text(
        "# FEATURE: Transactions\n\n## Programmatic Acceptance\n\n"
        "=== AC transaction-post-read ===\nIntent: Posting allocates an id.\n\n"
        f"{_CONTRADICTING}=== END AC transaction-post-read ===\n",
        encoding="utf-8",
    )

    result = verify("Demo", target)

    (defect,) = result.defects
    assert defect.kind == "harness-exit"
    assert defect.check_id == "transaction-post-read"
    assert "`load categories sources/seed_categories.csv` exits 1" in defect.detail
    assert "sources/run.sh:4 expects 0" in defect.detail
    assert result.exit_code() == 1


def test_plan_repair_may_correct_only_a_harness_exit_assertion():
    body = load_prompt("plan_repair").body

    assert "for a `harness-exit` fault, change the named call's expected exit status" in body
    assert "except as\n  permitted above for a `harness-exit` fault" in body
