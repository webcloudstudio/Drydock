# Command-Line Application

**Version:** 20260920 V1
**Layer:** platform
**Category:** Technologies
**Foundation:** cli
**Description:** Command-line application structure: entry point, argument parsing, exit codes, cross-platform launchers, and testing without spawning a process.

Technology reference. This file does not change between projects.

Prerequisites: `stack/common.md`, `stack/python.md`

---

## Foundation Contract

The published shape of this foundation. Drydock synthesizes the story that builds it and every
acceptance criterion writes against these names. Carried verbatim into `cli_compact.md`.

- package: cli
- entry: main(argv: list[str] | None = None) -> int
- fixture: cli_runner
- fixture_source: conftest.py

```python
# cli/__init__.py
def main(argv: list[str] | None = None) -> int:
    ...

# conftest.py
import pytest
from cli import main

@pytest.fixture
def cli_runner():
    def run(*args: str) -> tuple[int, str, str]:
        """Return (exit_code, stdout, stderr) without spawning a process."""
        import contextlib, io
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()
    return run
```

A criterion calls `cli_runner("status", "--json")` and asserts on the returned tuple. It does not
call `subprocess.run`, which measures the installed console script and the shell rather than the
code the story wrote.

---

## 1. Directory Layout

**Rule**: Command code lives in `cli/`. The root holds only packaging and infrastructure files.

```
project/
  pyproject.toml            # [project.scripts] declares the console script
  cli/
    __init__.py             # main() — the single entry point
    commands.py             # one function per command; no argument parsing
    parser.py               # argparse construction; no behavior
  bin/
    run.sh                  # bash launcher
    run.ps1                 # PowerShell launcher
  tests/
```

**Why**: Parsing, behavior, and launching are three contracts. Collapsing them produces a command
that cannot be tested without a shell.

---

## 2. Entry Point and Exit Codes

**Rule**: `main(argv=None) -> int` parses, dispatches, and returns an exit code. It never calls
`sys.exit` and never raises for an expected failure. The console script is the only caller that
translates the return value into a process exit.

```python
# cli/__init__.py
import sys
from cli.parser import build_parser
from cli import commands

def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return commands.dispatch(args)
    except OperationalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
```

```toml
# pyproject.toml
[project.scripts]
mytool = "cli:main"
```

**Exit codes**: `0` success, `1` operational failure, `2` usage error. `argparse` already returns
`2` for a usage error; do not override it.

**Why**: A `main` that returns rather than exits is callable from a test in-process. A `main` that
calls `sys.exit` forces every criterion to spawn a subprocess and measure the shell.

---

## 3. Parsing Is Separate From Behavior

**Rule**: `parser.py` builds the `argparse` tree and returns it. `commands.py` holds one function
per command taking plain arguments, not a `Namespace`. Neither imports the other.

```python
# cli/parser.py
import argparse

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mytool")
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="Report current state")
    status.add_argument("--json", action="store_true")
    return parser
```

```python
# cli/commands.py
def status(*, as_json: bool) -> int:
    ...

def dispatch(args) -> int:
    if args.command == "status":
        return status(as_json=args.json)
    return 2
```

**Why**: Behavior tested through a `Namespace` is behavior tested through the parser. Separating
them lets a criterion call `status(as_json=True)` directly.

---

## 4. Cross-Platform Launchers

**Rule**: Ship both launchers. They locate the environment and invoke the package entry point;
they contain no business logic. A launcher that makes a decision is a second implementation of the
command.

```bash
#!/usr/bin/env bash
# bin/run.sh — locate the environment and hand off. No business logic.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -d "$ROOT/.venv" ]; then
    source "$ROOT/.venv/bin/activate"
fi
exec python -m cli "$@"
```

```powershell
# bin/run.ps1 — locate the environment and hand off. No business logic.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Activate = Join-Path $Root ".venv\Scripts\Activate.ps1"
if (Test-Path $Activate) { & $Activate }
python -m cli @args
exit $LASTEXITCODE
```

```python
# cli/__main__.py — makes `python -m cli` work identically on both platforms
import sys
from cli import main

sys.exit(main())
```

**Why**: `python -m cli` is the one invocation both launchers share, so the two scripts cannot
drift in behavior — only in how they find the interpreter. `exit $LASTEXITCODE` is required in
PowerShell; without it the exit code is discarded and a failing command reports success.

---

## 5. Output and Streams

**Rule**: Results go to stdout, diagnostics to stderr. A `--json` mode prints one JSON document to
stdout and nothing else. Never interleave progress text into a machine-readable stream.

**Why**: A caller piping stdout to `jq` receives the progress lines too, and the command becomes
unusable in a pipeline.

---

## 6. Testing Without a Process

**Rule**: Test through `main(["status", "--json"])` or the `cli_runner` fixture. Reserve
`subprocess.run` for one packaging test asserting the installed console script exists and runs.

```python
def test_status_reports_json(cli_runner):
    code, out, err = cli_runner("status", "--json")
    assert code == 0
    assert json.loads(out)["state"] == "ready"
    assert err == ""
```

**Why**: In-process tests are fast, debuggable, and measure the code. Subprocess tests measure the
installed environment, which is a different and much smaller question.

---

## Checklist

- [ ] `cli/` package; `main(argv=None) -> int` that returns rather than exits
- [ ] `[project.scripts]` declares the console script
- [ ] `cli/__main__.py` so `python -m cli` works
- [ ] Both `bin/run.sh` and `bin/run.ps1`, neither holding logic; `.ps1` ends with `exit $LASTEXITCODE`
- [ ] Parsing in `parser.py`, behavior in `commands.py`, no import between them
- [ ] Exit codes `0` / `1` / `2` used consistently
- [ ] Results on stdout, diagnostics on stderr, `--json` emits nothing else
- [ ] Criteria use `cli_runner`; at most one subprocess test for packaging
