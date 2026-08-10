"""Unit tests for Programmatic Acceptance parsing and its execution budget."""

from __future__ import annotations

import os
import subprocess
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


def test_strict_target_execution_does_not_fall_back_to_drydock_python(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='target'\nversion='0'\n")
    check = ProgrammaticAcceptance("strict", "FEATURE-X.md", "Strict.", "assert True")

    result = run_programmatic_acceptance(
        (check,),
        build_dir=tmp_path,
        target_dir=tmp_path,
        blueprint_dir=tmp_path,
        strict_target=True,
    )[0]

    assert not result.passed
    assert result.interpreter == ""
    assert result.error == "acceptance environment unavailable: Target Python project has no .venv"


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


# --- Removing unsatisfiable criteria -----------------------------------------
#
# The Manifest is the build graph. A criterion that cannot pass by construction makes the
# block that owns it unbuildable, and no repair pass may rewrite it, so it is stripped at plan
# time rather than carried into a build that is guaranteed to fail.

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


def test_unsatisfiable_criterion_is_removed_and_the_rest_is_kept():
    from drydock.acceptance import drop_unsatisfiable_acceptance

    cleaned, dropped = drop_unsatisfiable_acceptance(_TWO_CRITERIA_SPEC, source="FEATURE-X.md")

    assert [d.check_id for d in dropped] == ["scoped-number"]
    assert "the intended command never runs" in dropped[0].reason
    # The removal takes the heading, its intent prose, and its fence together.
    assert "scoped-number" not in cleaned
    assert "PYTHONPATH=sources" not in cleaned
    assert "### scoped-pattern" in cleaned
    assert "bash" in cleaned
    # Surrounding structure survives intact.
    assert cleaned.startswith("# FEATURE: Scoped Verification")
    assert "## User Acceptance" in cleaned


def test_a_hardcoded_conformance_tally_is_removed_at_plan_time():
    from drydock.acceptance import drop_unsatisfiable_acceptance

    spec = (
        "# FEATURE: Conformance Harness\n\n"
        "## Programmatic Acceptance\n\n"
        "### complete-conformance-suite\n"
        "The complete supplied suite passes without skipped cases.\n\n"
        "```python\n"
        "import subprocess\n\n"
        'result = subprocess.run(["sh", "full_test.sh"], capture_output=True, text=True)\n'
        "print(result.stdout)\n"
        "assert result.returncode == 0\n"
        'assert "valid tests: 210 passed, 0 failed" in result.stdout\n'
        "```\n"
    )

    cleaned, dropped = drop_unsatisfiable_acceptance(spec, source="FEATURE-Conformance.md")

    assert [d.check_id for d in dropped] == ["complete-conformance-suite"]
    assert "column-align" in dropped[0].reason
    assert "210 passed" not in cleaned


def test_a_satisfiable_spec_is_returned_untouched():
    from drydock.acceptance import drop_unsatisfiable_acceptance

    good = _TWO_CRITERIA_SPEC.split("### scoped-number")[0] + "## User Acceptance\n\n- None.\n"
    cleaned, dropped = drop_unsatisfiable_acceptance(good, source="FEATURE-X.md")

    assert dropped == ()
    assert cleaned == good


def test_removing_every_criterion_leaves_a_well_formed_empty_section():
    # The hole is reported by the plan's own assertion gate; the file must stay parseable.
    from drydock.acceptance import drop_unsatisfiable_acceptance

    only_bad = (
        "# FEATURE: X\n\n## Programmatic Acceptance\n\n"
        "### broken\nIt never runs.\n\n"
        "```python\n"
        "import subprocess\n"
        "subprocess.run(['A=1', 'prog'], shell=True)\n"
        "```\n\n"
        "## Guardrails\n\n- None.\n"
    )
    cleaned, dropped = drop_unsatisfiable_acceptance(only_bad, source="FEATURE-X.md")

    assert [d.check_id for d in dropped] == ["broken"]
    assert "- None." in cleaned
    assert "## Guardrails" in cleaned


def test_spec_without_acceptance_is_untouched():
    from drydock.acceptance import drop_unsatisfiable_acceptance

    text = "# FEATURE: X\n\n## Guardrails\n\n- None.\n"
    assert drop_unsatisfiable_acceptance(text, source="FEATURE-X.md") == (text, ())
