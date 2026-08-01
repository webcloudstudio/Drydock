#!/usr/bin/env python3
"""Print a title-only report of outstanding Drydock notes.

The script takes no arguments. Completed ``*_done.md`` sections and implemented
items with no specification work are excluded from the report.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import archive_notes


@dataclass(frozen=True)
class Item:
    title: str
    spec: str
    impl: str
    category: str


def _category(source_name: str) -> str:
    return Path(source_name).stem.removeprefix("notes_")


def _is_outstanding(spec: str, impl: str) -> bool:
    if "<" in spec or "<" in impl:
        return False
    if spec == "applied" and impl == "implemented":
        return False
    if spec == "na" and impl in {"implemented", "na", "n/a"}:
        return False
    return True


def _active_items() -> list[Item]:
    items: list[Item] = []
    active_files = sorted(
        path
        for path in archive_notes.NOTES_DIR.glob("notes_*.md")
        if path != archive_notes.DOCS_FILE and not path.stem.endswith("_done")
    )
    for path in active_files:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        headings = archive_notes._heading_map(lines)
        for section in archive_notes._sections(lines):
            if not _is_outstanding(section.spec, section.impl):
                continue
            _, title = headings[section.start]
            items.append(
                Item(
                    title=title,
                    spec=section.spec,
                    impl=section.impl,
                    category=_category(path.name),
                )
            )
    return items


def _documentation_items() -> list[Item]:
    if not archive_notes.DOCS_FILE.exists():
        return []
    lines = archive_notes.DOCS_FILE.read_text(encoding="utf-8").splitlines(keepends=True)
    headings = archive_notes._heading_map(lines)
    source_at_line: dict[int, str] = {}
    current_source: str | None = None
    for index in range(len(lines)):
        if index in headings and headings[index][0] == 2:
            match = archive_notes.SOURCE_HEADING_RE.match(lines[index].rstrip("\n"))
            current_source = match.group("source") if match else None
        if current_source is not None:
            source_at_line[index] = current_source

    items: list[Item] = []
    for section in archive_notes._sections(lines):
        if not _is_outstanding(section.spec, section.impl):
            continue
        source_name = source_at_line.get(section.start)
        if source_name is None:
            raise ValueError(
                f"documentation section at line {section.start + 1} has no source category"
            )
        _, title = headings[section.start]
        items.append(
            Item(
                title=title,
                spec=section.spec,
                impl=section.impl,
                category=_category(source_name),
            )
        )
    return items


def collect_items() -> list[Item]:
    return sorted(
        [*_active_items(), *_documentation_items()],
        key=lambda item: (item.category.casefold(), item.title.casefold()),
    )


def _escape(value: str) -> str:
    return value.replace("|", "\\|")


def render(items: list[Item]) -> str:
    categories = Counter(item.category for item in items)
    lines = [
        "# Notes Summary",
        "",
        f"Outstanding items: {len(items)}",
        "",
        "Category counts: "
        + ", ".join(f"{category}={count}" for category, count in sorted(categories.items())),
        "",
        "| Title | Status | Category |",
        "|---|---|---|",
    ]
    lines.extend(
        f"| {_escape(item.title)} | spec:{item.spec} · impl:{item.impl} | {item.category} |"
        for item in items
    )
    return "\n".join(lines)


def main() -> None:
    print(render(collect_items()))


if __name__ == "__main__":
    main()
