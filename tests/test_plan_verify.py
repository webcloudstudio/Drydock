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

_READS_ITS_OWN_SPECIFICATION = """# FEATURE: Self Reading

## Programmatic Acceptance

=== AC boundaries ===
Intent: The architecture declares the required boundaries.

import pathlib

text = pathlib.Path("FEATURE_Self.md").read_text()
assert "FastAPI" in text
=== END AC boundaries ===
"""

_READS_A_BUILT_FILE = """# FEATURE: Built Reading

## Programmatic Acceptance

=== AC storage-module ===
Intent: The storage module is written.

import pathlib

text = pathlib.Path("marina_app/storage.py").read_text()
assert "def open_session" in text
=== END AC storage-module ===
"""

_RUNS_A_STAGED_ASSET = """# FEATURE: Staged Reading

## Programmatic Acceptance

=== AC conformance ===
Intent: The imported suite passes.

import pathlib

assert pathlib.Path("sources/run_conformance.py").is_file()
=== END AC conformance ===
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

_BROKEN_STAGED_REGEX = """# FEATURE: Staged Runner Pattern

## Programmatic Acceptance

=== AC lexer-conformance ===
Intent: Selects lexical conformance cases through the staged runner.

import subprocess
import sys

selector = r"\\\\(|@format"
result = subprocess.run(
    [sys.executable, "sources/run_conformance.py", "--select", selector],
    capture_output=True,
    text=True,
)
assert result.returncode == 0
=== END AC lexer-conformance ===
"""

_STAGED_REGEX_RUNNER = """import argparse
import re

parser = argparse.ArgumentParser()
parser.add_argument("--select")
args = parser.parse_args()
selector = re.compile(args.select) if args.select else None
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


def test_reading_a_blueprint_document_is_a_defect(tmp_path):
    """The exact failure that blocked Marina_Luna's first block: acceptance runs in the build
    directory, which never holds the specification the story was built from."""
    result = verify("Demo", _target(tmp_path, FEATURE_Self=_READS_ITS_OWN_SPECIFICATION))

    assert not result.ok
    assert result.exit_code() == 1
    (defect,) = result.defects
    assert defect.check_id == "boundaries"
    assert defect.kind == "blueprint-read"
    assert "FEATURE_Self.md" in defect.detail
    assert "never holds" in defect.detail


def test_reading_a_file_the_story_builds_is_not_a_defect(tmp_path):
    """Only a path that exists in the Blueprint is refused. A build output does not yet exist
    anywhere, and asserting on one is the normal shape."""
    result = verify("Demo", _target(tmp_path, FEATURE_Built=_READS_A_BUILT_FILE))

    assert result.ok
    assert result.defects == ()


def test_reading_a_staged_asset_is_not_a_defect(tmp_path):
    """Assets the Analysis marks ``stage`` are copied into the build, so the path resolves."""
    target = _target(tmp_path, FEATURE_Staged=_RUNS_A_STAGED_ASSET)
    sources = target / "blueprint" / "sources"
    sources.mkdir()
    (sources / "run_conformance.py").write_text("print('ok')\n", encoding="utf-8")

    result = verify("Demo", target)

    assert result.ok
    assert result.defects == ()


def test_reading_another_blueprint_document_is_a_defect(tmp_path):
    """The fault is the Blueprint, not self-reference: a sibling specification is equally absent."""
    result = verify(
        "Demo",
        _target(
            tmp_path,
            FEATURE_Ok=_RUNNABLE,
            FEATURE_Self=_READS_ITS_OWN_SPECIFICATION.replace(
                'pathlib.Path("FEATURE_Self.md")', 'pathlib.Path("FEATURE_Ok.md")'
            ),
        ),
    )

    assert not result.ok
    (defect,) = result.defects
    assert defect.kind == "blueprint-read"
    assert "FEATURE_Ok.md" in defect.detail


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


def test_an_uncompilable_regex_passed_to_a_staged_runner_is_a_defect(tmp_path):
    """A runner contract proves this value fails before it can test the product."""
    target = _target(tmp_path, FEATURE_Bad=_BROKEN_STAGED_REGEX)
    sources = target / "blueprint" / "sources"
    sources.mkdir()
    (sources / "run_conformance.py").write_text(_STAGED_REGEX_RUNNER, encoding="utf-8")

    result = verify("Demo", target)

    assert not result.ok
    (defect,) = result.defects
    assert defect.check_id == "lexer-conformance"
    assert defect.kind == "invalid-staged-regex"
    assert "sources/run_conformance.py --select" in defect.detail
    assert "does not compile" in defect.detail


def test_one_criterion_yields_one_defect(tmp_path):
    """Syntax short-circuits name analysis, so a single fault is never reported twice."""
    result = verify("Demo", _target(tmp_path, FEATURE_Bad=_BROKEN_SYNTAX))

    assert len(result.defects) == 1


_PROBE_RUNNER_LINES = """import argparse

CASES = ["alpha", "beta", "gamma"]

parser = argparse.ArgumentParser()
parser.add_argument("--select")
parser.add_argument("--list", action="store_true")
args = parser.parse_args()
selected = [c for c in CASES if args.select in c] if args.select else CASES
if args.list:
    for case in selected:
        print(case)
"""

_PROBE_RUNNER_SUMMARY = """import argparse

CASES = ["alpha", "beta", "gamma"]

parser = argparse.ArgumentParser()
parser.add_argument("--select")
parser.add_argument("--list", action="store_true")
args = parser.parse_args()
selected = [c for c in CASES if args.select in c] if args.select else CASES
if args.list:
    print(f"{len(selected)} cases, {len(CASES) - len(selected)} excluded")
"""


def _selector_ac(check_id: str, select: str, *, probe: str = "", probe_count: str = "") -> str:
    declarations = ""
    if probe:
        declarations += f"Probe: {probe}\n"
    if probe_count:
        declarations += f"Probe Count: {probe_count}\n"
    return f"""# FEATURE: Selector

## Programmatic Acceptance

=== AC {check_id} ===
Intent: Selects a conformance slice through the staged runner.
{declarations}
import subprocess
import sys

result = subprocess.run(
    [sys.executable, "sources/run_probe.py", "--select", "{select}"],
    capture_output=True, text=True,
)
assert result.returncode == 0
=== END AC {check_id} ===
"""


def _probe_target(tmp_path, runner_text: str, **specs: str):
    target = _target(tmp_path, **specs)
    sources = target / "blueprint" / "sources"
    sources.mkdir()
    (sources / "run_probe.py").write_text(runner_text, encoding="utf-8")
    return target


def test_a_missing_selection_probe_is_a_defect(tmp_path):
    """A recognized selector with no declared Probe: cannot be proven non-empty before build."""
    target = _probe_target(
        tmp_path, _PROBE_RUNNER_LINES, FEATURE_Selector=_selector_ac("select-alpha", "alpha")
    )

    result = verify("Demo", target)

    assert not result.ok
    (defect,) = result.defects
    assert defect.check_id == "select-alpha"
    assert defect.kind == "missing-selection-probe"


def test_an_invalid_selection_probe_is_a_defect(tmp_path, monkeypatch):
    """Malformed Probe:/Probe Count: is rejected before anything executes."""
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not execute")),
    )
    target = _probe_target(
        tmp_path,
        _PROBE_RUNNER_LINES,
        FEATURE_Selector=_selector_ac(
            "select-alpha", "alpha", probe="--list; echo hi", probe_count="lines"
        ),
    )

    result = verify("Demo", target)

    assert not result.ok
    (defect,) = result.defects
    assert defect.kind == "invalid-selection-probe"


def test_an_invalid_selection_probe_count_mode_is_a_defect(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not execute")),
    )
    target = _probe_target(
        tmp_path,
        _PROBE_RUNNER_LINES,
        FEATURE_Selector=_selector_ac("select-alpha", "alpha", probe="--list", probe_count="tally"),
    )

    result = verify("Demo", target)

    assert not result.ok
    (defect,) = result.defects
    assert defect.kind == "invalid-selection-probe"


def test_a_failed_probe_is_a_defect_not_an_empty_selection(tmp_path):
    """A probe that cannot run is never read as proof of zero cases."""
    target = _probe_target(
        tmp_path,
        _PROBE_RUNNER_LINES,
        FEATURE_Selector=_selector_ac(
            "select-alpha", "alpha", probe="--not-a-real-flag", probe_count="lines"
        ),
    )

    result = verify("Demo", target)

    assert not result.ok
    (defect,) = result.defects
    assert defect.kind == "probe-failed"


def test_an_empty_selection_in_lines_mode_is_a_defect(tmp_path):
    target = _probe_target(
        tmp_path,
        _PROBE_RUNNER_LINES,
        FEATURE_Selector=_selector_ac("select-nothing", "zzz", probe="--list", probe_count="lines"),
    )

    result = verify("Demo", target)

    assert not result.ok
    (defect,) = result.defects
    assert defect.kind == "empty-selection"


def test_an_empty_selection_in_summary_mode_is_a_defect(tmp_path):
    target = _probe_target(
        tmp_path,
        _PROBE_RUNNER_SUMMARY,
        FEATURE_Selector=_selector_ac(
            "select-nothing", "zzz", probe="--list", probe_count="summary"
        ),
    )

    result = verify("Demo", target)

    assert not result.ok
    (defect,) = result.defects
    assert defect.kind == "empty-selection"


def test_a_valid_probe_with_a_nonzero_count_is_not_a_defect(tmp_path):
    target = _probe_target(
        tmp_path,
        _PROBE_RUNNER_LINES,
        FEATURE_Selector=_selector_ac("select-alpha", "alpha", probe="--list", probe_count="lines"),
    )

    result = verify("Demo", target)

    assert result.ok
    assert result.defects == ()


def test_a_valid_probe_in_summary_mode_with_a_nonzero_count_is_not_a_defect(tmp_path):
    target = _probe_target(
        tmp_path,
        _PROBE_RUNNER_SUMMARY,
        FEATURE_Selector=_selector_ac(
            "select-alpha", "alpha", probe="--list", probe_count="summary"
        ),
    )

    result = verify("Demo", target)

    assert result.ok
    assert result.defects == ()


_DYNAMIC_SELECTOR = """# FEATURE: Dynamic Selector

## Programmatic Acceptance

=== AC select-dynamic ===
Intent: Selects a conformance slice chosen at runtime.

import os
import subprocess
import sys

pattern = os.environ.get("SELECT", "alpha")
result = subprocess.run(
    [sys.executable, "sources/run_probe.py", "--select", pattern],
    capture_output=True, text=True,
)
assert result.returncode == 0
=== END AC select-dynamic ===
"""


def test_a_dynamic_selector_is_only_an_advisory(tmp_path):
    """Drydock cannot statically recover the selector, so it cannot build a probe for it; Layer 1
    (build_run's zero-case handling) still guards this case at runtime."""
    target = _probe_target(tmp_path, _PROBE_RUNNER_LINES, FEATURE_Dynamic=_DYNAMIC_SELECTOR)

    result = verify("Demo", target)

    assert result.ok
    assert result.defects == ()
    assert any("cannot statically resolve" in warning for warning in result.warnings)


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


_UNREADABLE_DATABASE = """# DATABASE: Demo

## Access Patterns

### FEATURE-X-001 — Store setting

| Field | Value |
|---|---|
| Owner | FEATURE-INVENTED.md |
| Access | read-write |
| Repository operation | `settings.update` |
| Compatibility | data |

## `settings`

| Field | Type | Notes |
|---|---|---|
| key | TEXT PK | |
"""


def test_verification_reads_the_same_ownership_rule_as_plan(tmp_path):
    """A Screen cannot own a table; `DATABASE.md` can, and means shared."""
    screen_owned = _UNREADABLE_DATABASE.replace(
        "| Owner | FEATURE-INVENTED.md |", "| Owner | SCREEN-X.md |"
    )
    result = verify("Demo", _target(tmp_path / "screen", DATABASE=screen_owned, SCREEN_X=""))
    assert "database-owner-unknown" in {defect.kind for defect in result.defects}

    shared = _UNREADABLE_DATABASE.replace(
        "| Owner | FEATURE-INVENTED.md |", "| Owner | DATABASE.md |"
    )
    result = verify("Demo", _target(tmp_path / "shared", DATABASE=shared))
    assert "database-owner-unknown" not in {defect.kind for defect in result.defects}


def test_a_persistence_declaration_build_cannot_read_fails_verification(tmp_path):
    """Build generates the persistence layer from DATABASE.md, so a declaration it cannot parse
    is a plan that cannot be built — Marina_Luna reported PLAN CREATED over thirteen of them."""
    result = verify("Demo", _target(tmp_path, DATABASE=_UNREADABLE_DATABASE))

    assert not result.ok
    assert sorted(defect.kind for defect in result.defects) == [
        "database-contract",
        "database-owner-unknown",
    ]
    assert "persistence defect" in result.summary
    rendered = render(result)
    assert "Run: drydock plan Demo" in rendered
    assert "Run: drydock plan repair Demo" not in rendered


_STACK_HEADER = """# Technology Stack

| Technology | Rigging | Notes |
|---|---|---|
"""


def _with_stack(target, rows: str):
    (target / "TECHNOLOGY_STACK.md").write_text(_STACK_HEADER + rows, encoding="utf-8")
    return target


def test_a_stack_selecting_one_foundation_per_kind_verifies_clean(tmp_path):
    target = _with_stack(
        _target(tmp_path, FEATURE_Ok=_RUNNABLE),
        "| Python | python.md | |\n| FastAPI | fastapi.md | |\n| SQLite | sqlite.md | |\n",
    )

    result = verify("Demo", target)

    assert result.ok
    assert result.defects == ()


def test_two_web_servers_is_a_defect(tmp_path):
    """One build tree cannot hold two application shapes."""
    target = _with_stack(
        _target(tmp_path, FEATURE_Ok=_RUNNABLE),
        "| Python | python.md | |\n| FastAPI | fastapi.md | |\n| Flask | flask.md | |\n",
    )

    result = verify("Demo", target)

    assert not result.ok
    (defect,) = result.defects
    assert defect.kind == "foundation"
    assert "web-server: 2 selected" in defect.detail
    assert defect.filename == "TECHNOLOGY_STACK.md"


def test_an_unanswered_foundation_row_is_a_defect(tmp_path):
    """Drydock does not pick a web server for the operator. Analyze asks; plan refuses."""
    target = _with_stack(
        _target(tmp_path, FEATURE_Ok=_RUNNABLE),
        "| Python | python.md | |\n| FastAPI | — | |\n",
    )

    result = verify("Demo", target)

    assert not result.ok
    (defect,) = result.defects
    assert defect.kind == "foundation"
    assert "FastAPI" in defect.detail
    assert "fastapi.md" in defect.detail


def test_an_unanswered_non_foundation_row_is_not_a_defect(tmp_path):
    """A technology with no Rigging guidance is normal and never an error."""
    target = _with_stack(
        _target(tmp_path, FEATURE_Ok=_RUNNABLE),
        "| Python | python.md | |\n| Git | — | |\n| GitHub CLI | — | |\n",
    )

    result = verify("Demo", target)

    assert result.ok


def test_additive_files_beside_one_database_are_clean(tmp_path):
    """sqlalchemy.md and alembic.md are Persistence files selected alongside the one database."""
    target = _with_stack(
        _target(tmp_path, FEATURE_Ok=_RUNNABLE),
        "| Python | python.md | |\n| SQLite | sqlite.md | |\n| SQLAlchemy | sqlalchemy.md | |\n| Alembic | alembic.md | |\n",
    )

    result = verify("Demo", target)

    assert result.ok


def test_no_stack_file_is_not_a_foundation_defect(tmp_path):
    """A missing stack is an earlier problem, reported by the commands that need one."""
    result = verify("Demo", _target(tmp_path, FEATURE_Ok=_RUNNABLE))

    assert result.ok


# ── Unknown packages ────────────────────────────────────────────────────────────

_WRONG_PACKAGE = """# FEATURE: Catalog

## Programmatic Acceptance

=== AC catalog-list ===
Intent: The catalog endpoint answers.

from marina_app import create_app

client = create_app().test_client()
assert client.get("/catalog").status_code == 200
=== END AC catalog-list ===
"""

_PUBLISHED_FIXTURE = """# FEATURE: Catalog

## Programmatic Acceptance

=== AC catalog-list ===
Intent: The catalog endpoint answers.

from app_server.main import create_app
from fastapi.testclient import TestClient

response = TestClient(create_app()).get("/catalog")
assert response.status_code == 200
=== END AC catalog-list ===
"""

_UNSELECTED_PACKAGE = """# FEATURE: Storage

## Programmatic Acceptance

=== AC rows-persist ===
Intent: A written row reads back.

import persistence

with persistence.open_session() as session:
    assert session is not None
=== END AC rows-persist ===
"""


def test_a_criterion_importing_the_entry_from_the_wrong_package_is_a_defect(tmp_path):
    """The Marina_Luna split: 98 imports of `app` against 77 of `marina_app`, every one of them
    importing the callable the foundation publishes in `app_server`."""
    target = _with_stack(
        _target(tmp_path, FEATURE_Catalog=_WRONG_PACKAGE),
        "| Python | python.md | |\n| FastAPI | fastapi.md | |\n",
    )

    result = verify("Demo", target)

    assert not result.ok
    (defect,) = result.defects
    assert defect.kind == "unknown-package"
    assert defect.check_id == "catalog-list"
    assert "`app_server`" in defect.detail


def test_a_criterion_importing_a_package_no_selected_foundation_publishes_is_a_defect(tmp_path):
    """`persistence` means the selected database. With none selected it means nothing, and the
    criterion raises ModuleNotFoundError in its own frame on every run."""
    target = _with_stack(
        _target(tmp_path, FEATURE_Storage=_UNSELECTED_PACKAGE),
        "| Python | python.md | |\n| FastAPI | fastapi.md | |\n",
    )

    result = verify("Demo", target)

    assert not result.ok
    (defect,) = result.defects
    assert defect.kind == "unknown-package"
    assert "selects no database" in defect.detail


def test_the_published_package_verifies_clean(tmp_path):
    target = _with_stack(
        _target(tmp_path, FEATURE_Catalog=_PUBLISHED_FIXTURE),
        "| Python | python.md | |\n| FastAPI | fastapi.md | |\n",
    )

    result = verify("Demo", target)

    assert result.ok


def test_imports_are_not_judged_without_a_technology_stack(tmp_path):
    """Without a stack there is no selection to judge against, and guessing refuses good plans."""
    result = verify("Demo", _target(tmp_path, FEATURE_Catalog=_WRONG_PACKAGE))

    assert result.ok


@pytest.mark.parametrize(
    "setup",
    [
        'import os\nos.environ["DATABASE_PATH"] = "new.db"',
        'from os import environ as env\nenv.update(DATABASE_URL="new.db")',
        'import os\nos.putenv("DATABASE_PATH", "new.db")',
        'from persistence.testing import db_session\nwith db_session("new.db") as db:\n    assert db is not None',
    ],
)
def test_acceptance_cannot_replace_the_configured_store(tmp_path, setup):
    target = _target(
        tmp_path, **{"FEATURE-Test.md": _RUNNABLE.replace("import json", setup + "\nimport json")}
    )
    result = verify("Test", target)
    assert any(d.kind == "acceptance-store" for d in result.defects)


def _go_criterion(body: str) -> str:
    return (
        "# FEATURE: Go CLI\n\n## Programmatic Acceptance\n\n=== AC usage ===\n"
        "Intent: Malformed invocations return the usage-error exit status.\n\n"
        f"{body}\n=== END AC usage ===\n"
    )


def test_go_run_of_the_application_is_a_defect(tmp_path):
    """CsvStat 20261022.203215: ``go run`` reports exit 2 as 1, so a correct parser failed."""
    code = (
        "import subprocess\n\n"
        'result = subprocess.run(["go", "run", "./cmd/csvstat"], capture_output=True, text=True)\n'
        "assert result.returncode == 2"
    )
    result = verify("Demo", _target(tmp_path, FEATURE_Cli=_go_criterion(code)))

    (defect,) = result.defects
    assert defect.kind == "go-run"
    assert "line(s) 3" in defect.detail
    assert "cli_runner" in defect.detail


def test_go_run_as_a_shell_string_is_a_defect(tmp_path):
    code = (
        "import subprocess\n\n"
        'result = subprocess.run("go run ./cmd/csvstat --top 0", shell=True)\n'
        "assert result.returncode == 2"
    )
    result = verify("Demo", _target(tmp_path, FEATURE_Cli=_go_criterion(code)))

    assert [defect.kind for defect in result.defects] == ["go-run"]


def test_a_pinned_go_tool_and_the_go_cli_runner_verify_clean(tmp_path):
    code = (
        "import subprocess\n"
        "from drydock_go import cli_runner\n\n"
        'lint = subprocess.run(["go", "run", "honnef.co/go/tools/cmd/staticcheck@v0.5.1", "./..."])\n'
        "assert lint.returncode == 0\n"
        'code, out, err = cli_runner("--top", "0", "data.csv")\n'
        "assert code == 2, (code, out, err)"
    )
    result = verify("Demo", _target(tmp_path, FEATURE_Cli=_go_criterion(code)))

    assert result.ok, result.defects


_STORY_MANIFEST = """# MANIFEST: Demo
state: draft

## story 1: Store
id: store
implements: DATABASE.md
instructions: |
  Provision the store.
state: pending

## story 2: Status
id: status
implements: FEATURE-Status.md
depends: store
instructions: |
  Build the status command.
state: pending
"""

_NO_CRITERIA = "# DATABASE: Demo\n\n## Programmatic Acceptance\n\n- None.\n"


def test_a_story_whose_blueprint_carries_no_criterion_is_a_defect(tmp_path):
    """ReadingList 20261022.231143: `persistence-store` had no criteria and could only fail."""
    target = _target(tmp_path, **{"DATABASE": _NO_CRITERIA, "FEATURE-Status": _RUNNABLE})
    (target / "MANIFEST.md").write_text(_STORY_MANIFEST, encoding="utf-8")

    result = verify("Demo", target)

    (defect,) = result.defects
    assert defect.kind == "criteria-missing"
    assert defect.filename == "DATABASE.md"
    assert "story `store`" in defect.detail
    assert "db_session" in defect.detail
    assert "1 story Blueprint has no acceptance criteria" in result.summary


def test_every_story_with_a_criterion_verifies_clean(tmp_path):
    target = _target(tmp_path, **{"DATABASE": _RUNNABLE, "FEATURE-Status": _RUNNABLE})
    (target / "MANIFEST.md").write_text(_STORY_MANIFEST, encoding="utf-8")

    assert verify("Demo", target).ok


def test_a_story_citing_a_file_outside_the_blueprint_has_no_criterion(tmp_path):
    """A story implementing a Rigging file such as python.md has nothing to grade."""
    target = _target(tmp_path, **{"FEATURE-Status": _RUNNABLE})
    (target / "MANIFEST.md").write_text(
        _STORY_MANIFEST.replace("implements: DATABASE.md", "implements: python.md"),
        encoding="utf-8",
    )

    (defect,) = verify("Demo", target).defects
    assert defect.kind == "criteria-missing"
    assert defect.filename == "python.md"
    assert "not a file in blueprint/" in defect.detail


def test_a_story_implementing_nothing_has_no_criterion(tmp_path):
    target = _target(tmp_path, **{"FEATURE-Status": _RUNNABLE})
    (target / "MANIFEST.md").write_text(
        _STORY_MANIFEST.replace("implements: DATABASE.md\n", ""), encoding="utf-8"
    )

    (defect,) = verify("Demo", target).defects
    assert defect.kind == "criteria-missing"
    assert defect.filename == "MANIFEST.md"
    assert "story `store` implements no Blueprint" in defect.detail


def test_a_refit_ticket_beneath_the_blueprint_is_counted(tmp_path):
    """ReadingList's `mark-read-*` stories implemented `changes/` tickets carrying no criterion."""
    target = _target(tmp_path, **{"DATABASE": _RUNNABLE, "FEATURE-Status": _RUNNABLE})
    changes = target / "blueprint" / "changes"
    changes.mkdir()
    (changes / "TICKET-001.md").write_text(_NO_CRITERIA, encoding="utf-8")
    (changes / "TICKET-002.md").write_text(_RUNNABLE, encoding="utf-8")
    manifest = _STORY_MANIFEST + (
        "\n## story 3: Ticket one\nid: ticket-one\nimplements: changes/TICKET-001.md\n"
        "state: pending\n\n## story 4: Ticket two\nid: ticket-two\n"
        "implements: changes/TICKET-002.md\nstate: pending\n"
    )
    (target / "MANIFEST.md").write_text(manifest, encoding="utf-8")

    (defect,) = verify("Demo", target).defects
    assert defect.filename == "changes/TICKET-001.md"
    assert "story `ticket-one`" in defect.detail


def test_plan_repair_leaves_a_missing_criterion_to_plan(tmp_path):
    from drydock.plan_repair import repair

    target = _target(tmp_path, **{"DATABASE": _NO_CRITERIA, "FEATURE-Status": _RUNNABLE})
    (target / "MANIFEST.md").write_text(_STORY_MANIFEST, encoding="utf-8")

    def runner(*args, **kwargs):
        raise AssertionError("no repair call is made for a missing criterion")

    result = repair("Demo", target, runner=runner)

    (item,) = result.items
    assert item.status == "unrepaired"
    assert "drydock plan Demo" in item.detail


def _database(criteria: str) -> str:
    from tests.test_database_emit import _DATABASE

    return _DATABASE.replace(
        "## `tickets`", f"## Programmatic Acceptance\n\n{criteria}\n## `tickets`", 1
    )


_CREATE_CRITERION = """=== AC ticket-create ===
Intent: A created ticket comes back with its key.

from persistence.testing import db_session

with db_session() as db:
    created = db.tickets.create(status="open", title="T")
    assert created.id
=== END AC ticket-create ===
"""


def test_a_declared_operation_no_criterion_calls_is_a_defect(tmp_path):
    """One criterion per repository operation: `tickets.list` ships untested here."""
    target = _target(
        tmp_path,
        **{"DATABASE": _database(_CREATE_CRITERION), "FEATURE-Ticket": _RUNNABLE},
    )

    result = verify("Demo", target)

    (defect,) = result.defects
    assert defect.kind == "operation-untested"
    assert defect.filename == "DATABASE.md"
    assert "`tickets.list`" in defect.detail
    assert "db.tickets.list(" in defect.detail
    assert "1 repository operation no DATABASE.md criterion calls" in result.summary


def test_every_declared_operation_called_verifies_clean(tmp_path):
    listed = _CREATE_CRITERION.replace("ticket-create", "ticket-list").replace(
        "assert created.id", 'assert [row.id for row in db.tickets.list(status="open")]'
    )
    target = _target(
        tmp_path,
        **{
            "DATABASE": _database(_CREATE_CRITERION + "\n" + listed),
            "FEATURE-Ticket": _RUNNABLE,
        },
    )

    assert verify("Demo", target).ok, verify("Demo", target).defects


def test_a_go_criterion_calls_the_exported_operation():
    from drydock.plan_verify import untested_operations
    from tests.test_database_emit import _DATABASE

    code = 'created, err := db.Tickets.Create(ctx, CreateTicket{Status: "open"})'

    assert untested_operations(_DATABASE, [code]) == ("tickets.list",)
