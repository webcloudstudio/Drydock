# FEATURE: Conformance Verification

| Field       | Value |
|-------------|-------|
| Version     | 20260722 V4 |
| Description | Verification stages the imported CommonMark corpus and harness and proves clean subprocess execution before final scoring. |
| Depends On  | ARCHITECTURE.md, FEATURE-Filter-Execution.md, FEATURE-Block-Parsing.md, FEATURE-Inline-Parsing.md |
| Provides    | tests/test_conformance_harness.py, staged/spec.txt, staged/spec_tests.py, staged/normalize.py |
| Phase       | 5 |

## Purpose

This feature preserves the imported CommonMark corpus and harness as target-local verification
inputs and defines the project’s clean subprocess execution proof.

## Trigger

After the parser implementation stories complete, the verification story stages the harness and
runs focused integration checks. Full-corpus threshold scoring remains a final Sea Trials activity.

## Sequence

1. Stage `spec.txt`, `spec_tests.py`, and `normalize.py` into the target test assets.
2. Add story-scoped integration tests that invoke the parser as a subprocess through the same
   stdin-to-stdout contract used by the harness.
3. Verify focused harness execution on selected examples completes without execution errors.
4. Preserve the full-corpus command for final project scoring rather than story-level gating.

## Reads

- Imported CommonMark corpus and harness files.
- Built parser executable.

## Writes

- Target-local staged conformance assets.
- Integration tests that exercise the subprocess harness contract.

## Operational Behavior

- Story-level verification proves clean subprocess execution, not final release score.
- HTML normalization is part of the integration acceptance surface because the supplied harness uses
  normalized comparison.
- The feature does not redefine the corpus threshold; the answered questionnaire fixes that as
  `100% passing threshold` for final scoring.

## Programmatic Acceptance

### verify-staged-assets
The target workspace stages the imported conformance corpus and helper scripts.

```python
from pathlib import Path

assert Path("tests/conformance/spec.txt").is_file()
assert Path("tests/conformance/spec_tests.py").is_file()
assert Path("tests/conformance/normalize.py").is_file()
```

### verify-subprocess-clean-execution
A focused harness run completes without execution errors for a selected example set.

Sea Trials: st-002

```python
import subprocess
import sys

result = subprocess.run(
    [
        sys.executable,
        "tests/conformance/spec_tests.py",
        "--spec",
        "tests/conformance/spec.txt",
        "--program",
        f"{sys.executable} -m commonmark",
        "--pattern",
        "ATX headings",
    ],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=False,
)

stdout = result.stdout.decode("utf-8")
assert "errored" in stdout
assert "0 errored" in stdout
```

### verify-harness-contract-output
The harness adapter reports pass and fail totals in the expected summary format.

```python
import subprocess
import sys
import re

result = subprocess.run(
    [
        sys.executable,
        "tests/conformance/spec_tests.py",
        "--spec",
        "tests/conformance/spec.txt",
        "--program",
        f"{sys.executable} -m commonmark",
        "--number",
        "1",
    ],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=False,
)

summary = result.stdout.decode("utf-8").strip().splitlines()[-1]
assert re.fullmatch(r"\\d+ passed, \\d+ failed, \\d+ errored, \\d+ skipped", summary)
```

## User Acceptance

- None.

## Guardrails

- Full-corpus pass-threshold measurement remains a final Sea Trials check and is not duplicated as a story assertion.
- Verification does not replace the authoritative imported corpus with re-authored examples.
- Harness execution remains subprocess-based.

## Open Questions

- None.
