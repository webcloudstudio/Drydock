#!/usr/bin/env python3
"""Archive completed and documentation-ready sections from Drydock notes.

The script takes no arguments and operates on ``notes_*.md`` files beside it.

Transitions:

* spec:approved + impl:implemented|na|n/a -> notes_docs.md
* spec:applied + impl:implemented          -> notes_<subject>_done.md

Sections already in notes_docs.md move to their source-specific done file after
their status is changed to spec:applied + impl:implemented.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

NOTES_DIR = Path(__file__).resolve().parent
DOCS_FILE = NOTES_DIR / "notes_docs.md"

HEADING_RE = re.compile(r"^(#{2,6})[ \t]+(.+?)[ \t]*$")
STATUS_RE = re.compile(
    r"`[^`]+`\s*·\s*`spec:(?P<spec>[^`]+)`\s*·\s*`impl:(?P<impl>[^`]+)`",
    re.IGNORECASE,
)
SOURCE_HEADING_RE = re.compile(r"^##[ \t]+(?P<source>notes_.+\.md)[ \t]*$")


@dataclass(frozen=True)
class Section:
    start: int
    end: int
    level: int
    spec: str
    impl: str


def _heading_map(lines: list[str]) -> dict[int, tuple[int, str]]:
    headings: dict[int, tuple[int, str]] = {}
    fence: str | None = None
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        marker = stripped[:3]
        if marker in {"```", "~~~"}:
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            continue
        if fence is not None:
            continue
        match = HEADING_RE.match(line.rstrip("\n"))
        if match:
            headings[index] = (len(match.group(1)), match.group(2))
    return headings


def _sections(lines: list[str]) -> list[Section]:
    headings = _heading_map(lines)
    heading_indexes = sorted(headings)
    sections: list[Section] = []
    for position, start in enumerate(heading_indexes):
        level, _ = headings[start]
        status_match = None
        for line in lines[start + 1 : start + 5]:
            if line.strip():
                status_match = STATUS_RE.search(line)
                break
        if status_match is None:
            continue

        end = len(lines)
        for candidate in heading_indexes[position + 1 :]:
            candidate_level, _ = headings[candidate]
            if candidate_level <= level:
                end = candidate
                break
        sections.append(
            Section(
                start=start,
                end=end,
                level=level,
                spec=status_match.group("spec").strip().lower(),
                impl=status_match.group("impl").strip().lower(),
            )
        )
    return sections


def _route(section: Section) -> str | None:
    if section.spec == "applied" and section.impl == "implemented":
        return "done"
    if section.spec == "approved" and section.impl in {"implemented", "na", "n/a"}:
        return "docs"
    return None


def _promote_or_demote(text: str, delta: int) -> str:
    lines = text.splitlines(keepends=True)
    headings = _heading_map(lines)
    for index, (level, title) in headings.items():
        new_level = level + delta
        if not 1 <= new_level <= 6:
            raise ValueError(f"cannot change heading level {level} by {delta}: {title}")
        newline = "\n" if lines[index].endswith("\n") else ""
        lines[index] = f"{'#' * new_level} {title}{newline}"
    return "".join(lines)


def _remove_sections(lines: list[str], sections: list[Section]) -> list[str]:
    for section in sorted(sections, key=lambda item: item.start, reverse=True):
        del lines[section.start : section.end]
    return _remove_empty_group_headings(lines)


def _remove_empty_group_headings(lines: list[str]) -> list[str]:
    while True:
        headings = _heading_map(lines)
        indexes = sorted(headings)
        removed = False
        for position, start in enumerate(indexes):
            level, _ = headings[start]
            end = len(lines)
            for candidate in indexes[position + 1 :]:
                candidate_level, _ = headings[candidate]
                if candidate_level <= level:
                    end = candidate
                    break
            body = lines[start + 1 : end]
            if body and any(line.strip() for line in body):
                continue
            delete_end = start + 1
            while delete_end < len(lines) and not lines[delete_end].strip():
                delete_end += 1
            del lines[start:delete_end]
            removed = True
            break
        if not removed:
            break
    return lines


def _normalize_spacing(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text.rstrip())
    return f"{text}\n" if text else ""


def _update_pending_counts(text: str) -> str:
    remaining = _sections(text.splitlines(keepends=True))
    pending_spec = sum(section.spec == "approved" for section in remaining)
    pending_impl = sum(section.impl == "unimplemented" for section in remaining)
    text = re.sub(
        r"(?m)^(\| Pending spec \| )[^|]*( \|)$",
        rf"\g<1>{pending_spec} approved items\g<2>",
        text,
    )
    text = re.sub(
        r"(?m)^(\| Pending impl \| )[^|]*( \|)$",
        rf"\g<1>{pending_impl} unimplemented sections\g<2>",
        text,
    )
    return text


def _done_path(source_name: str) -> Path:
    return NOTES_DIR / f"{Path(source_name).stem}_done.md"


def _append_done(source_name: str, blocks: list[str]) -> None:
    if not blocks:
        return
    path = _done_path(source_name)
    subject = Path(source_name).stem.removeprefix("notes_")
    if path.exists():
        text = path.read_text(encoding="utf-8").rstrip()
    else:
        text = f"# DONE: {subject}"
    for block in blocks:
        normalized = block.strip()
        if normalized and normalized not in text:
            text = f"{text}\n\n{normalized}"
    path.write_text(f"{text.rstrip()}\n", encoding="utf-8")


def _docs_groups(lines: list[str]) -> dict[str, tuple[int, int]]:
    headings = _heading_map(lines)
    indexes = sorted(headings)
    groups: dict[str, tuple[int, int]] = {}
    for position, start in enumerate(indexes):
        match = SOURCE_HEADING_RE.match(lines[start].rstrip("\n"))
        if match is None:
            continue
        end = len(lines)
        for candidate in indexes[position + 1 :]:
            if headings[candidate][0] <= 2:
                end = candidate
                break
        groups[match.group("source")] = (start, end)
    return groups


def _append_docs(source_name: str, blocks: list[str]) -> None:
    if not blocks:
        return
    if DOCS_FILE.exists():
        lines = DOCS_FILE.read_text(encoding="utf-8").splitlines(keepends=True)
    else:
        lines = [
            "# DOCUMENTATION NOTES\n",
            "\n",
            "Specification-approved sections awaiting application to the canonical specification.\n",
        ]

    groups = _docs_groups(lines)
    additions = [f"\n{_promote_or_demote(block.strip(), 1)}\n" for block in blocks]
    if source_name in groups:
        _, end = groups[source_name]
        lines[end:end] = additions
    else:
        if lines and lines[-1].strip():
            lines.append("\n")
        lines.append(f"## {source_name}\n")
        lines.extend(additions)
    DOCS_FILE.write_text(_normalize_spacing("".join(lines)), encoding="utf-8")


def _archive_active_file(path: Path) -> None:
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    routed = [(section, _route(section)) for section in _sections(lines)]
    selected = [(section, route) for section, route in routed if route is not None]
    if not selected:
        return

    docs_blocks = [
        "".join(lines[item.start : item.end]) for item, route in selected if route == "docs"
    ]
    done_blocks = [
        "".join(lines[item.start : item.end]) for item, route in selected if route == "done"
    ]
    retained = _remove_sections(lines, [item for item, _ in selected])
    updated = _update_pending_counts(_normalize_spacing("".join(retained)))

    _append_docs(path.name, docs_blocks)
    _append_done(path.name, done_blocks)
    path.write_text(updated, encoding="utf-8")


def _archive_applied_docs() -> None:
    if not DOCS_FILE.exists():
        return
    lines = DOCS_FILE.read_text(encoding="utf-8").splitlines(keepends=True)
    headings = _heading_map(lines)
    source_at_line: dict[int, str] = {}
    current_source: str | None = None
    for index in range(len(lines)):
        if index in headings and headings[index][0] == 2:
            match = SOURCE_HEADING_RE.match(lines[index].rstrip("\n"))
            current_source = match.group("source") if match else None
        if current_source is not None:
            source_at_line[index] = current_source

    selected = [section for section in _sections(lines) if _route(section) == "done"]
    if not selected:
        return
    by_source: dict[str, list[str]] = {}
    for section in selected:
        source = source_at_line.get(section.start)
        if source is None:
            raise ValueError(
                f"applied documentation section at line {section.start + 1} has no source"
            )
        block = "".join(lines[section.start : section.end])
        by_source.setdefault(source, []).append(_promote_or_demote(block.strip(), -1))
    for source, blocks in by_source.items():
        _append_done(source, blocks)
    retained = _remove_sections(lines, selected)
    DOCS_FILE.write_text(_normalize_spacing("".join(retained)), encoding="utf-8")


def main() -> None:
    _archive_applied_docs()
    active_files = sorted(
        path
        for path in NOTES_DIR.glob("notes_*.md")
        if path != DOCS_FILE and not path.stem.endswith("_done")
    )
    for path in active_files:
        _archive_active_file(path)


if __name__ == "__main__":
    main()
