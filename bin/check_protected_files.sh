#!/usr/bin/env bash
set -euo pipefail

protected_files=(
  "DRYDOCK_DEVELOPMENT.md"
  "docs/Drydock_Specification.md"
  "docs/drydock-anchor.svg"
  "docs/drydock-compass.svg"
  "docs/drydock-helm.svg"
  "docs/drydock-lighthouse.svg"
)

failed=0
for path in "${protected_files[@]}"; do
  if [[ ! -f "$path" ]]; then
    printf 'protected file missing from working tree: %s\n' "$path" >&2
    failed=1
  fi
  if ! git cat-file -e ":$path" 2>/dev/null; then
    printf 'protected file missing from staged index: %s\n' "$path" >&2
    failed=1
  fi
done

if [[ "$failed" -ne 0 ]]; then
  printf '\nCommit blocked to prevent accidental deletion of canonical Drydock files.\n' >&2
  printf 'Restore and stage the files, or intentionally bypass with SKIP=protect-canonical-files.\n' >&2
  exit 1
fi
