"""Tests for governed acceptance commands and their classified execution."""

from __future__ import annotations

import json
import sys

import pytest

from drydock.acceptance_contract import (
    FILENAME,
    OUTCOME_ERROR,
    OUTCOME_FAIL,
    OUTCOME_PASS,
    AcceptanceContract,
    contract_from_config,
    load_contract,
    run_gate,
    write_contract,
)
from drydock.errors import SpecificationError


def _target(tmp_path, payload: dict | None = None):
    target = tmp_path / "target"
    build = tmp_path / "build"
    target.mkdir()
    build.mkdir()
    if payload is not None:
        (target / FILENAME).write_text(json.dumps(payload), encoding="utf-8")
    return target, build


# ── the contract ──────────────────────────────────────────────────────────────


def test_an_absent_contract_is_empty_not_an_error(tmp_path):
    """Most Targets declare none. That is a fact about the Target, not a fault."""
    target, _ = _target(tmp_path)

    contract = load_contract(target)

    assert not contract.declared
    assert contract.full == ()
    assert contract.story_gates == {}


def test_a_retired_stages_key_still_loads_as_governed_story_gates(tmp_path):
    target, _ = _target(
        tmp_path,
        {
            "full": ["sh", "sources/full_test.sh"],
            "stages": {"parser-strings": ["sh", "sources/stage_test.sh", "valid/string/**"]},
        },
    )

    contract = load_contract(target)

    assert contract.declared
    assert contract.full == ("sh", "sources/full_test.sh")
    assert contract.story_gate_for("parser-strings") == (
        "parser-strings",
        ("sh", "sources/stage_test.sh", "valid/string/**"),
    )


def test_story_gate_lookup_falls_back_through_the_story_ids_a_block_delivers(tmp_path):
    target, _ = _target(tmp_path, {"stages": {"PARSER-002": ["sh", "x.sh"]}})

    contract = load_contract(target)

    assert contract.story_gate_for("parser-strings", "PARSER-002") == ("PARSER-002", ("sh", "x.sh"))
    assert contract.story_gate_for("parser-keys", "PARSER-003") is None


def test_stable_coverage_selector_takes_precedence_over_generated_story_id(tmp_path):
    target, _ = _target(
        tmp_path,
        {
            "stages": {
                "LEXICAL-001": ["sh", "stable.sh"],
                "lexical-strings": ["sh", "generated.sh"],
            }
        },
    )

    contract = load_contract(target)

    assert contract.story_gate_for("LEXICAL-001", "lexical-strings") == (
        "LEXICAL-001",
        ("sh", "stable.sh"),
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"full": "sh full_test.sh"},
        {"full": []},
        {"full": ["sh", ""]},
        {"stages": ["not", "an", "object"]},
        {"stages": {"a": "not-argv"}},
    ],
)
def test_a_malformed_contract_is_rejected(tmp_path, payload):
    """The contract is the one thing that can close a story verified. It parses strictly."""
    target, _ = _target(tmp_path, payload)

    with pytest.raises(SpecificationError):
        load_contract(target)


def test_unreadable_json_is_rejected(tmp_path):
    target, _ = _target(tmp_path)
    (target / FILENAME).write_text("{not json", encoding="utf-8")

    with pytest.raises(SpecificationError):
        load_contract(target)


def test_a_written_contract_carries_the_release_gate_alone(tmp_path):
    """Story gates belong to STORY_GUIDANCE.json and are not round-tripped through this file."""
    target, _ = _target(tmp_path)
    contract = AcceptanceContract(full=("sh", "t.sh"), story_gates={"a": ("sh", "s.sh")})

    write_contract(target, contract)
    loaded = load_contract(target)

    assert loaded.full == contract.full
    assert loaded.story_gates == {}


def test_a_fixture_declaration_becomes_a_contract():
    contract = contract_from_config(
        {"full": ["sh", "sources/full_test.sh"]}, where="uat/Toml/uat.json"
    )

    assert contract.full == ("sh", "sources/full_test.sh")


def test_no_fixture_declaration_is_an_empty_contract():
    assert not contract_from_config(None, where="uat/Demo/uat.json").declared


# ── classified execution ──────────────────────────────────────────────────────


def test_exit_zero_is_a_product_pass(tmp_path):
    _, build = _target(tmp_path)

    gate = run_gate("full", (sys.executable, "-c", "raise SystemExit(0)"), build_dir=build)

    assert gate.outcome == OUTCOME_PASS
    assert gate.passed
    assert not gate.blocks
    assert gate.return_code == 0


def test_a_nonzero_exit_from_a_command_that_ran_is_a_product_failure(tmp_path):
    _, build = _target(tmp_path)

    gate = run_gate(
        "full", (sys.executable, "-c", "print('12 failed'); raise SystemExit(1)"), build_dir=build
    )

    assert gate.outcome == OUTCOME_FAIL
    assert gate.blocks
    assert "12 failed" in gate.stdout


def test_exit_two_is_a_usage_error_not_a_product_failure(tmp_path):
    """The `diff` and `grep` convention: 1 is a legitimate negative answer, 2 is trouble. A gate
    script exits 2 for an unset variable, a bad argument, or a harness that is not the version the
    run named -- none of which observed the product. Toml 20260813.195530 is the recorded case: a
    version probe refused to run, every gate exited 2, and the release reported the decoder as
    failing when nothing had examined it."""
    _, build = _target(tmp_path)

    gate = run_gate(
        "full",
        (sys.executable, "-c", "import sys; print('usage: ...', file=sys.stderr); sys.exit(2)"),
        build_dir=build,
    )

    assert gate.outcome == OUTCOME_ERROR
    assert not gate.blocks
    assert not gate.passed
    assert gate.return_code == 2
    assert "could not run" in gate.detail


def test_a_missing_command_is_an_error_not_a_product_failure(tmp_path):
    """The harness was absent. Charging that to the build turns a kit fault into a defect."""
    _, build = _target(tmp_path)

    gate = run_gate("full", ("definitely-not-on-this-path-12345",), build_dir=build)

    assert gate.outcome == OUTCOME_ERROR
    assert not gate.blocks
    assert "command not found" in gate.detail


def test_a_timeout_is_an_error(tmp_path):
    _, build = _target(tmp_path)

    gate = run_gate(
        "full", (sys.executable, "-c", "import time; time.sleep(30)"), build_dir=build, timeout=1
    )

    assert gate.outcome == OUTCOME_ERROR
    assert gate.timed_out
    assert not gate.blocks


def test_a_signal_death_is_an_error(tmp_path):
    _, build = _target(tmp_path)

    gate = run_gate(
        "full",
        (sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"),
        build_dir=build,
    )

    assert gate.outcome == OUTCOME_ERROR
    assert "signal 9" in gate.detail
    assert not gate.blocks


def test_a_missing_build_directory_is_an_error(tmp_path):
    target, build = _target(tmp_path)
    build.rmdir()

    gate = run_gate("full", (sys.executable, "-c", "pass"), build_dir=build)

    assert gate.outcome == OUTCOME_ERROR
    assert not gate.blocks


def test_a_verdict_records_the_artifact_it_judged(tmp_path):
    """Without the identity, 'the same suite passed' is an assumption rather than a fact."""
    _, build = _target(tmp_path)
    (build / "main.go").write_text("package main\n", encoding="utf-8")

    first = run_gate("full", (sys.executable, "-c", "pass"), build_dir=build)
    (build / "main.go").write_text("package main // changed\n", encoding="utf-8")
    second = run_gate("full", (sys.executable, "-c", "pass"), build_dir=build)

    assert first.build_identity
    assert first.build_identity != second.build_identity


def test_the_same_artifact_yields_the_same_verdict_twice(tmp_path):
    """The enforceable determinism claim: same artifact and command, same classified result.

    Two *builds* may legitimately differ, so agreement between runs of the build is a quality
    metric rather than a contract. Agreement between two executions of one gate against one tree
    is the property the gate itself must have.
    """
    _, build = _target(tmp_path)
    (build / "marker.txt").write_text("fixed\n", encoding="utf-8")
    argv = (sys.executable, "-c", "raise SystemExit(3)")

    first = run_gate("full", argv, build_dir=build)
    second = run_gate("full", argv, build_dir=build)

    assert (first.outcome, first.return_code, first.argv, first.build_identity) == (
        second.outcome,
        second.return_code,
        second.argv,
        second.build_identity,
    )


def test_the_evidence_record_carries_the_whole_execution(tmp_path):
    _, build = _target(tmp_path)

    payload = run_gate(
        "full", (sys.executable, "-c", "print('out'); raise SystemExit(1)"), build_dir=build
    ).to_dict()

    assert payload["outcome"] == OUTCOME_FAIL
    assert payload["argv"][0] == sys.executable
    assert payload["return_code"] == 1
    assert "out" in payload["stdout"]
    assert payload["build_identity"]


# -- bounded execution --------------------------------------------------------
#
# A gate hands control to the code under test, so the code under test must not be able to end the
# process grading it. These cover the two ways it could: unbounded output and unbounded memory.


def test_a_gate_that_floods_stdout_fails_instead_of_exhausting_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("DRYDOCK_CAPTURE_OUTPUT_LIMIT", "1")
    _, build = _target(tmp_path)

    gate = run_gate(
        "full",
        (
            sys.executable,
            "-c",
            "import sys\nwhile True: sys.stdout.write('x' * 65536)",
        ),
        build_dir=build,
        timeout=60,
    )

    # A product that emits without end is a defective product, not a broken harness.
    assert gate.outcome == OUTCOME_FAIL
    assert gate.blocks
    assert "more than 1 MB on stdout" in gate.detail
    # The captured evidence is bounded, and a little slack is allowed for the chunk in flight
    # when the ceiling was crossed.
    assert len(gate.stdout) <= 1 * 1024 * 1024 + 65536


def test_a_gate_that_floods_stderr_is_also_bounded(tmp_path, monkeypatch):
    monkeypatch.setenv("DRYDOCK_CAPTURE_OUTPUT_LIMIT", "1")
    _, build = _target(tmp_path)

    gate = run_gate(
        "full",
        (
            sys.executable,
            "-c",
            "import sys\nwhile True: sys.stderr.write('x' * 65536)",
        ),
        build_dir=build,
        timeout=60,
    )

    assert gate.outcome == OUTCOME_FAIL
    assert "on stderr" in gate.detail


def test_a_capture_limit_of_zero_lifts_the_output_bound(tmp_path, monkeypatch):
    monkeypatch.setenv("DRYDOCK_CAPTURE_OUTPUT_LIMIT", "0")
    _, build = _target(tmp_path)

    gate = run_gate(
        "full",
        (sys.executable, "-c", "print('x' * 200000)"),
        build_dir=build,
        timeout=60,
    )

    assert gate.outcome == OUTCOME_PASS
    assert len(gate.stdout) > 100000


def test_ordinary_gate_output_is_captured_whole(tmp_path):
    _, build = _target(tmp_path)

    gate = run_gate(
        "full",
        (sys.executable, "-c", "import sys\nprint('ok out')\nsys.stderr.write('ok err')"),
        build_dir=build,
    )

    assert gate.outcome == OUTCOME_PASS
    assert "ok out" in gate.stdout
    assert "ok err" in gate.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="RLIMIT_AS is POSIX-only")
def test_a_gate_inherits_the_sandbox_memory_ceiling(tmp_path, monkeypatch):
    monkeypatch.setenv("DRYDOCK_SANDBOX_MEM_LIMIT", "256")
    _, build = _target(tmp_path)

    # Allocating far past the ceiling must fail inside the child, not in Drydock.
    gate = run_gate(
        "full",
        (sys.executable, "-c", "x = bytearray(2 * 1024 * 1024 * 1024)"),
        build_dir=build,
        timeout=120,
    )

    assert gate.outcome == OUTCOME_FAIL
    assert gate.return_code != 0


def test_a_gate_still_times_out_under_the_bounded_runner(tmp_path):
    _, build = _target(tmp_path)

    gate = run_gate(
        "full",
        (sys.executable, "-c", "import time; time.sleep(30)"),
        build_dir=build,
        timeout=1,
    )

    assert gate.outcome == OUTCOME_ERROR
    assert gate.timed_out
