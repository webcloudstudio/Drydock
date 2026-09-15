#!/usr/bin/env bash
# Build or repair unfinished work, including Targets stalled before the first build.
set -Eeuo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: build_loop.sh <Target> [build/diagnose provider and model flags]" >&2
  exit 2
fi
target=$1
shift
max=${DRYDOCK_RUNNER_MAX_BUILDS:-5}
case "$max" in
  ''|*[!0-9]*|0) echo "DRYDOCK_RUNNER_MAX_BUILDS must be positive." >&2; exit 2 ;;
esac

for ((attempt=1; attempt<=max; attempt++)); do
  if drydock status "$target" --ready; then
    echo "Running build attempt $attempt/$max"
    if drydock build "$target" "$@"; then
      continue
    fi
  elif drydock status "$target" --check; then
    exit 0
  fi

  echo "Repairing unfinished work for $target"
  if ! drydock diagnose "$target" --apply "$@"; then
    echo "Diagnosis did not restore progress; see the repair outcome above." >&2
    exit 1
  fi
  if drydock status "$target" --check; then
    exit 0
  fi
  if ! drydock status "$target" --ready; then
    echo "Target remains stalled after diagnosis; stopping recovery." >&2
    exit 1
  fi
done

if drydock status "$target" --check; then
  exit 0
fi
echo "Reached DRYDOCK_RUNNER_MAX_BUILDS=$max; unfinished work remains." >&2
exit 1
