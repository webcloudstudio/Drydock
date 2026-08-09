# Drydock Example — CommonMark Parser

A Drydock UAT kit. Drydock reads the CommonMark 0.31.2 specification and its conformance suite,
then designs and builds a CommonMark parser unattended, from `init` to a scored `build`.
Correctness is the number of spec examples the parser converts exactly.

## Prerequisites

Python 3. The conformance suite is pure Python and needs no installation.

## Running

```bash
drydock uat CommonMark
```

The run lands in `runs/<run-id>/`; open its `README.md` for the verdict and `index.html` for the
linked evidence.

## Kit contents

| Path | Role |
|---|---|
| `uat.json` | Source bundle, updates, and the scoring command |
| `sources/INSTRUCTIONS.md` | The build brief: objective, interface contract, definition of done |
| `sources/spec.txt` | The CommonMark 0.31.2 specification, examples included — the primary input |
| `sources/spec_tests.py` | Conformance runner; extracts every example and compares output |
| `sources/cmark.py`, `sources/normalize.py` | Harness support: subprocess driver and HTML canonicalizer |
| `LICENSE` | Upstream license covering the specification and suite |

Every non-Markdown source is staged verbatim into the build directory's `sources/` for the build to
execute. The Markdown becomes Blueprint input.

`spec.txt` carries significant trailing whitespace: two trailing spaces are a hard line break in
Markdown, and several examples test exactly that. Never run a whitespace-trimming formatter over
this kit.

## What the build must produce

A filter: read Markdown from stdin, write HTML to stdout. No arguments, no configuration, no side
effects. Any language satisfying that contract works; Python 3 is the default. `full_test.sh` at
the application root runs the complete conformance suite and returns its exit code unchanged.

## Reading the evidence

`runs/<run-id>/README.md` states the verdict. When a build fails, the authoritative diagnosis is
`runs/<run-id>/workspace/targets/commonmark/evidence/<block-id>.md`, which records every acceptance
criterion, its exit code, and its captured output.
