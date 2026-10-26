#!/usr/bin/env bash
# Deprecated. Use: drydock run builder <Target> --model <model> [--infile F]... [--indir D]...
# This shim forwards a <target> <model> invocation; import scripts are retired in favor of
# repeated --infile and --indir arguments (see Import_Marina.sh).
set -Eeuo pipefail

if [ "$#" -ne 2 ]; then
  echo "drydock_runner.sh is deprecated. Use:" >&2
  echo "  drydock run builder <Target> --model <model> [--infile [<format>=]<file>]... [--indir [<format>=]<dir>]..." >&2
  if [ "$#" -eq 3 ]; then
    echo "Import scripts are retired; run the import script itself (see Import_Marina.sh)." >&2
  fi
  exit 2
fi

echo "drydock_runner.sh is deprecated; running: drydock run builder $1 --model $2" >&2
exec drydock run builder "$1" --model "$2"
