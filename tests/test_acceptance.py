"""Unit tests for Programmatic Acceptance parsing and its execution budget."""

from __future__ import annotations

from pathlib import Path

from drydock.acceptance import (
    CORPUS_TIMEOUT_SECONDS,
    TIMEOUT_SECONDS,
    parse_programmatic_acceptance,
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
