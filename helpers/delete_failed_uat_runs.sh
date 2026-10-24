#!/usr/bin/env bash
# Operator-only cleanup. Preview by default; no Drydock commands or Git operations.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 - "$script_dir/../uat" "$@" <<'PY'
import argparse
import json
import shutil
import sys
from pathlib import Path

parser = argparse.ArgumentParser(
    description='Preview deletion of runs whose result.json status is "failed".',
    epilog='Stop active UAT runs before deleting. Kit indexes, checksums, and Git history '
           'are not updated; published evidence must be reconciled by the operator.',
)
parser.add_argument('--uat-root', type=Path, default=Path(sys.argv[1]),
                    help='kit parent directory (default: repository uat/)')
parser.add_argument('--delete', action='store_true', help='delete the listed failed runs')
args = parser.parse_args(sys.argv[2:])
root = args.uat_root.resolve()
if not root.is_dir():
    parser.exit(1, f'Error: UAT root is not a directory: {root}\n')

selected = 0
errors = 0
try:
    for kit in sorted(root.iterdir()):
        if kit.is_symlink() or not kit.is_dir():
            continue
        runs = kit / 'runs'
        if runs.is_symlink() or not runs.is_dir():
            continue
        for run in sorted(runs.iterdir()):
            if run.is_symlink() or not run.is_dir():
                continue
            receipt = run / 'result.json'
            try:
                if receipt.is_symlink():
                    print(f'SKIP {run}: symlinked result.json')
                    continue
                payload = json.loads(receipt.read_text(encoding='utf-8'))
            except (OSError, ValueError) as exc:
                print(f'SKIP {run}: unreadable result.json ({exc})')
                continue
            status = payload.get('status') if isinstance(payload, dict) else None
            if status != 'failed':
                print(f'KEEP {run}: status={status!r}')
                continue
            if args.delete:
                try:
                    shutil.rmtree(run)
                except OSError as exc:
                    print(f'ERROR {run}: {exc}', file=sys.stderr)
                    errors += 1
                    continue
            print(f'{"DELETED" if args.delete else "WOULD DELETE"} {run}')
            selected += 1
except OSError as exc:
    parser.exit(1, f'Error: {exc}\n')

print(f'{selected} failed run(s) {"deleted" if args.delete else "selected (dry run)"}.')
sys.exit(1 if errors else 0)
PY
