# FEATURE: Filter Execution

| Field       | Value |
|-------------|-------|
| Version     | 20260722 V1 |
| Description | The executable filter reads Markdown from standard input and writes rendered HTML to standard output. |
| Depends On  | ARCHITECTURE.md, COMPASS.md |
| Provides    | stdin -> stdout markdown filter, commonmark.api.convert |
| Phase       | 2 |

## Purpose

This feature defines the executable filter contract: one process invocation, no arguments, no
configuration, and no side effects beyond standard output.

## Trigger

The harness or a user starts the executable and supplies a Markdown document on standard input.

## Sequence

1. Read the entire input stream as text.
2. Replace every `U+0000` character with `U+FFFD` before parsing.
3. Convert the document through the parser and renderer pipeline.
4. Write only the rendered HTML to standard output.
5. Exit successfully when conversion succeeds.

## Reads

- Standard input bytes decoded as UTF-8 text.

## Writes

- Standard output HTML bytes.

## Operational Behavior

- The executable accepts no command-line arguments.
- The executable does not read configuration files or environment variables to alter parsing
  behavior.
- The executable does not write files, mutate process state outside its own memory, or contact
  external services.

## Programmatic Acceptance

### filter-stdin-stdout-contract
The executable reads Markdown from standard input and writes the corresponding HTML to standard output.

Sea Trials: st-001

```python
import subprocess
import sys

result = subprocess.run(
    [sys.executable, "-m", "commonmark"],
    input="Hello\n".encode("utf-8"),
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=False,
)

assert result.returncode == 0
assert result.stderr == b""
assert result.stdout.decode("utf-8") == "<p>Hello</p>\n"
```

### filter-heading-render
The CLI produces heading HTML for a representative CommonMark heading input.

```python
import subprocess
import sys

result = subprocess.run(
    [sys.executable, "-m", "commonmark"],
    input="# Title\n".encode("utf-8"),
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=False,
)

assert result.returncode == 0
assert result.stdout.decode("utf-8") == "<h1>Title</h1>\n"
```

### filter-no-arguments
The executable accepts no command-line arguments and fails fast on unexpected CLI parameters.

```python
import subprocess
import sys

result = subprocess.run(
    [sys.executable, "-m", "commonmark", "--unexpected"],
    input=b"",
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=False,
)

assert result.returncode != 0
assert result.stdout == b""
```

### filter-nul-replacement
NUL input is replaced with the Unicode replacement character before rendering.

Sea Trials: st-005

```python
from commonmark.api import convert

html = convert("A\0B\n")
assert html == "<p>A\ufffdB</p>\n"
```

## User Acceptance

- None.

## Guardrails

- The feature does not add CLI flags, configuration files, or side-effectful startup behavior.
- Successful execution writes only rendered HTML to standard output.
- NUL replacement happens before block or inline parsing.

## Open Questions

- None.
