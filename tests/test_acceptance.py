"""Unit tests for Programmatic Acceptance parsing and its execution budget."""

from __future__ import annotations

from pathlib import Path

from drydock.acceptance import (
    CORPUS_TIMEOUT_SECONDS,
    TIMEOUT_SECONDS,
    ProgrammaticAcceptance,
    parse_programmatic_acceptance,
    run_programmatic_acceptance,
)

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
Corpus: full
Sea Trials: st-004
Every normative example converts correctly.

```python
import subprocess, sys
subprocess.run([sys.executable, "sources/spec_tests.py"], check=True)
```
"""


def _checks(tmp_path: Path):
    path = tmp_path / "FEATURE-Verification.md"
    path.write_text(_SPEC, encoding="utf-8")
    return {check.check_id: check for check in parse_programmatic_acceptance(path)}


def test_corpus_full_marker_is_parsed(tmp_path):
    checks = _checks(tmp_path)

    assert checks["conformance-full"].full_corpus is True
    assert checks["assets-present"].full_corpus is False


def test_full_corpus_check_gets_the_long_execution_budget(tmp_path):
    """A story timeout would kill a real conformance run partway and report a false failure."""
    checks = _checks(tmp_path)

    assert checks["conformance-full"].timeout_seconds == CORPUS_TIMEOUT_SECONDS
    assert checks["assets-present"].timeout_seconds == TIMEOUT_SECONDS
    assert CORPUS_TIMEOUT_SECONDS > TIMEOUT_SECONDS


def test_marker_lines_do_not_leak_into_the_stated_intent(tmp_path):
    checks = _checks(tmp_path)

    assert checks["conformance-full"].intent == "Every normative example converts correctly."
    assert "Corpus:" not in checks["conformance-full"].intent
    assert "Sea Trials:" not in checks["conformance-full"].intent


def test_sea_trial_references_still_parse_alongside_the_corpus_marker(tmp_path):
    checks = _checks(tmp_path)

    assert checks["conformance-full"].sea_trials == ("st-004",)
    assert checks["assets-present"].sea_trials == ("st-003",)


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
