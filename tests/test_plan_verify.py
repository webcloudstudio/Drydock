"""Tests for ``drydock plan verify`` — the free, deterministic gate before a build is paid for."""

from __future__ import annotations

import pytest

from drydock.errors import SpecificationError
from drydock.plan_verify import render, verify

_RUNNABLE = """# FEATURE: Example

## Programmatic Acceptance

=== AC ok ===
Intent: A criterion that can execute.

import json

payload = json.dumps({"a": 1})
assert "a" in payload
=== END AC ok ===
"""

_MISSING_IMPORT = """# FEATURE: Broken

## Programmatic Acceptance

=== AC path-filter ===
Intent: Filtered paths select only matching locations.

import subprocess

result = subprocess.run([os.path.join(os.getcwd(), "jq")], capture_output=True)
assert result.returncode == 0
=== END AC path-filter ===
"""

_BROKEN_SYNTAX = """# FEATURE: Malformed

## Programmatic Acceptance

=== AC bad-syntax ===
Intent: Does not compile.

def (:
=== END AC bad-syntax ===
"""

_BROKEN_REGEX = """# FEATURE: Malformed Pattern

## Programmatic Acceptance

=== AC lexer-conformance-slice ===
Intent: Selects a conformance slice by pattern.

import re

SELECT = r'^(\\\\.|\\\\[|\\\\{|def)'
selector = re.compile(SELECT)
assert selector
=== END AC lexer-conformance-slice ===
"""

_RETYPED = """# FEATURE: Advisory

## Programmatic Acceptance

=== AC retyped ===
Intent: Compares against a hand-typed literal.

import subprocess

result = subprocess.run(["echo", "hello"], capture_output=True, text=True)
assert result.stdout.strip() == "hello world"
=== END AC retyped ===
"""


def _target(tmp_path, **specs: str):
    target = tmp_path / "Demo"
    blueprint = target / "blueprint"
    blueprint.mkdir(parents=True)
    for name, text in specs.items():
        (blueprint / f"{name}.md").write_text(text, encoding="utf-8")
    return target


def test_a_runnable_blueprint_verifies_clean(tmp_path):
    result = verify("Demo", _target(tmp_path, FEATURE_Ok=_RUNNABLE))

    assert result.ok
    assert result.exit_code() == 0
    assert result.defects == ()
    assert result.checked_criteria == 1


def test_an_empty_blueprint_verifies_clean(tmp_path):
    """Nothing to run is not a defect. Only a criterion that cannot run is."""
    result = verify("Demo", _target(tmp_path))

    assert result.ok
    assert result.checked_criteria == 0


def test_a_missing_import_is_a_defect_naming_the_criterion(tmp_path):
    """The exact failure that cost a whole jq run: NameError before the criterion tests anything."""
    result = verify("Demo", _target(tmp_path, FEATURE_Broken=_MISSING_IMPORT))

    assert not result.ok
    assert result.exit_code() == 1
    (defect,) = result.defects
    assert defect.check_id == "path-filter"
    assert defect.kind == "unresolved-global"
    assert "`os`" in defect.detail
    assert defect.filename == "FEATURE_Broken.md"


def test_a_syntax_error_is_a_defect(tmp_path):
    result = verify("Demo", _target(tmp_path, FEATURE_Bad=_BROKEN_SYNTAX))

    assert not result.ok
    assert result.defects[0].kind == "syntax"


def test_an_uncompilable_regex_pattern_is_a_defect(tmp_path):
    """The exact fault that stalled the jq run: an escaped backslash opens an unterminated
    class, so every build call crashes identically on the same criterion."""
    result = verify("Demo", _target(tmp_path, FEATURE_Bad=_BROKEN_REGEX))

    assert not result.ok
    assert result.exit_code() == 1
    (defect,) = result.defects
    assert defect.check_id == "lexer-conformance-slice"
    assert defect.kind == "invalid-regex"
    assert "does not compile" in defect.detail


def test_one_criterion_yields_one_defect(tmp_path):
    """Syntax short-circuits name analysis, so a single fault is never reported twice."""
    result = verify("Demo", _target(tmp_path, FEATURE_Bad=_BROKEN_SYNTAX))

    assert len(result.defects) == 1


def test_a_retyped_expectation_warns_and_does_not_gate(tmp_path):
    """Gating on this class would refuse correct specifications; it is reported instead."""
    result = verify("Demo", _target(tmp_path, FEATURE_Advisory=_RETYPED))

    assert result.ok
    assert result.warnings


_SILENT_SUITE = """# FEATURE: Conformance

## Programmatic Acceptance

=== AC suite-conformance ===
Intent: The suite passes.

import json, subprocess, sys

result = subprocess.run([sys.executable, "run_suite.py", "--json"], capture_output=True, text=True)
report = json.loads(result.stdout)
assert report["summary"]["fail"] == 0
=== END AC suite-conformance ===
"""


def test_a_criterion_that_captures_output_and_prints_none_warns_and_does_not_gate(tmp_path):
    """It runs and judges correctly; what it costs is measurement, so it is advisory."""
    result = verify("Demo", _target(tmp_path, FEATURE_Silent=_SILENT_SUITE))

    assert result.ok
    assert any("prints none of it" in warning for warning in result.warnings)


def test_a_criterion_that_reports_what_it_captured_does_not_warn(tmp_path):
    result = verify(
        "Demo",
        _target(
            tmp_path,
            FEATURE_Loud=_SILENT_SUITE.replace(
                "report = json.loads(result.stdout)",
                'report = json.loads(result.stdout)\nprint(report["summary"])',
            ),
        ),
    )

    assert result.warnings == ()


def test_generated_files_are_not_verified(tmp_path):
    target = _target(tmp_path, FEATURE_Ok=_RUNNABLE)
    (target / "blueprint" / "MANIFEST.md").write_text(_MISSING_IMPORT, encoding="utf-8")

    assert verify("Demo", target).ok


def test_a_missing_blueprint_is_an_error(tmp_path):
    (tmp_path / "Demo").mkdir()

    with pytest.raises(SpecificationError):
        verify("Demo", tmp_path / "Demo")


def test_the_rendering_names_the_repair_command(tmp_path):
    text = render(verify("Demo", _target(tmp_path, FEATURE_Broken=_MISSING_IMPORT)))

    assert "FEATURE_Broken.md [path-filter]" in text
    assert "drydock plan repair Demo" in text


def test_a_clean_rendering_does_not_offer_repair(tmp_path):
    text = render(verify("Demo", _target(tmp_path, FEATURE_Ok=_RUNNABLE)))

    assert "plan repair" not in text


class TestVerifyRecordsOnlyFailure:
    """``plan verify`` claims no rung; a failure condemns the rung that authored the plan."""

    def _verify(self, monkeypatch, target_dir):
        from drydock import cli

        monkeypatch.setattr("drydock.config.require_target_dir", lambda _t: target_dir)
        return cli.cmd_plan_verify("Demo")

    def test_a_clean_verify_records_nothing(self, tmp_path, monkeypatch, capsys):
        from drydock.project_status import read_status, record_status

        target_dir = _target(tmp_path, FEATURE_Ok=_RUNNABLE)
        record_status(target_dir, "PLAN CREATED", passed=True)

        assert self._verify(monkeypatch, target_dir) == 0
        capsys.readouterr()

        entry = read_status(target_dir)[-1]
        assert entry.passed is True
        assert entry.command == ""  # untouched: verify wrote no record over it

    def test_a_failed_verify_fails_the_plan_rung_without_voiding(
        self, tmp_path, monkeypatch, capsys
    ):
        from drydock.project_status import (
            current_state,
            latest_per_label,
            read_status,
            record_status,
        )

        target_dir = _target(tmp_path, FEATURE_Broken=_MISSING_IMPORT)
        for label in ("PLAN CREATED", "BUILT", "SCORE RELEASE"):
            record_status(target_dir, label, passed=True)

        assert self._verify(monkeypatch, target_dir) == 1
        capsys.readouterr()

        standing = latest_per_label(read_status(target_dir))
        assert standing["PLAN CREATED"].passed is False
        assert standing["PLAN CREATED"].detail == "1 criterion cannot run"
        assert standing["PLAN CREATED"].command == "drydock plan verify Demo"
        # It authored nothing, so it voids nothing; the later release remains current.
        assert set(standing) == {"PLAN CREATED", "BUILT", "SCORE RELEASE"}
        assert current_state(target_dir).label == "SCORE RELEASE"

    def test_a_repaired_plan_is_the_rung_condemned(self, tmp_path, monkeypatch, capsys):
        from drydock.project_status import latest_per_label, read_status, record_status

        target_dir = _target(tmp_path, FEATURE_Broken=_MISSING_IMPORT)
        record_status(target_dir, "PLAN CREATED", passed=True)
        record_status(target_dir, "PLAN REPAIRED", passed=True)

        assert self._verify(monkeypatch, target_dir) == 1
        capsys.readouterr()

        standing = latest_per_label(read_status(target_dir))
        assert standing["PLAN CREATED"].passed is True
        assert standing["PLAN REPAIRED"].passed is False

    def test_no_plan_rung_means_no_record(self, tmp_path, monkeypatch, capsys):
        from drydock.project_status import read_status, record_status

        target_dir = _target(tmp_path, FEATURE_Broken=_MISSING_IMPORT)
        record_status(target_dir, "INITIALIZED", passed=True)

        assert self._verify(monkeypatch, target_dir) == 1
        capsys.readouterr()

        assert [e.label for e in read_status(target_dir)] == ["INITIALIZED"]
