# FEATURE: Filter Execution

| Field       | Value |
|-------------|-------|
| Version     | 20260722 V1 |
| Description | Defines conversion of Markdown input into HTML through the standalone filter contract. |
| Depends On  | ARCHITECTURE.md |
| Provides    | `convert(md: str) -> str`, stdin-to-stdout conversion |
| Phase       | 2 |

## Purpose

The filter receives the complete Markdown document from standard input and emits only the corresponding HTML on standard output. It has no arguments, configuration, persistence, or external dependencies.

## Behavior

The conversion entry point accepts a Unicode string and returns CommonMark HTML. The executable reads all standard input and writes the conversion result. NUL characters are replaced with U+FFFD before rendering.

## Programmatic Acceptance

### filter-stdin-stdout
The executable converts a representative heading through the subprocess interface.

Sea Trials: st-001

```python
import subprocess
result = subprocess.run(
    ["python3", "mycommonmark.py"],
    input=b"# Hello\n",
    capture_output=True,
    check=False,
)
assert result.returncode == 0
assert result.stderr == b""
assert b"<h1>Hello</h1>" in result.stdout
```

### filter-nul-replacement
NUL input is rendered as the Unicode replacement character.

Sea Trials: st-005

```python
from mycommonmark import convert
assert "\ufffd" in convert("before\x00after")
assert "\x00" not in convert("before\x00after")
```

### filter-no-side-effects
Conversion does not create files or require configuration.

```python
import os
import tempfile
from mycommonmark import convert

with tempfile.TemporaryDirectory() as directory:
    before = set(os.listdir(directory))
    assert "<p>text</p>" in convert("text")
    assert set(os.listdir(directory)) == before
```

## User Acceptance

- The filter produces no visible output other than converted HTML.

## Guardrails

- The filter accepts no configuration.
- The filter produces no side effects.
- NUL characters never reach rendered output unchanged.

## Open Questions

- None.
