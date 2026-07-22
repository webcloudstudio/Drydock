# FEATURE: Conformance Verification

| Field       | Value |
|-------------|-------|
| Version     | 20260722 V1 |
| Description | Defines focused subprocess verification using the supplied CommonMark conformance assets. |
| Depends On  | ARCHITECTURE.md, FEATURE-Filter-Execution.md, FEATURE-Block-Parsing.md, FEATURE-Inline-Parsing.md |
| Provides    | focused subprocess conformance verification |
| Phase       | 5 |

## Purpose

The verification workflow executes selected CommonMark 0.31.2 examples through the parser subprocess and compares normalized HTML. The complete corpus remains a final Sea Trials measurement.

## Behavior

The implementation remains compatible with the supplied harness contract: the parser runs as a subprocess, accepts Markdown on standard input, emits UTF-8 HTML on standard output, and completes selected examples without execution errors.

## Programmatic Acceptance

### verify-subprocess-execution
A selected conformance example completes without an execution error.

Sea Trials: st-002

```python
import subprocess
result = subprocess.run(
    ["python3", "mycommonmark.py"],
    input=b"## Selected example\n",
    capture_output=True,
    check=False,
)
assert result.returncode == 0
assert result.stderr == b""
assert b"<h2>Selected example</h2>" in result.stdout
```

### verify-assets-staged
The focused verification assets are present.

```python
from pathlib import Path
assert Path("blueprint/sources/spec.txt").is_file()
assert Path("blueprint/sources/spec_tests.py").is_file()
assert Path("blueprint/sources/normalize.py").is_file()
```

### verify-summary-format
The supplied harness reports pass and fail totals for a bounded selected example.

```python
import subprocess
result = subprocess.run(
    [
        "python3",
        "blueprint/sources/spec_tests.py",
        "--spec",
        "blueprint/sources/spec.txt",
        "--program",
        "python3 mycommonmark.py",
        "--number",
        "1",
    ],
    capture_output=True,
    text=True,
    check=False,
)
assert result.returncode in (0, 1)
assert "passed" in result.stdout
assert "failed" in result.stdout
assert "errored" in result.stdout
```

## User Acceptance

- The supplied harness can invoke the executable as documented.

## Guardrails

- Focused verification does not substitute for final complete-corpus scoring.
- Verification does not contact external services or create project data outside its tracking output.

## Open Questions

- None.
