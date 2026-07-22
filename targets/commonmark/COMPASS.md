# COMPASS: CommonMark Parser

## Compass
CommonMark Parser is a standalone executable filter for converting CommonMark 0.31.2 Markdown into HTML. It serves the supplied subprocess conformance harness and must prioritize specification fidelity across block structure, inline structure, links, images, autolinks, and raw HTML.

## Constraints
- Input is read from standard input.
- Output is written to standard output.
- The executable accepts no arguments and requires no configuration.
- The implementation must conform to CommonMark 0.31.2 behavior.
- The supplied harness invokes the program as a subprocess.

## Guardrails
- Do not create side effects or depend on external services.
- Do not treat code blocks or code spans as parsed Markdown.
- Replace NUL characters with U+FFFD.
- Preserve raw HTML where the specification requires it.
