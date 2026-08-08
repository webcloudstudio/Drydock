# Build Instructions: CommonMark Parser

## Objective

Build a CommonMark parser that conforms to the specification in `spec.txt`
(CommonMark 0.31.2). Correctness is measured by the conformance test suite in
`test/`. The goal is to maximize the number of passing spec examples.

## Interface Contract

The program is a filter: read Markdown from **stdin**, write HTML to **stdout**.
No arguments, no config, no side effects.

Minimal shape (`mycommonmark.py`):

```python
#!/usr/bin/env python3
import sys

def convert(md: str) -> str:
    ...  # your implementation

if __name__ == "__main__":
    md = sys.stdin.read()
    sys.stdout.write(convert(md))
```

Language is not fixed — any executable that satisfies the stdin→stdout contract
works, since the harness invokes it as a subprocess. Python 3 is the default.

## Test / Verification Process

Imported UAT assets are flattened into the completed application's `sources/` directory. Run the
conformance suite from the completed application root:

```bash
env PYTHONPATH=sources python3 sources/spec_tests.py \
  --spec sources/spec.txt \
  --program "python3 mycommonmark.py"
```

Mechanics: `spec_tests.py` extracts every fenced `example` block from `spec.txt`
(Markdown input + expected HTML), pipes each input through your program via
stdin, normalizes both actual and expected HTML (`sources/normalize.py` parses and
canonicalizes the DOM so insignificant whitespace/attribute differences are
ignored), and compares.

Output is per-example diffs plus a summary line:

```
NNN passed, NNN failed, N errored, N skipped
```

The passed count is the correctness score. Exit code = failed + errored.

### Useful flags

- `-P "ATX headings"` / `--pattern "..."` — run only sections matching the regex.
  Use this to develop one construct at a time.
- `-n N` / `--number N` — run only example number N.
- `--track results.json` — persist pass/fail state; report only regressions and
  `fixed!` transitions between runs. Best signal while iterating.
- `-d` / `--dump-tests` — emit all examples as JSON to drive your own harness.
- `--no-normalize` — strict byte-for-byte comparison (stricter than scoring).

## Suggested Implementation Order

CommonMark parsing is two phases: **block structure** first, then **inline
parsing** on the block contents. Implement in roughly this order and watch the
section pattern scores climb:

1. Blocks: paragraphs, thematic breaks, ATX headings, setext headings,
   indented code, fenced code, HTML blocks, block quotes, lists (the hardest
   block construct — lazy continuation, list-item nesting).
2. Inlines: backslash escapes, entity/numeric references, code spans, emphasis
   and strong emphasis (the delimiter-run algorithm — nontrivial), links and
   images (including reference link definitions), autolinks, raw HTML, hard
   line breaks.

The spec text is normative and contains the algorithms (see the "Appendix: A
parsing strategy" section). Follow it directly rather than reinventing rules.

## Files the LLM Needs

- `sources/spec.txt` — the specification AND the test corpus. Primary input. Required.
- `sources/spec_tests.py`, `sources/cmark.py`, `sources/normalize.py` — the flattened harness.

## Definition of Done

- A POSIX-compatible `full_test.sh` exists at the completed application root.
- `sh full_test.sh` runs the complete, unfiltered conformance command above.
- The script prints the suite output and exits zero only when the passed count is nonzero and the
  failed, errored, and skipped counts are all zero.
- Program satisfies the stdin→stdout contract.
- Passing count is 100%
- The llm is to write the library for this work - not reuse a public markdown library.  The exercise is to write the code as those libraries will not meet 100% acceptance criteria.  

The final build story depends on every implementation story, adds no new parser behavior, runs
`sh full_test.sh`, and preserves the command, exit code, suite summary, standard output, and
standard error as evidence.

## Fixture Provenance

The CommonMark conformance assets are copied from:

- https://github.com/commonmark/commonmark-spec
- https://spec.commonmark.org/0.31.2/

The copied assets retain the upstream `LICENSE`.
