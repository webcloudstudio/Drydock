"""Unit tests for Programmatic Acceptance parsing and its execution budget."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from drydock import acceptance
from drydock.acceptance import (
    MEMORY_FAILURE_PREFIX,
    SUITE_TIMEOUT_SECONDS,
    TIMEOUT_FAILURE_PREFIX,
    TIMEOUT_SECONDS,
    AcceptanceRequirement,
    ProgrammaticAcceptance,
    parse_programmatic_acceptance,
    run_programmatic_acceptance,
)
from drydock.config import DEFAULT_SANDBOX_MEM_LIMIT_MB, get_sandbox_mem_limit_mb
from drydock.errors import ConfigurationError

_SPEC = """# FEATURE: Verification

## Programmatic Acceptance

### assets-present
Sea Trials: st-003
The supplied verification assets are staged.

```python
from pathlib import Path
assert Path("sources/spec.txt").is_file()
```

### conformance-full
Suite: full
Sea Trials: st-004
Every normative example converts correctly.

```python
import subprocess, sys
subprocess.run([sys.executable, "sources/spec_tests.py"], check=True)
```

### suite-full
Suite: full
Every normative example converts correctly.

```python
import subprocess, sys
subprocess.run([sys.executable, "sources/spec_tests.py"], check=True)
```

### suite-scoped
Suite: scoped
The owned sections convert correctly.

```python
import subprocess, sys
subprocess.run([sys.executable, "sources/spec_tests.py", "--pattern", "Hard line breaks"], check=True)
```
"""


def _checks(tmp_path: Path):
    path = tmp_path / "FEATURE-Verification.md"
    path.write_text(_SPEC, encoding="utf-8")
    return {check.check_id: check for check in parse_programmatic_acceptance(path)}


def test_suite_markers_are_parsed(tmp_path):
    checks = _checks(tmp_path)

    # Suite: full/scoped both mark a whole-test-suite check.
    assert checks["suite-full"].full_suite is True
    assert checks["suite-scoped"].full_suite is True
    assert checks["conformance-full"].full_suite is True
    assert checks["assets-present"].full_suite is False


def test_suite_check_gets_the_long_execution_budget(tmp_path):
    """A story timeout would kill a real conformance run partway and report a false failure."""
    checks = _checks(tmp_path)

    assert checks["suite-full"].timeout_seconds == SUITE_TIMEOUT_SECONDS
    assert checks["suite-scoped"].timeout_seconds == SUITE_TIMEOUT_SECONDS
    assert checks["conformance-full"].timeout_seconds == SUITE_TIMEOUT_SECONDS
    assert checks["assets-present"].timeout_seconds == TIMEOUT_SECONDS
    assert SUITE_TIMEOUT_SECONDS > TIMEOUT_SECONDS


def test_an_undeclared_staged_runner_still_gets_the_suite_budget():
    """The exact criterion that sank jq run 20260815.004309.

    ``delivery-assets`` shelled out to a 550-case conformance suite without declaring ``Suite:``,
    drew the story budget, was killed at the limit, and was reported as a non-terminating loop in
    the product. The budget follows the invocation, not only the marker.
    """
    check = _criterion(
        "import os, subprocess\n"
        "result = subprocess.run(['sh', 'sources/full_test.sh'], capture_output=True,"
        " text=True, env={**os.environ, 'JQ': './jq'})\n"
        "assert result.returncode in (0, 1)\n"
    )

    assert check.full_suite is False
    assert check.suite_bound
    assert check.timeout_seconds == SUITE_TIMEOUT_SECONDS


def test_merely_naming_a_staged_path_keeps_the_story_budget():
    """Reading a staged file is bounded work; only executing one hands off the runtime."""
    check = _criterion('from pathlib import Path\nassert Path("sources/spec.txt").is_file()\n')

    assert not check.suite_bound
    assert check.timeout_seconds == TIMEOUT_SECONDS


def test_marker_lines_do_not_leak_into_the_stated_intent(tmp_path):
    checks = _checks(tmp_path)

    assert checks["conformance-full"].intent == "Every normative example converts correctly."
    assert "Suite:" not in checks["conformance-full"].intent
    assert "Sea Trials:" not in checks["conformance-full"].intent
    assert checks["suite-full"].intent == "Every normative example converts correctly."
    assert "Suite:" not in checks["suite-full"].intent
    assert "Suite:" not in checks["suite-scoped"].intent


def test_repeated_requirements_are_typed_and_excluded_from_intent(tmp_path):
    path = tmp_path / "FEATURE-Health.md"
    path.write_text(
        """# FEATURE: Health

## Programmatic Acceptance

### health-route
Requires: python-package=httpx; scope=test
Requires: executable=curl; scope=test

The health route responds successfully.

```python
assert True
```
""",
        encoding="utf-8",
    )

    check = parse_programmatic_acceptance(path)[0]

    assert check.requirements == (
        AcceptanceRequirement("python-package", "httpx", "test"),
        AcceptanceRequirement("executable", "curl", "test"),
    )
    assert check.intent == "The health route responds successfully."


@pytest.mark.parametrize(
    "declaration",
    [
        "Requires: package=httpx; scope=test",
        "Requires: python-package=httpx; scope=build",
        "Requires: python-package=httpx",
    ],
)
def test_malformed_requirements_are_rejected(tmp_path, declaration):
    path = tmp_path / "FEATURE-Health.md"
    path.write_text(
        "# FEATURE: Health\n\n## Programmatic Acceptance\n\n### health\n"
        + declaration
        + "\n\n```python\nassert True\n```\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Requires"):
        parse_programmatic_acceptance(path)


def test_new_python_target_uses_drydock_active_python_for_acceptance(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='target'\nversion='0'\n")
    (tmp_path / "target_module.py").write_text(
        "import pytest\nVALUE = pytest.__name__\n", encoding="utf-8"
    )
    check = ProgrammaticAcceptance(
        "strict",
        "FEATURE-X.md",
        "Strict.",
        "import target_module\nassert target_module.VALUE == 'pytest'",
    )

    result = run_programmatic_acceptance(
        (check,),
        build_dir=tmp_path,
        target_dir=tmp_path,
        blueprint_dir=tmp_path,
        strict_target=True,
    )[0]

    assert result.passed
    assert result.interpreter == sys.executable


def test_target_venv_cannot_import_a_package_available_only_on_drydock_pythonpath(
    tmp_path, monkeypatch
):
    leak = tmp_path / "drydock-only"
    leak.mkdir()
    (leak / "drydock_only_package.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(leak))
    subprocess.run(["python3", "-m", "venv", str(tmp_path / ".venv")], check=True)
    check = ProgrammaticAcceptance(
        "isolated",
        "FEATURE-X.md",
        "Target isolation.",
        "import drydock_only_package\nassert drydock_only_package.VALUE == 1",
    )

    result = run_programmatic_acceptance(
        (check,),
        build_dir=tmp_path,
        target_dir=tmp_path,
        blueprint_dir=tmp_path,
        strict_target=True,
    )[0]

    assert not result.passed
    assert "No module named 'drydock_only_package'" in result.stderr
    assert ".venv" in result.interpreter


def test_sea_trial_references_still_parse_alongside_the_suite_marker(tmp_path):
    checks = _checks(tmp_path)

    assert checks["conformance-full"].sea_trials == ("st-004",)
    assert checks["assets-present"].sea_trials == ("st-003",)


@pytest.mark.parametrize("scope", ["full", "scoped"])
def test_suite_accepts_authoritative_exact_passed_count(tmp_path, scope):
    path = tmp_path / "FEATURE-Verification.md"
    path.write_text(
        f"""# FEATURE: Verification

## Programmatic Acceptance

### conformance-full
Suite: {scope}
Sea Trials: st-004

```python
assert result.returncode == 0
assert "652 passed" in result.stdout
```
""",
        encoding="utf-8",
    )

    checks = parse_programmatic_acceptance(path)

    assert len(checks) == 1
    assert checks[0].full_suite is True
    assert '"652 passed"' in checks[0].code


# --- Failure diagnostics ----------------------------------------------------
#
# A failing assertion must name itself. Executed via ``python -c`` the traceback reads
# ``File "<string>", line 3`` with no source, so a mis-authored expectation is
# indistinguishable from a genuine implementation defect without manual reproduction.


def _run_one(code: str, tmp_path: Path):
    check = ProgrammaticAcceptance(
        check_id="diagnostic-check",
        source="FEATURE-Diagnostics.md",
        intent="Diagnostics are legible.",
        code=code,
    )
    return run_programmatic_acceptance(
        (check,),
        build_dir=tmp_path,
        target_dir=tmp_path,
        blueprint_dir=tmp_path,
    )[0]


def test_failing_assertion_reports_its_source_line(tmp_path):
    result = _run_one('value = 1\nassert value == 2, "value drifted"', tmp_path)
    assert not result.passed
    assert "assert value == 2" in result.stderr
    assert "value drifted" in result.stderr


def test_traceback_names_the_check_not_a_temporary_path(tmp_path):
    result = _run_one("assert False", tmp_path)
    assert "diagnostic-check.py" in result.stderr
    assert "drydock-acceptance-" not in result.stderr


def test_build_directory_stays_importable(tmp_path):
    (tmp_path / "built_module.py").write_text("VALUE = 7\n", encoding="utf-8")
    result = _run_one("from built_module import VALUE\nassert VALUE == 7", tmp_path)
    assert result.passed, result.stderr


def test_the_snippet_is_not_left_in_the_build_directory(tmp_path):
    _run_one("assert True", tmp_path)
    assert list(tmp_path.iterdir()) == []


# A build agent's code runs unsupervised. An unbounded allocation in it drove a 16 GB host
# into swap for the whole timeout window; the bound must stop that in seconds, and the
# verdict must say the code exhausted a resource rather than missed an expectation.


def test_memory_limit_defaults_and_reads_the_configuration(monkeypatch):
    monkeypatch.delenv("DRYDOCK_SANDBOX_MEM_LIMIT", raising=False)
    assert get_sandbox_mem_limit_mb() == DEFAULT_SANDBOX_MEM_LIMIT_MB
    monkeypatch.setenv("DRYDOCK_SANDBOX_MEM_LIMIT", "512")
    assert get_sandbox_mem_limit_mb() == 512
    monkeypatch.setenv("DRYDOCK_SANDBOX_MEM_LIMIT", "0")
    assert get_sandbox_mem_limit_mb() == 0
    monkeypatch.setenv("DRYDOCK_SANDBOX_MEM_LIMIT", "not-a-number")
    with pytest.raises(ConfigurationError):
        get_sandbox_mem_limit_mb()


@pytest.mark.skipif(os.name != "posix", reason="RLIMIT_AS is POSIX-only")
def test_runaway_allocation_is_bounded_and_named_as_resource_exhaustion(tmp_path, monkeypatch):
    monkeypatch.setenv("DRYDOCK_SANDBOX_MEM_LIMIT", "256")
    result = _run_one("blob = bytearray(1024 * 1024 * 1024)\nassert blob", tmp_path)
    assert not result.passed
    assert result.error is not None
    assert result.error.startswith(MEMORY_FAILURE_PREFIX)
    assert "256 MB" in result.error


@pytest.mark.skipif(os.name != "posix", reason="RLIMIT_AS is POSIX-only")
def test_the_bound_reaches_a_grandchild_process(tmp_path, monkeypatch):
    """The runaway is the built code the check invokes, not the check itself."""
    monkeypatch.setenv("DRYDOCK_SANDBOX_MEM_LIMIT", "256")
    (tmp_path / "runaway.py").write_text("bytearray(1024 * 1024 * 1024)\n", encoding="utf-8")
    result = _run_one(
        "import subprocess, sys\n"
        "done = subprocess.run([sys.executable, 'runaway.py'], capture_output=True, text=True)\n"
        "assert done.returncode == 0, done.stderr",
        tmp_path,
    )
    assert not result.passed
    assert "MemoryError" in result.stderr


def test_an_ordinary_assertion_failure_carries_no_resource_verdict(tmp_path):
    result = _run_one("assert 1 == 2", tmp_path)
    assert not result.passed
    assert result.error is None


def test_a_hung_check_is_reported_as_a_non_terminating_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(acceptance, "TIMEOUT_SECONDS", 2)
    result = _run_one("while True:\n    pass", tmp_path)
    assert not result.passed
    assert result.error is not None and result.error.startswith(TIMEOUT_FAILURE_PREFIX)
    assert "did not terminate" in result.error
    assert "non-terminating loop" in result.error


def test_a_story_timeout_names_the_loop_as_the_first_thing_to_look_for():
    """Bounded work that overran its own budget is good evidence of a loop that never exits."""
    check = _criterion("while True:\n    pass\n")
    error = acceptance._timeout_failure_text(check)

    assert error.startswith(TIMEOUT_FAILURE_PREFIX)
    assert "Look first for a non-terminating loop" in error
    assert "not a missed expectation" in error


def test_a_suite_timeout_does_not_invent_a_cause():
    """The claim that sank jq run 20260815.004309.

    ``delivery-assets`` was killed running a staged corpus that in fact completes in 50s, and the
    harness reported a non-terminating loop in the product. A kill at the budget cannot tell a
    hung case from a slow suite from a loaded host, so it must not name one.
    """
    check = _criterion(
        "import subprocess\nsubprocess.run(['sh', 'sources/full_test.sh'], check=False)\n"
    )
    error = acceptance._timeout_failure_text(check)

    assert error.startswith(TIMEOUT_FAILURE_PREFIX)
    assert "cause is not established" in error
    assert "non-terminating loop" not in error
    assert str(acceptance.SUITE_TIMEOUT_SECONDS) in error


@pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX-only")
def test_the_timeout_reaps_a_grandchild_instead_of_orphaning_it(tmp_path, monkeypatch):
    """Killing only the direct child leaves the runaway that the timeout was meant to stop."""
    monkeypatch.setattr(acceptance, "TIMEOUT_SECONDS", 2)
    marker = tmp_path / "grandchild.pid"
    (tmp_path / "sleeper.py").write_text(
        "import os, pathlib, time\n"
        f"pathlib.Path({str(marker)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(120)\n",
        encoding="utf-8",
    )
    result = _run_one(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, 'sleeper.py'])\n"
        "time.sleep(120)\n",
        tmp_path,
    )
    assert not result.passed
    grandchild = int(marker.read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and _alive(grandchild):
        time.sleep(0.1)
    assert not _alive(grandchild), f"pid {grandchild} survived the timeout"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# --- Malformed checks -------------------------------------------------------
#
# A check that dies inside its own snippet is not a red baseline. No implementation turns it
# green, so a repair pass on it is spend with no possible return. Attribution is by traceback
# frame: the same exception raised inside the code under test is a genuine red.


def test_a_name_from_a_sibling_check_is_named_as_a_malformed_check(tmp_path):
    result = _run_one("assert result.returncode == 0", tmp_path)
    assert not result.passed
    assert result.error is not None
    assert result.error.startswith(acceptance.MALFORMED_FAILURE_PREFIX)
    assert "NameError" in result.error
    assert "its own process" in result.error


def test_a_type_error_in_the_checks_own_frame_never_fails_the_build(tmp_path):
    """A criterion that cannot execute is not a verdict on the implementation.

    The observed case: a criterion passed a ``str`` to a binary-mode ``subprocess`` call, which
    raises before the program under test starts. Graded as a FAIL it closed its block failed and
    no implementation could ever have reopened it. A build searches for pass/fail verdicts, so an
    exception in the harness is charged to the harness — reported, and not to the build.
    """
    result = _run_one("import subprocess\nmemoryview('text')", tmp_path)
    assert not result.passed
    assert result.skipped, "a criterion that cannot execute must not be charged to the build"
    assert result.outcome == acceptance.OUTCOME_UNVERIFIED
    assert result.error is not None
    assert result.error.startswith(acceptance.MALFORMED_FAILURE_PREFIX)
    assert "TypeError" in result.error


def test_a_type_error_inside_the_code_under_test_stays_a_genuine_red(tmp_path):
    """Attribution is still by frame: the build owns what the build raised."""
    (tmp_path / "built_module.py").write_text(
        "def render(text):\n    return len(None)\n", encoding="utf-8"
    )
    result = _run_one("from built_module import render\nassert render('x') == 1", tmp_path)
    assert not result.passed
    assert not result.skipped
    assert "TypeError" in result.stderr
    assert result.error is None


def test_a_name_error_inside_the_code_under_test_stays_a_genuine_red(tmp_path):
    (tmp_path / "built_module.py").write_text(
        "def render():\n    return missing_helper()\n", encoding="utf-8"
    )
    result = _run_one("from built_module import render\nassert render() == 'x'", tmp_path)
    assert not result.passed
    assert "NameError" in result.stderr
    # The failure surfaced in the built code's frame, which is exactly what the build fixes.
    assert result.error is None


def test_a_missing_project_module_stays_the_expected_red_baseline(tmp_path):
    result = _run_one("from app import create_app\nassert create_app()", tmp_path)
    assert not result.passed
    assert result.error is None


def test_a_typo_in_an_import_is_left_to_the_build(tmp_path):
    """An import failure is indistinguishable from the expected pre-build red baseline.

    ``import subprocesss`` is a defect, but the traceback is identical in shape to
    ``from app import create_app`` before ``app`` exists. Classifying it would block builds
    that should proceed, so the runtime gate stays silent and static analysis owns what it can
    prove.
    """
    result = _run_one("import subprocesss\nassert subprocesss.run(['true'])", tmp_path)
    assert not result.passed
    assert result.error is None


def test_an_ordinary_assertion_failure_carries_no_malformed_verdict(tmp_path):
    result = _run_one("value = 1\nassert value == 2", tmp_path)
    assert not result.passed
    assert result.error is None


def test_a_passing_check_carries_no_verdict(tmp_path):
    result = _run_one("assert 1 == 1", tmp_path)
    assert result.passed
    assert result.error is None


# --- Three-valued outcome ----------------------------------------------------
#
# An assertion that fails because it could not read a file never reached the code under test.
# It is not a failure, it is a non-result. Only FAIL is evidence about the product; UNVERIFIED
# is evidence about the kit and is never charged against the build.


def test_a_missing_path_in_the_check_is_unverified_not_a_failure(tmp_path):
    result = _run_one("open('/nonexistent/dir/config.json').read()", tmp_path)
    assert result.outcome == acceptance.OUTCOME_UNVERIFIED
    assert result.unverified
    assert result.error is not None
    assert result.error.startswith(acceptance.UNVERIFIED_FAILURE_PREFIX)
    assert "FileNotFoundError" in result.error


def test_a_missing_path_inside_the_code_under_test_stays_a_failure(tmp_path):
    (tmp_path / "built_module.py").write_text(
        "def load():\n    return open('/nonexistent/dir/config.json').read()\n", encoding="utf-8"
    )
    result = _run_one("from built_module import load\nassert load()", tmp_path)
    # The refusal came from the built code's own frame. That is a product defect.
    assert result.outcome == acceptance.OUTCOME_FAIL
    assert result.error is None


def test_a_declared_package_absent_at_run_time_is_unverified(tmp_path):
    check = acceptance.ProgrammaticAcceptance(
        check_id="declared-tool",
        source="SPEC.md",
        intent="uses a declared dependency",
        code="import definitely_not_installed_pkg\nassert definitely_not_installed_pkg",
        requirements=(
            acceptance.AcceptanceRequirement(
                "python-package", "definitely-not-installed-pkg", "test"
            ),
        ),
    )
    result = acceptance.run_programmatic_acceptance(
        (check,), build_dir=tmp_path, target_dir=tmp_path, blueprint_dir=tmp_path
    )[0]
    assert result.outcome == acceptance.OUTCOME_UNVERIFIED
    assert "declared python-package" in (result.error or "")


def test_an_undeclared_missing_module_stays_the_expected_red_baseline(tmp_path):
    result = _run_one("import definitely_not_installed_pkg", tmp_path)
    assert result.outcome == acceptance.OUTCOME_FAIL
    assert result.error is None


def test_a_malformed_check_is_unverified_rather_than_charged_to_the_build(tmp_path):
    result = _run_one("assert result.returncode == 0", tmp_path)
    assert result.outcome == acceptance.OUTCOME_UNVERIFIED


def test_an_ordinary_assertion_failure_is_a_product_defect(tmp_path):
    result = _run_one("value = 1\nassert value == 2", tmp_path)
    assert result.outcome == acceptance.OUTCOME_FAIL


def test_a_passing_check_is_a_pass(tmp_path):
    assert _run_one("assert 1 == 1", tmp_path).outcome == acceptance.OUTCOME_PASS


def test_the_tally_separates_harness_defects_from_product_defects(tmp_path):
    results = (
        _run_one("assert 1 == 1", tmp_path),
        _run_one("value = 1\nassert value == 2", tmp_path),
        _run_one("open('/nonexistent/dir/config.json').read()", tmp_path),
    )
    tally = acceptance.tally_outcomes(results)
    assert (tally.passed, tally.failed, tally.unverified) == (1, 1, 1)
    assert tally.product_defects == 1
    assert tally.harness_defects == 1
    assert tally.to_dict()["total"] == 3


# --- Flagging doubtful criteria ----------------------------------------------
#
# Static analysis of an assertion is authoring guidance, never a gate. The analyzers are an
# unbounded blacklist grown one observed failure at a time, each with its own false-positive
# rate against legitimate snippets, and two were retracted after they began failing fixtures
# that had passed for weeks. Nothing is removed and nothing is excluded from grading: a
# criterion that truly cannot exercise the code reports UNVERIFIED at run time instead.

_TWO_CRITERIA_SPEC = """# FEATURE: Scoped Verification

## Programmatic Acceptance

### scoped-pattern
The verification command supports section selection.

```python
import subprocess

result = subprocess.run(["bash", "full_test.sh"], capture_output=True, text=True)
print(result.stdout)
assert result.returncode == 0
```

### scoped-number
The supplied harness supports example selection.

```python
import subprocess

result = subprocess.run(
    ["PYTHONPATH=sources", "python3", "spec_tests.py", "--number", "1"],
    shell=True,
    capture_output=True,
    text=True,
)
print(result.stdout)
assert "1 passed" in result.stdout
```

## User Acceptance

- None.
"""


# --- The staged-harness environment contract ---------------------------------
#
# Every criterion below is the shape a real plan emitted against the TOML conformance
# harness. Each cost a full build pass — and in three cases a whole UAT run — before it was
# caught here.

_STAGED_HARNESS = """#!/bin/sh
set -u

if [ -z "${DECODER:-}" ]; then
    echo "error: DECODER is not set; give the command that runs your decoder." >&2
    exit 2
fi

exec toml-test -decoder "${DECODER}" "$@"
"""

_STAGED_CALL_SPEC = """# FEATURE: Keys

## Programmatic Acceptance

### key-conformance
The implementation passes the key conformance slice.

```python
import subprocess

result = subprocess.run(
    ["sh", "sources/run_conformance.sh", "-run", "valid/key*"],
    capture_output=True,
    text=True,
)
print(result.stdout)
assert result.returncode == 0
```

## User Acceptance

- None.
"""


def _staged_sources(tmp_path):
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "run_conformance.sh").write_text(_STAGED_HARNESS, encoding="utf-8")
    return sources


# --- Flagging at grading time ------------------------------------------------


# --- Delimited acceptance blocks -------------------------------------------------------
#
# The delimited container exists because every boundary in the Markdown form was inferred, and an
# inferred boundary collides with ordinary proof content. A markup-processing target embeds
# fences, ``##`` lines, and ``Requires:``-shaped strings in its proofs as a matter of course.

_FENCE_BEARING_AC = '''\
# Feature

## Programmatic Acceptance

=== AC fenced-code-roundtrip ===
Intent: The parser renders a fenced code block.
Suite: scoped
Requires: executable=python3; scope=test
Sea Trials: st-001

import subprocess

sample = """
```
print("hi")
```
"""
## not a heading
### also not a heading
result = subprocess.run(["./parser"], input=sample, capture_output=True, text=True)
assert result.returncode == 0
=== END AC fenced-code-roundtrip ===

=== AC second-check ===
Intent: A second criterion that must survive the first.

result: int = 5
assert result == 5
=== END AC second-check ===
'''


def test_a_proof_body_containing_a_markdown_fence_parses_whole():
    """The defect this format replaces: a nested fence truncated the proof and ate its successor."""
    checks = acceptance.parse_programmatic_acceptance_text(_FENCE_BEARING_AC, source="FEATURE-X.md")

    assert [check.check_id for check in checks] == ["fenced-code-roundtrip", "second-check"]
    first = checks[0]
    assert "```" in first.code
    assert first.code.splitlines()[-1] == "assert result.returncode == 0"
    # Both bodies are real Python, which the truncated form never was.
    for check in checks:
        compile(check.code, "<ac>", "exec")


def test_markdown_structure_inside_a_proof_body_is_inert():
    checks = acceptance.parse_programmatic_acceptance_text(_FENCE_BEARING_AC, source="FEATURE-X.md")

    assert "## not a heading" in checks[0].code
    assert "### also not a heading" in checks[0].code


def test_block_declarations_are_read_and_do_not_leak_into_the_proof():
    checks = acceptance.parse_programmatic_acceptance_text(_FENCE_BEARING_AC, source="FEATURE-X.md")
    first, second = checks

    assert first.intent == "The parser renders a fenced code block."
    assert first.full_suite is True
    assert first.sea_trials == ("st-001",)
    assert first.requirements == (AcceptanceRequirement("executable", "python3", "test"),)
    assert not first.code.startswith("Intent:")
    # An annotated assignment on the first code line is code, not a declaration.
    assert second.code.startswith("result: int = 5")
    assert second.requirements == ()


@pytest.mark.parametrize(
    ("label", "text"),
    [
        ("unterminated", "=== AC a ===\nassert 1\n"),
        ("mismatched end id", "=== AC a ===\nassert 1\n=== END AC b ===\n"),
        (
            "duplicate id",
            "=== AC a ===\nassert 1\n=== END AC a ===\n=== AC a ===\nassert 2\n=== END AC a ===\n",
        ),
        ("stray end", "=== END AC a ===\n"),
        ("nested open", "=== AC a ===\nassert 1\n=== AC b ===\nassert 2\n=== END AC b ===\n"),
    ],
)
def test_a_malformed_block_is_a_hard_error_never_a_silent_truncation(label, text):
    with pytest.raises(ValueError):
        acceptance.parse_programmatic_acceptance_text(text, source="FEATURE-X.md")


def test_legacy_markdown_blueprints_still_parse():
    """Blueprints authored before the delimited format keep working."""
    checks = acceptance.parse_programmatic_acceptance_text(
        _TWO_CRITERIA_SPEC, source="FEATURE-X.md"
    )

    assert [check.check_id for check in checks] == ["scoped-pattern", "scoped-number"]


# --- The compile gate ------------------------------------------------------------------


def test_a_criterion_that_does_not_compile_is_reported_as_malformed():
    """Left ungated this is absorbed: SyntaxError in the snippet's own frame settles UNVERIFIED
    and costs the story nothing, so the criterion stops gating and the story closes green."""
    checks = acceptance.parse_programmatic_acceptance_text(
        "## Programmatic Acceptance\n\n"
        "=== AC truncated ===\n"
        "Intent: Truncated.\n\n"
        'sample = """\n'
        "=== END AC truncated ===\n",
        source="FEATURE-X.md",
    )
    flagged = acceptance.malformed_criteria(checks)

    assert [entry.check_id for entry in flagged] == ["truncated"]
    assert "not valid Python" in flagged[0].reason


def test_a_criterion_that_compiles_is_not_flagged():
    """The gate asks only whether the text is Python — never whether the assertion can pass."""
    checks = acceptance.parse_programmatic_acceptance_text(
        "## Programmatic Acceptance\n\n"
        "=== AC ok ===\n"
        "Intent: Fine.\n\n"
        "assert 1 == 2\n"
        "=== END AC ok ===\n",
        source="FEATURE-X.md",
    )

    assert acceptance.malformed_criteria(checks) == ()
    assert acceptance.syntax_defect("assert 1 == 2") is None


# --- Prepassed criteria: recorded for reporting, never gated ----------------------------


def test_prepassed_ids_accumulate_across_blocks(tmp_path):
    """Each block records its own baseline; score ac reads the union after the whole build."""
    evidence = tmp_path / "evidence"

    acceptance.record_prepassed_acceptance(evidence, ["character-insecure"])
    acceptance.record_prepassed_acceptance(evidence, ["leaf-blocks", "containers"])

    assert acceptance.read_prepassed_acceptance(evidence) == frozenset({
        "character-insecure",
        "leaf-blocks",
        "containers",
    })


def test_reading_prepassed_ids_without_a_build_is_empty_not_an_error(tmp_path):
    assert acceptance.read_prepassed_acceptance(tmp_path / "nothing-here") == frozenset()


def test_recording_no_prepassed_ids_writes_nothing(tmp_path):
    evidence = tmp_path / "evidence"

    acceptance.record_prepassed_acceptance(evidence, [])

    assert not (evidence / acceptance.PREPASSED_ACCEPTANCE_EVIDENCE).exists()


# --- Authoring defects: rejected where they are written ---------------------------------
#
# A criterion that no implementation can execute is a defect in the criterion. Caught at plan
# time it costs one validation pass; left to the build it costs a whole repair budget before the
# loop concludes what was knowable before any code existed.


def _criterion(code: str, *, encoding: str = "") -> acceptance.ProgrammaticAcceptance:
    declaration = f"Encoding: {encoding}\n" if encoding else ""
    text = f"=== AC example ===\nIntent: Example.\n{declaration}\n{code}\n=== END AC example ===\n"
    return acceptance.parse_programmatic_acceptance_text(text, source="FEATURE-Example.md")[0]


# ── R1: the oracle whitelist ──────────────────────────────────────────────────
# A criterion binds only when its expected value is one the author could not have got wrong.
# The failure this rule exists for is a real one: a criterion supplied a TOML literal string
# with doubled backslashes, re-typed the expectation with single ones, and failed a correct
# decoder six figures of tokens into a build.


def test_a_retyped_expectation_does_not_bind():
    """The exact criterion that sank Toml run 20260813.084830."""
    check = _criterion(
        "import json, subprocess\n"
        "source = 'raw = \\'C:\\\\\\\\Users\\\\\\\\nodejs\\'\\n'\n"
        "result = subprocess.run(['./toml-decoder'], input=source,"
        " capture_output=True, text=True)\n"
        "decoded = json.loads(result.stdout)\n"
        'assert decoded["raw"]["value"] == r"C:\\Users\\nodejs"\n'
    )

    assert check.retyped_expectations == ("C:\\Users\\nodejs",)
    assert not check.binding


def test_binding_the_value_to_a_name_makes_the_same_claim_bind():
    """Round trip: one escaping decision instead of two, so it cannot disagree with itself."""
    check = _criterion(
        "import json, subprocess\n"
        'raw = "C:\\\\Users\\\\nodejs"\n'
        "source = f\"raw = '{raw}'\\n\"\n"
        "result = subprocess.run(['./toml-decoder'], input=source,"
        " capture_output=True, text=True)\n"
        "decoded = json.loads(result.stdout)\n"
        'assert decoded["raw"]["value"] == raw\n'
    )

    assert check.retyped_expectations == ()
    assert check.binding


def test_a_status_oracle_binds():
    check = _criterion(
        "import subprocess\n"
        "result = subprocess.run(['./program'], capture_output=True, text=True)\n"
        "assert result.returncode == 0\n"
    )

    assert check.binding


def test_a_contract_token_binds():
    """`"string"` is read off a declared interface; there is nothing in it to mis-escape."""
    check = _criterion(
        "import json, subprocess\n"
        "result = subprocess.run(['./toml-decoder'], input='a = 1\\n',"
        " capture_output=True, text=True)\n"
        "decoded = json.loads(result.stdout)\n"
        'assert decoded["a"]["type"] == "integer"\n'
    )

    assert check.binding


def test_structural_claims_bind():
    """Membership, identity, and absence carry no re-typed bytes."""
    check = _criterion(
        "import json, subprocess\n"
        "result = subprocess.run(['./program'], capture_output=True, text=True)\n"
        "decoded = json.loads(result.stdout)\n"
        'assert "title" in decoded\n'
        'assert decoded.get("deleted") is None\n'
    )

    assert check.binding


def test_a_suite_bound_criterion_is_recognised():
    check = _criterion(
        "import os, subprocess\n"
        "result = subprocess.run(['sh', 'sources/run_conformance.sh', '-run', 'valid/*'],"
        " env={**os.environ, 'DECODER': './toml-decoder'}, capture_output=True, text=True)\n"
        "assert result.returncode == 0\n"
    )

    assert check.suite_bound
    assert check.binding


def test_an_echoed_input_literal_binds():
    """Asserting the bytes that went in came back out is the round trip, spelled once."""
    check = _criterion(
        "import subprocess\n"
        "result = subprocess.run(['./program'], input='line one\\n',"
        " capture_output=True, text=True)\n"
        "assert result.stdout == 'line one\\n'\n"
    )

    assert check.binding


def test_a_transform_expectation_does_not_bind():
    """A renderer's output cannot be derived from its input, so it is reported, not charged."""
    check = _criterion(
        "import subprocess\n"
        "result = subprocess.run(['./cmark'], input='# Hello\\n',"
        " capture_output=True, text=True)\n"
        "assert result.stdout == '<h1>Hello</h1>\\n'\n"
    )

    assert not check.binding
    assert check.retyped_expectations == ("<h1>Hello</h1>\n",)


def test_an_unparseable_criterion_reports_no_oracle_finding():
    """The compile gate owns unparseable code; two reports of one fault help nobody."""
    assert _criterion("assert render( ==").retyped_expectations == ()
