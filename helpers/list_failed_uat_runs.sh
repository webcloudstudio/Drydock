#!/usr/bin/env bash
# Read-only companion to delete_failed_uat_runs.sh.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 - "$script_dir/../uat" "$@" <<'PY'
import argparse
import json
import sys
from pathlib import Path

parser = argparse.ArgumentParser(
    description='List runs whose result.json status is "failed" without changing files.',
)
parser.add_argument('--uat-root', type=Path, default=Path(sys.argv[1]),
                    help='kit parent directory (default: repository uat/)')
args = parser.parse_args(sys.argv[2:])
root = args.uat_root.resolve()
if not root.is_dir():
    parser.exit(1, f'Error: UAT root is not a directory: {root}\n')

selected = 0
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
                    print(f'SKIP {run}: symlinked result.json', file=sys.stderr)
                    continue
                payload = json.loads(receipt.read_text(encoding='utf-8'))
            except (OSError, ValueError) as exc:
                print(f'SKIP {run}: unreadable result.json ({exc})', file=sys.stderr)
                continue
            if isinstance(payload, dict) and payload.get('status') == 'failed':
                print(run)
                selected += 1
except OSError as exc:
    parser.exit(1, f'Error: {exc}\n')

print(f'{selected} failed run(s).', file=sys.stderr)
PY
