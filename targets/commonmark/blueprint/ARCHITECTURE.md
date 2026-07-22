# ARCHITECTURE: CommonMark Parser

| Field       | Value |
|-------------|-------|
| Version     | 20260722 V1 |
| Description | Module boundaries, execution flow, and verification interfaces for the CommonMark parser. |
| Depends On  | COMPASS.md |
| Provides    | commonmark.__main__:main, commonmark.api.convert, commonmark.blocks.parse_document, commonmark.inlines.parse_inlines, commonmark.render.render_document |
| Phase       | 1 |

## System Shape

The system is a CLI filter packaged as a Python module. The runtime entry point is
`python -m commonmark`, which reads all of standard input, converts the Markdown document, and
writes HTML to standard output without reading configuration or mutating the filesystem.

## Execution Flow

1. `commonmark.__main__.main()` reads UTF-8 text from standard input and normalizes `U+0000` to
   `U+FFFD`.
2. `commonmark.api.convert(markdown: str) -> str` orchestrates parsing and rendering for a complete
   document.
3. `commonmark.blocks.parse_document(markdown: str)` performs phase-one block parsing, builds the
   document tree, and collects link reference definitions with document-wide scope.
4. `commonmark.inlines.parse_inlines(text: str, references: dict)` performs phase-two inline
   parsing over paragraph, heading, and other inline-bearing nodes.
5. `commonmark.render.render_document(document)` renders the syntax tree to HTML suitable for the
   supplied normalization harness.

## Module Responsibilities

| Module | Responsibility |
|--------|----------------|
| `src/commonmark/__main__.py` | CLI entry point; stdin/stdout contract only |
| `src/commonmark/api.py` | High-level conversion orchestration |
| `src/commonmark/blocks.py` | Block parsing, container handling, and link-reference collection |
| `src/commonmark/inlines.py` | Inline parsing for code spans, emphasis, links, images, autolinks, raw HTML, and line breaks |
| `src/commonmark/render.py` | HTML rendering and escaping rules |
| `src/commonmark/model.py` | Block and inline node dataclasses plus reference-definition data |
| `src/commonmark/html.py` | Shared HTML escaping and URL/title normalization helpers |
| `tests/` | Story-focused tests plus conformance-harness integration tests |

## Parsing Boundaries

- Phase one owns line classification, block continuation, list tightness, raw HTML block handling,
  fenced and indented code handling, heading recognition, paragraph formation, and reference
  definition extraction.
- Phase two owns textual inline parsing only after block structure is finalized.
- Code spans, fenced code blocks, indented code blocks, autolinks, and raw HTML tags bind more
  tightly than emphasis parsing.
- The renderer writes HTML only from the syntax tree; parsing modules do not emit HTML directly.

## Verification Strategy

- Story-level tests exercise the CLI contract, block structure, inline behavior, and targeted edge
  cases from the corpus.
- The conformance harness is preserved as an integration input and is staged into the target
  workspace for final verification.
- Harness normalization is treated as the acceptance oracle for HTML equivalence; the implementation
  renderer targets compatibility with that normalization behavior.

## Module Ownership

| Boundary | Owning module | Allowed low-level access |
|----------|---------------|--------------------------|
| CLI process boundary | `commonmark.__main__` | `sys.stdin`, `sys.stdout`, process exit handling |
| Conversion orchestration | `commonmark.api` | Calls block parser, inline parser, and renderer |
| Syntax tree state | `commonmark.model` | Dataclasses and immutable-like node structures |
| HTML rendering helpers | `commonmark.html` | HTML escaping, URL normalization, attribute escaping |
| Verification adapter | `tests/` and harness wrapper code | `subprocess`, staged corpus files |

## Programmatic Acceptance

### architecture-entrypoint
The package exposes the documented CLI and conversion entry points.

```python
import importlib

main_module = importlib.import_module("commonmark.__main__")
api_module = importlib.import_module("commonmark.api")

assert hasattr(main_module, "main")
assert callable(main_module.main)
assert hasattr(api_module, "convert")
assert callable(api_module.convert)
```

### architecture-parser-modules
The parser package separates block parsing, inline parsing, and rendering modules.

```python
import importlib

blocks = importlib.import_module("commonmark.blocks")
inlines = importlib.import_module("commonmark.inlines")
render = importlib.import_module("commonmark.render")

assert hasattr(blocks, "parse_document")
assert hasattr(inlines, "parse_inlines")
assert hasattr(render, "render_document")
```

### architecture-cli-contract
The module entry point behaves as a stdin-to-stdout filter without stderr noise on success.

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
assert result.stderr == b""
assert "<h1>Title</h1>" in result.stdout.decode("utf-8")
```

## User Acceptance

- None.

## Guardrails

- The CLI entry point does not own parsing rules; it delegates to importable modules.
- Parsing modules do not write directly to standard output.
- Verification helpers do not reach external services or require network access.

## Open Questions

- None.
