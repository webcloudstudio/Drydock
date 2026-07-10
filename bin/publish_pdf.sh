#!/usr/bin/env bash
# Convert a Markdown document to themed HTML and PDF via drydock publish.
# Usage: bin/publish_pdf.sh <document.md> [theme]
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: bin/publish_pdf.sh <document.md> [theme]" >&2
  exit 2
fi

md="$1"
theme="${2:-sail}"
base="${md%.md}"

drydock publish "$md" \
  --output "${base}.html" \
  --theme "$theme" \
  --pdf \
  --pdf-output "${base}.pdf"
