"""Run native Go tests and the built Go executable from a Blueprint's Python AC container.

Copied beside each criterion by Drydock. No Drydock installation is needed in the Target.
The outer acceptance process owns the timeout and kills the whole process group.
"""
from __future__ import annotations

import atexit
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GoResult:
    passed: bool
    status: str
    return_code: int | None
    stdout: str
    stderr: str
    tests: dict[str, str]


def _report(result: GoResult) -> GoResult:
    print("DRYDOCK_NATIVE_RESULT=" + json.dumps({"status": result.status}), file=sys.stderr, flush=True)
    return result


def run_test(package: str, test: str) -> GoResult:
    """Execute one exact test/subtest; absent and skipped tests never pass."""
    if not package.startswith('./') or '..' in package.split('/'):
        raise ValueError('package must be a relative Go package beneath the build root')
    if not re.fullmatch(r'Test[A-Za-z0-9_]+(?:/[A-Za-z0-9_ -]+)*', test):
        raise ValueError('test must name a Test function, optionally followed by named subtests')
    pattern = '/'.join('^' + re.escape(part) + '$' for part in test.split('/'))
    try:
        process = subprocess.run(
            ['go', 'test', '-json', '-count=1', '-run', pattern, package],
            capture_output=True, text=True, encoding='utf-8', errors='replace', check=False,
        )
    except OSError as exc:
        return _report(GoResult(False, 'unavailable', None, '', str(exc), {}))
    tests = {}
    for line in process.stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('Test') and event.get('Action') in ('pass', 'fail', 'skip'):
            tests[event.get('Package', '') + '/' + event['Test']] = event['Action']
    matching = [value for key, value in tests.items() if key.endswith('/' + test)]
    if process.returncode != 0:
        status = 'fail' if 'fail' in tests.values() else 'execution-error'
    elif not matching:
        status = 'not-run'
    elif any(value == 'skip' for value in tests.values()):
        status = 'skip'
    elif all(value == 'pass' for value in matching):
        status = 'pass'
    else:
        status = 'fail'
    return _report(GoResult(status == 'pass', status, process.returncode,
                    process.stdout, process.stderr, tests))


_BUILT: dict[str, str] = {}


def _main_package() -> str:
    """The single ``./cmd/<name>`` main package; a criterion names ``package=`` when there are several."""
    found = sorted({
        path.parent.as_posix()
        for path in Path('cmd').glob('*/*.go')
        if re.search(r'^package main\b', path.read_text(encoding='utf-8', errors='replace'), re.M)
    })
    if len(found) != 1:
        raise ValueError(f'expected one main package under ./cmd, found {found or "none"}; pass package=')
    return './' + found[0]


def _executable(package: str) -> str:
    """Build ``package`` once per criterion process and return the binary's path."""
    if package in _BUILT:
        return _BUILT[package]
    directory = tempfile.mkdtemp(prefix='drydock-go-cli-')
    atexit.register(shutil.rmtree, directory, True)
    binary = str(Path(directory) / Path(package).name)
    try:
        build = subprocess.run(
            ['go', 'build', '-o', binary, package],
            capture_output=True, text=True, encoding='utf-8', errors='replace', check=False,
        )
    except OSError as exc:
        _report(GoResult(False, 'unavailable', None, '', str(exc), {}))
        raise RuntimeError(f'go is unavailable: {exc}') from exc
    if build.returncode != 0:
        _report(GoResult(False, 'execution-error', build.returncode, build.stdout, build.stderr, {}))
        raise RuntimeError(f'go build {package} failed:\n{build.stderr}')
    _BUILT[package] = binary
    return binary


def cli_runner(*args: str, package: str | None = None, input: str | None = None) -> tuple[int, str, str]:
    """Return ``(exit_code, stdout, stderr)`` from the built executable.

    The binary is built with ``go build`` and run directly. ``go run`` is never used: it reports
    every non-zero program exit as 1, so a criterion could not observe exit 2 or 3 at all.
    """
    package = package or _main_package()
    if not package.startswith('./') or '..' in package.split('/'):
        raise ValueError('package must be a relative Go package beneath the build root')
    process = subprocess.run(
        [_executable(package), *args],
        input=input, capture_output=True, text=True, encoding='utf-8', errors='replace', check=False,
    )
    return process.returncode, process.stdout, process.stderr
