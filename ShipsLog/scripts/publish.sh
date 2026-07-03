#!/usr/bin/env bash
# publish.sh — validate a post file and rebuild the local posts index.
#
# Usage: scripts/publish.sh blog/posts/<file>.md [--force]
#   --force  continue even if the disclosure lint flags issues (use sparingly)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$HERE/blog.config.sh"

POST="${1:-}"
FORCE="${2:-}"
if [[ -z "$POST" || ! -f "$POST" ]]; then
  echo "publish: pass a post file. e.g. scripts/publish.sh blog/posts/2026-06-10-foo.md" >&2
  exit 1
fi

# 1. Disclosure gate.
if ! python3 "$HERE/scripts/check_disclosure.py" "$POST"; then
  if [[ "$FORCE" != "--force" ]]; then
    echo "publish: blocked by disclosure lint. Fix the post or re-run with --force." >&2
    exit 2
  fi
  echo "publish: lint flagged issues — overridden by --force." >&2
fi

# 2. Rebuild the local post preview and index.
python3 "$HERE/scripts/render.py" "$POST"

echo "publish: done."
