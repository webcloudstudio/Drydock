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

Run the conformance suite from the repository root:

```bash
python3 test/spec_tests.py --spec spec.txt --program "python3 mycommonmark.py"
```

Mechanics: `spec_tests.py` extracts every fenced `example` block from `spec.txt`
(Markdown input + expected HTML), pipes each input through your program via
stdin, normalizes both actual and expected HTML (`test/normalize.py` parses and
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

- `spec.txt` — the specification AND the test corpus. Primary input. Required.
- `test/spec_tests.py`, `test/cmark.py`, `test/normalize.py` — the harness.
  Required to run/score; useful to read so the LLM understands invocation and
  the normalization applied before comparison.

## Definition of Done

- Program satisfies the stdin→stdout contract.
- `python3 test/spec_tests.py --spec spec.txt --program "..."` runs cleanly
  (0 errored).
- Passing count is at the target threshold (set your bar, e.g. 100% = 655/655).
