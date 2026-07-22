# COMPASS: CommonMark

| Field       | Value |
|-------------|-------|
| Version     | 20260722 V1 |
| Description | Product intent, execution constraints, and permanent guardrails for the CommonMark parser. |
| Depends On  | — |
| Provides    | — |
| Phase       | 1 |

## Compass

CommonMark is a standalone executable filter for converting CommonMark 0.31.2 Markdown into HTML.
It serves the supplied subprocess conformance harness and prioritizes specification fidelity across
block structure, inline structure, links, images, autolinks, and raw HTML.

## Constraints

- Input is read from standard input.
- Output is written to standard output.
- The executable accepts no arguments and requires no configuration.
- The implementation conforms to CommonMark 0.31.2 behavior.
- The supplied harness invokes the program as a subprocess.
- The default implementation stack is Python and packages the code under `src/commonmark`.

## Guardrails

- The parser does not create side effects or depend on external services.
- The parser does not treat code blocks or code spans as parsed Markdown.
- The parser replaces NUL characters with `U+FFFD`.
- The parser preserves raw HTML where the specification requires it.

## Programmatic Acceptance

- None. Product intent and guardrails are proven by the implementing feature specifications and their executable assertions.

## User Acceptance

- None.

## Open Questions

- None.
