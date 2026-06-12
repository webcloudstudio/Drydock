#!/usr/bin/env bash
set -euo pipefail

specification="docs/Drydock_Specification.md"
root="$(git rev-parse --show-toplevel)"
git_dir="$(git rev-parse --git-dir)"
backup_dir="$git_dir/canonical-backups"
backup="$backup_dir/Drydock_Specification.md"

cd "$root"
mkdir -p "$backup_dir"

restore_specification() {
  if [[ -f "$backup" ]]; then
    cp "$backup" "$specification"
    printf 'restored canonical specification from pre-commit snapshot: %s\n' "$specification" >&2
    return 0
  fi

  if git cat-file -e ":$specification" 2>/dev/null; then
    git show ":$specification" > "$specification"
    printf 'restored canonical specification from staged index: %s\n' "$specification" >&2
    return 0
  fi

  return 1
}

if [[ ! -f "$specification" ]]; then
  restore_specification || {
    printf 'canonical specification is missing and no recovery source exists: %s\n' \
      "$specification" >&2
  }
  printf 'commit blocked because the canonical specification was missing.\n' >&2
  exit 1
fi

# Preserve the latest working copy before any commit tooling can touch the worktree.
cp "$specification" "$backup"

if ! git cat-file -e ":$specification" 2>/dev/null; then
  printf 'commit blocked: canonical specification is missing from the staged index: %s\n' \
    "$specification" >&2
  exit 1
fi

if ! git diff --quiet -- "$specification"; then
  printf 'commit blocked: canonical specification has unstaged edits: %s\n' \
    "$specification" >&2
  printf 'Stage its approved edits before committing other work. This prevents pre-commit from\n' >&2
  printf 'stashing and losing the working copy on this filesystem.\n' >&2
  exit 1
fi

if [[ "$#" -eq 0 ]]; then
  printf 'usage: %s <pre-commit command> [arguments...]\n' "$0" >&2
  exit 2
fi

set +e
"$@"
status=$?
set -e

if [[ ! -f "$specification" ]]; then
  restore_specification || true
  printf 'commit blocked because commit tooling removed the canonical specification.\n' >&2
  exit 1
fi

exit "$status"
