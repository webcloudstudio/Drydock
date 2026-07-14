"""Target-local source exclusion ledger for prompt assembly."""

from __future__ import annotations

import re
from pathlib import Path

_FILENAME = "EXCLUDE_FILES.md"
_HEADER = """# Exclude Files

Exact filenames listed here are excluded from `blueprint/sources/` prompt injection for `drydock analyze` and `drydock plan`.

## Excluded files
"""

_SUGGESTED_SOURCE_NAMES = (
    "BUILD_PLAN.md",
    "BUILD_PLAN_INTENT.md",
    "CHANGE_LOG.md",
)
_SUGGESTED_SOURCE_PATTERNS = (
    re.compile(r".*MANIFEST.*\.md\Z", re.IGNORECASE),
    re.compile(r".*CONTRACT.*\.md\Z", re.IGNORECASE),
)


def exclude_files_path(target_dir: Path) -> Path:
    return target_dir / _FILENAME


def ensure_exclude_file(target_dir: Path) -> str:
    path = exclude_files_path(target_dir)
    if not path.is_file():
        path.write_text(_HEADER, encoding="utf-8", newline="\n")
    return path.read_text(encoding="utf-8")


def load_excluded_filenames(target_dir: Path) -> frozenset[str]:
    path = exclude_files_path(target_dir)
    if not path.is_file():
        return frozenset()
    names: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("- "):
            name = line[2:].strip()
            if name:
                names.append(name)
    return frozenset(names)


def append_suggested_exclusions(target_dir: Path, source_files: list[Path]) -> Path:
    path = exclude_files_path(target_dir)
    existing = set(load_excluded_filenames(target_dir))
    source_names = {p.name for p in source_files}
    to_add = []
    for name in _SUGGESTED_SOURCE_NAMES:
        if name not in existing and name in source_names:
            to_add.append(name)
    for name in sorted(source_names):
        if name in existing:
            continue
        if any(pattern.fullmatch(name) for pattern in _SUGGESTED_SOURCE_PATTERNS):
            to_add.append(name)
    if not to_add:
        ensure_exclude_file(target_dir)
        return path
    text = ensure_exclude_file(target_dir).rstrip() + "\n"
    addition = "".join(f"- {name}\n" for name in to_add)
    path.write_text(text + addition, encoding="utf-8", newline="\n")
    return path
