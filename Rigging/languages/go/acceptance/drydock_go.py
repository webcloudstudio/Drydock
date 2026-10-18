"""Run native Go tests from a Blueprint's Python AC container.

Copied beside each criterion by Drydock. No Drydock installation is needed in the Target.
The outer acceptance process owns the timeout and kills the whole process group.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class GoResult:
    passed: bool
    status: str
    return_code: int | None
    stdout: str
    stderr: str
    tests: dict[str, str]


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
        return GoResult(False, 'unavailable', None, '', str(exc), {})
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
    return GoResult(status == 'pass', status, process.returncode,
                    process.stdout, process.stderr, tests)
