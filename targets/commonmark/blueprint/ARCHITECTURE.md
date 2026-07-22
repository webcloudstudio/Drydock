# ARCHITECTURE: CommonMark

| Field       | Value |
|-------------|-------|
| Version     | 20260722 V1 |
| Description | Defines the standalone CommonMark parsing executable and its module boundaries. |
| Depends On  | — |
| Provides    | `convert(md: str) -> str`, `python3 mycommonmark.py` |
| Phase       | 1 |

## System Shape

CommonMark is a standalone Python executable filter. It reads Markdown from standard input and writes HTML to standard output. It accepts no arguments, configuration, or external services.

## Module Boundaries

| Module | Responsibility |
|---|---|
| `mycommonmark.py` | Public conversion entry point and executable filter |
| Block parser | Block structure, containers, lists, code blocks, and HTML blocks |
| Inline parser | Inline structure, references, emphasis, links, images, autolinks, and raw HTML |
| Renderer | CommonMark HTML serialization and escaping |

The implementation replaces NUL characters with U+FFFD before parsing. Code blocks and code spans remain literal. Raw HTML remains unescaped where required.

## Programmatic Acceptance

### architecture-entrypoint
The conversion entry point is importable and callable.

Sea Trials: st-001

```python
from mycommonmark import convert
assert callable(convert)
assert isinstance(convert("# Heading"), str)
```

### architecture-filter-contract
The executable accepts Markdown on standard input and emits HTML on standard output.

Sea Trials: st-001

```python
import subprocess
result = subprocess.run(
    ["python3", "mycommonmark.py"],
    input=b"# Heading\n",
    capture_output=True,
    check=False,
)
assert result.returncode == 0
assert b"<h1>Heading</h1>" in result.stdout
```

### architecture-no-configuration
The executable rejects unexpected arguments.

```python
import subprocess
result = subprocess.run(
    ["python3", "mycommonmark.py", "--unexpected"],
    input=b"",
    capture_output=True,
    check=False,
)
assert result.returncode != 0
```

## User Acceptance

- The executable is usable as a standalone stdin-to-stdout filter.

## Guardrails

- The parser does not read configuration or contact external services.
- The parser does not create files or other side effects.
- The parser preserves literal code content and required raw HTML.

## Open Questions

- None.
