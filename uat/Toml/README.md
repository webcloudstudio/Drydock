# Drydock Example — TOML 1.0.0 Parser

A Drydock UAT kit. Drydock reads the TOML 1.0.0 specification and a language-neutral conformance
harness, then designs and builds a complete TOML parser in Go, unattended, from `init` to a scored
`build`. Correctness is measured by the upstream `toml-test` suite: 210 valid and 499 invalid cases.

The parser is written from the specification. Every third-party TOML module is forbidden, and
`go.mod` declares no dependencies.

## Prerequisites

A Go toolchain of at least 1.22. The Go packaged by apt on Debian and Ubuntu is usually older and
will fail:

```bash
curl -sL https://go.dev/dl/go1.24.6.linux-amd64.tar.gz -o /tmp/go.tgz
sudo rm -rf /usr/local/go && sudo tar -C /usr/local -xzf /tmp/go.tgz
export PATH=/usr/local/go/bin:$PATH
```

Install the conformance harness once. It needs network access, and only this once:

```bash
sh sources/setup_harness.sh          # installs toml-test to $HOME/.local/bin
```

Confirm `toml-test` is reachable on `PATH`, or export `TOML_TEST=/path/to/toml-test`. The build
cannot be scored without it.

## Running

```bash
drydock uat Toml
```

Roughly thirty minutes and eighteen LLM calls. The run lands in `runs/<run-id>/`; open its
`README.md` for the verdict and `index.html` for the linked evidence.

## Kit contents

| Path | Role |
|---|---|
| `uat.json` | Source bundle, updates, and the scoring command |
| `TECHNOLOGY_STACK.md` | Fixes Go as the implementation stack, so `analyze` does not choose |
| `sources/INSTRUCTIONS.md` | The build brief: objective, interface contract, definition of done |
| `sources/toml-v1.0.0.md` | The TOML 1.0.0 specification — the primary input |
| `sources/run_conformance.sh` | Scoring entry point; runs `toml-test` against the built decoder |
| `sources/setup_harness.sh` | One-time harness installation |
| `LICENSE` | Upstream license covering the specification text |

Every non-Markdown source is staged verbatim into the build directory's `sources/` for the build to
execute. The Markdown becomes Blueprint input.

## What the build must produce

A filter: read TOML from stdin, write tagged JSON to stdout, exit `0`; on invalid TOML write a
diagnostic to stderr and exit non-zero. `full_test.sh` at the application root builds the decoder
and runs the full conformance suite, unfiltered, returning the harness exit code unchanged.

## Reading the evidence

`runs/<run-id>/README.md` states the verdict. When a build fails, the authoritative diagnosis is
`runs/<run-id>/workspace/targets/toml/evidence/<block-id>.md`, which records every acceptance
criterion, its exit code, and its captured output.
