# Blueprint Analysis: CommonMark Parser

## Story List

### Feature: Filter Execution Contract

| ID | Story | High-level AC |
|---|---|---|
| FILTER-001 | Convert Markdown from stdin to HTML on stdout | The executable reads all stdin and writes only converted HTML to stdout. |
| FILTER-002 | Preserve standalone filter operation | The executable requires no arguments or configuration and has no side effects. |

### Feature: Block Parsing

| ID | Story | High-level AC |
|---|---|---|
| BLOCKS-001 | Parse leaf blocks | The parser handles paragraphs, headings, thematic breaks, indented code, fenced code, and HTML blocks according to the supplied specification. |
| BLOCKS-002 | Parse container blocks | The parser handles block quotes, lists, nesting, laziness, and tight or loose list rendering. |
| BLOCKS-003 | Resolve link reference definitions | Definitions are collected across document containers and resolved with CommonMark precedence and label normalization. |

### Feature: Inline Parsing

| ID | Story | High-level AC |
|---|---|---|
| INLINE-001 | Parse escapes, entities, code spans, and line breaks | Inline output follows the specified escaping, reference, code-span, hard-break, and soft-break rules. |
| INLINE-002 | Parse emphasis and strong emphasis | Delimiter-run behavior produces the specified nested emphasis and strong-emphasis structure. |
| INLINE-003 | Parse links and images | Inline, reference, collapsed, shortcut, and image forms render with correct destinations, titles, labels, and nesting restrictions. |
| INLINE-004 | Parse autolinks and raw HTML | URI/email autolinks and valid raw HTML are rendered without inappropriate escaping. |

### Feature: Conformance Verification

| ID | Story | High-level AC |
|---|---|---|
| VERIFY-001 | Execute the supplied CommonMark conformance harness | The program completes harness execution without execution errors and reports per-example results and a summary. |

## Surfaced Acceptance Criteria

The analyze step has surfaced these acceptance criteria for `drydock plan` to fold into the relevant story's typed specification.

| ID | Story ID | Criterion |
|---|---|---|
| AC-001 | FILTER-001 | NUL characters are replaced with U+FFFD before HTML output. |
| AC-002 | VERIFY-001 | The program is executable as a subprocess using the supplied stdin-to-stdout harness contract. |

## Source Inventory

| Path | Content kind | Disposition | Reason |
|---|---|---|---|
| `sources/.drydock-import` | text | analyzed | readable UTF-8 |
| `sources/.gitkeep` | text | analyzed | readable UTF-8 |
| `sources/INSTRUCTIONS.md` | markdown | analyzed | readable UTF-8 |
| `sources/cmark.py` | code | analyzed | readable UTF-8 |
| `sources/normalize.py` | code | analyzed | readable UTF-8 |
| `sources/spec.txt` | text | chunked | split into 18 bounded chunks |
| `sources/spec_tests.py` | code | analyzed | readable UTF-8 |

## Relationship Model

| Source or group | Relationship type | Related source or group | Evidence | Delivery implication |
|---|---|---|---|---|
| `sources/INSTRUCTIONS.md` | instruction-to-test | `sources/spec_tests.py` | Defines subprocess invocation, stdin/stdout, and conformance command. | Implement the executable contract before harness verification. |
| `sources/spec.txt` | normative specification and conformance corpus | `sources/spec_tests.py` | The specification embeds the executable examples consumed by the harness. | Treat the corpus as the release-level verification input. |
| `sources/spec_tests.py` | test-kit-to-implementation | `sources/cmark.py` | Runs the candidate program and compares normalized HTML. | Keep implementation output compatible with subprocess execution. |
| `sources/spec_tests.py` | test-kit-to-implementation | `sources/normalize.py` | Normalizes HTML before comparison. | Use normalized comparisons for story tests; retain complete-corpus verification for Sea Trials. |
| `sources/cmark.py` | reference-to-replacement | `sources/INSTRUCTIONS.md` | Provides the existing library or subprocess adapter used by the harness. | The candidate executable replaces the subprocess target, not the harness adapter. |

## Source Roles

| Path | Role | Plan disposition | Build disposition |
|---|---|---|---|
| `sources/.drydock-import` | source reference | context | none |
| `sources/.gitkeep` | asset | exclude | none |
| `sources/INSTRUCTIONS.md` | author intent | compass | prompt-only |
| `sources/cmark.py` | reference implementation | context | prompt-only |
| `sources/normalize.py` | test helper | context | stage |
| `sources/spec.txt` | normative specification and conformance corpus | context | stage |
| `sources/spec_tests.py` | conformance harness | context | stage |

## Planning Instructions

### Delivery Shape

The system is a standalone Markdown-to-HTML filter. It receives Markdown through stdin and emits HTML through stdout. The implementation flow is block parsing, link-reference collection, inline parsing, rendering, and subprocess conformance verification.

### Story Realization Map

- `FILTER-001`: executable filter scope; evidence `sources/INSTRUCTIONS.md`; requires capability and acceptance contract.
- `FILTER-002`: no-argument, no-configuration, no-side-effect scope; evidence `sources/INSTRUCTIONS.md`; requires capability and acceptance contract.
- `BLOCKS-001`: leaf block parser; evidence `sources/spec.txt`; requires capability and focused tests.
- `BLOCKS-002`: container and list parser; evidence `sources/spec.txt`; requires capability and focused tests.
- `BLOCKS-003`: reference-definition collection and resolution; evidence `sources/spec.txt`; requires capability and focused tests.
- `INLINE-001`: escapes, entities, code spans, and breaks; evidence `sources/spec.txt`; requires capability and focused tests.
- `INLINE-002`: emphasis delimiter processing; evidence `sources/spec.txt` and its parsing-strategy appendix; requires capability and focused tests.
- `INLINE-003`: links and images; evidence `sources/spec.txt`; requires capability and focused tests.
- `INLINE-004`: autolinks and raw HTML; evidence `sources/spec.txt`; requires capability and focused tests.
- `VERIFY-001`: conformance harness execution; evidence `sources/spec_tests.py` and `sources/normalize.py`; requires integration and acceptance contract.

### Test and Acceptance Strategy

Focused tests cover each block and inline story, including representative edge cases from the corpus. Integration tests verify executable stdin/stdout behavior and failure handling. Final Sea Trials run the supplied conformance harness; complete-corpus results are not duplicated as story acceptance criteria.

### Sequencing and Dependencies

Implement the filter contract first, then block parsing, reference collection, inline parsing, and rendering. Parser behavior must precede normalization-based verification. The supplied fixtures and harness must be staged before final verification. No external services or persistence dependencies are described.

### Source Conflicts and Gaps

No source contradiction blocks decomposition. The implementation language and concrete technology stack are not selected. The desired passing threshold is described as a project goal but no human-owned numeric threshold is fixed; this remains a Sea Trials measurement question.

## Analysis Notes
generated: 2026-07-22
blueprint: /mnt/c/Users/barlo/projects/drydock/targets/commonmark/blueprint

Quality: Questions
  blockers: 0
  questions: 3
  features: 4
  stories: 10
  stack: not declared
  display_name: CommonMark Parser
  short_description: A standalone stdin-to-stdout parser that converts CommonMark 0.31.2 Markdown into HTML.

None.
