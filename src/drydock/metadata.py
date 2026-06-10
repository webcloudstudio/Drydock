"""METADATA.md field parser."""

from __future__ import annotations

import re
from pathlib import Path


def parse_metadata(path: Path) -> dict[str, str]:
    """
    Parse a METADATA.md file and return a dict of field -> value.

    Handles both 'key: value' frontmatter-style lines and the
    '## Agent Instructions' section boundary (stops there).
    """
    fields: dict[str, str] = {}
    if not path.exists():
        return fields

    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        # Stop at section headers — metadata fields are above them
        if line.startswith("## "):
            break
        m = re.match(r"^([a-z_]+):\s*(.*)$", line.rstrip())
        if m:
            fields[m.group(1)] = m.group(2).strip()
    return fields


def get_field(metadata: dict[str, str], key: str) -> str | None:
    """Return stripped value or None."""
    val = metadata.get(key, "").strip()
    return val if val else None
