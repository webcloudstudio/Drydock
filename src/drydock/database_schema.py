"""``DATABASE.md`` seeding, merging, and compaction for planning.

A planning run authors the persistence declaration once, in its own Stage 2 batch, and freezes
it. Drydock seeds that batch from the Rigging template and every table the imported source
already declared, then merges the seed back into what the model wrote: a model asked to render
an input specification paraphrases it, and a declaration that loses a source table leaves Build
implementing a schema no Blueprint describes.

The merge is append-only by construction.  A table already declared keeps its columns, their order,
and their prose; a column already declared is never retyped or removed.

Table declarations use the form :func:`drydock.database_contract.sqlite_schema_tables` reads — a
top-level ``## `table_name``` heading over a ``| Field | Type | Notes |`` table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from drydock.database_contract import sqlite_schema_tables
from drydock.errors import SpecificationError

#: The persistence declaration Blueprint.
DATABASE_BLOCK = "DATABASE.md"

#: The frozen declaration as later Stage 2 batches read it.
DATABASE_COMPACT_BLOCK = "DATABASE_compact.md"

_COMMENT_RE = re.compile(r"[ \t]*<!--.*?-->[ \t]*\n?", re.DOTALL)

_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_TABLE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_ACCESS_PATTERN_RE = re.compile(r"^###\s+([A-Z][A-Z0-9-]*-\d{3})\s+—", re.MULTILINE)
_EXAMPLE_RE = re.compile(
    r"[ \t]*<!--\s*drydock:example\s*-->.*?<!--\s*drydock:end-example\s*-->[ \t]*\n?",
    re.DOTALL,
)

#: The heading that owns the named repository operations Feature Blueprints cite.
_ACCESS_PATTERNS_HEADING = "Access Patterns"

#: The heading the first declared table follows, before any table exists to follow.
_SCHEMAS_HEADING = "Schemas"

#: Headings that close the declarative body.  A new table is inserted before the first of these,
#: never after, so the typed trailer stays last.
_TERMINAL_HEADINGS = (
    "Programmatic Acceptance",
    "User Acceptance",
    "Guardrails",
    "Open Questions",
)


@dataclass(frozen=True)
class Column:
    """One declared column, carrying the prose that explains it."""

    name: str
    type: str
    notes: str = ""

    def rendered(self) -> str:
        return f"| {self.name} | {self.type} | {self.notes} |"


@dataclass(frozen=True)
class TableSection:
    """One ``## `table_name``` section located within a ``DATABASE.md`` body."""

    name: str
    start: int
    end: int
    columns: tuple[Column, ...]

    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)


def _heading_name(raw: str) -> str:
    return raw.strip().strip("`").strip()


def _sections(text: str) -> list[tuple[str, int, int]]:
    """Every ``##`` heading with the span of the body that follows it."""
    matches = list(_HEADING_RE.finditer(text))
    spans: list[tuple[str, int, int]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        spans.append((_heading_name(match.group(1)), match.start(), end))
    return spans


def _columns(body: str) -> tuple[Column, ...]:
    """Read the first pipe table in ``body`` as column declarations."""
    fields: list[Column] = []
    seen_table = False
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            if seen_table:
                break
            continue
        if not stripped.startswith("|"):
            if seen_table:
                break
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells:
            continue
        header = cells[0].casefold()
        if header in {"field", "column"} or set(cells[0]) <= {"-", ":"}:
            seen_table = True
            continue
        if len(cells) < 2:
            continue
        seen_table = True
        fields.append(
            Column(
                name=cells[0].strip("`"),
                type=cells[1].strip("`"),
                notes=cells[2].strip() if len(cells) > 2 else "",
            )
        )
    return tuple(fields)


def table_sections(text: str) -> tuple[TableSection, ...]:
    """Locate every table declaration in a ``DATABASE.md`` body, in document order."""
    sections: list[TableSection] = []
    for name, start, end in _sections(text):
        if not _TABLE_NAME_RE.fullmatch(name):
            continue
        columns = _columns(text[start:end])
        if not columns:
            continue
        sections.append(TableSection(name, start, end, columns))
    return tuple(sections)


def declared_table_names(text: str) -> tuple[str, ...]:
    """Names of the tables a ``DATABASE.md`` body declares."""
    return tuple(section.name for section in table_sections(text))


def _insertion_point(text: str) -> int:
    """Where a newly declared table belongs: after the last table, before the typed trailer."""
    sections = table_sections(text)
    if sections:
        return sections[-1].end
    spans = _sections(text)
    for name, _start, end in spans:
        if name == _SCHEMAS_HEADING:
            return end
    for name, start, _end in spans:
        if name in _TERMINAL_HEADINGS:
            return start
    return len(text)


def _column_insertion_point(text: str, section: TableSection) -> int:
    """The offset just past the last row of a section's field table."""
    body = text[section.start : section.end]
    last = 0
    seen_table = False
    offset = 0
    for line in body.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("|"):
            seen_table = True
            last = offset + len(line.rstrip("\n"))
        elif seen_table and stripped:
            break
        offset += len(line)
    if not seen_table:
        raise SpecificationError(f"DATABASE.md: table {section.name!r} has no field table")
    return section.start + last


def merge_schema(base: str, addition: str) -> str:
    """Append what ``addition`` declares and ``base`` does not, changing nothing already held.

    A table absent from ``base`` is appended whole, with its prose.  A table present in both keeps
    every column it already declares, in order, and gains only the columns it lacks.  Nothing is
    removed, retyped, or reordered, so a pass that omits or rewrites an existing declaration cannot
    damage it.
    """
    if not addition.strip():
        return base
    incoming = table_sections(addition)
    held = {section.name: section for section in table_sections(base)}
    merged = base

    # Column additions run last-to-first so earlier offsets stay valid as the text grows.
    for section in sorted(
        (item for item in incoming if item.name in held),
        key=lambda item: held[item.name].start,
        reverse=True,
    ):
        current = table_sections(merged)
        target = next((item for item in current if item.name == section.name), None)
        if target is None:  # pragma: no cover - held membership guarantees presence
            continue
        existing = set(target.column_names())
        new_columns = [column for column in section.columns if column.name not in existing]
        if not new_columns:
            continue
        point = _column_insertion_point(merged, target)
        rows = "".join(f"\n{column.rendered()}" for column in new_columns)
        merged = merged[:point] + rows + merged[point:]

    merged = _merge_access_patterns(merged, addition)

    fresh = [section for section in incoming if section.name not in held]
    if fresh:
        point = _insertion_point(merged)
        head = merged[:point].rstrip("\n")
        tail = merged[point:].lstrip("\n")
        bodies = [addition[section.start : section.end].strip("\n") for section in fresh]
        merged = head + "\n\n" + "\n\n".join(bodies) + ("\n\n" + tail if tail else "\n")
    return merged


def _access_pattern_span(text: str) -> tuple[int, int] | None:
    """The span of the ``## Access Patterns`` section, when the body declares one."""
    for name, start, end in _sections(text):
        if name == _ACCESS_PATTERNS_HEADING:
            return start, end
    return None


def _access_pattern_ids(text: str) -> tuple[str, ...]:
    span = _access_pattern_span(text)
    if span is None:
        return ()
    return tuple(match.group(1) for match in _ACCESS_PATTERN_RE.finditer(text[span[0] : span[1]]))


def _merge_access_patterns(base: str, addition: str) -> str:
    """Append operations the addition names and the base does not.

    Features cite operations by id.  An operation already declared keeps its owner, access, and
    typed fields exactly as held; a pass may only introduce ones that do not yet exist.
    """
    incoming = _access_pattern_span(addition)
    if incoming is None:
        return base
    held_ids = set(_access_pattern_ids(base))
    body = addition[incoming[0] : incoming[1]]
    matches = list(_ACCESS_PATTERN_RE.finditer(body))
    fresh: list[str] = []
    for index, match in enumerate(matches):
        if match.group(1) in held_ids:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        fresh.append(body[match.start() : end].strip("\n"))
    if not fresh:
        return base
    span = _access_pattern_span(base)
    if span is None:
        point = _insertion_point(base)
        head = base[:point].rstrip("\n")
        tail = base[point:].lstrip("\n")
        section = f"## {_ACCESS_PATTERNS_HEADING}\n\n" + "\n\n".join(fresh)
        return head + "\n\n" + section + ("\n\n" + tail if tail else "\n")
    head = base[: span[1]].rstrip("\n")
    tail = base[span[1] :].lstrip("\n")
    return head + "\n\n" + "\n\n".join(fresh) + ("\n\n" + tail if tail else "\n")


def compact_declaration(text: str) -> str:
    """The declaration without its authoring guidance: comments and examples removed.

    Every table, access pattern, and field is kept verbatim, so a citation written against the
    compact form matches the declaration Build reads.
    """
    compact = _COMMENT_RE.sub("", _EXAMPLE_RE.sub("", text))
    return re.sub(r"\n{3,}", "\n\n", compact).strip() + "\n"


def merge_seeded_schema(authored: str, seed: str) -> str:
    """Restore omitted source declarations and refuse changes to their column contracts."""
    merged = merge_schema(authored, seed)
    required = sqlite_schema_tables(seed)
    actual = {table.name: table for table in sqlite_schema_tables(merged)}
    for table in required:
        columns = {column.name: column for column in actual[table.name].columns}
        for column in table.columns:
            if columns[column.name] != column:
                raise SpecificationError(
                    f"DATABASE.md: {table.name}.{column.name} changes its seeded type or "
                    "constraints; preserve the source declaration"
                )
        missing = [item for item in table.constraints if item not in actual[table.name].constraints]
        if missing:
            # Keep source constraints even when the model omits their bullets.
            section = next(item for item in table_sections(merged) if item.name == table.name)
            bullets = "\n".join(f"- {item.kind} ({', '.join(item.columns)})" for item in missing)
            merged = (
                merged[: section.end].rstrip("\n")
                + "\n\n"
                + bullets
                + "\n\n"
                + merged[section.end :]
            )
    return merged


def strip_examples(template: str) -> str:
    """Remove the template's illustrative blocks, which are guidance and not declarations."""
    return _EXAMPLE_RE.sub("", template)


def seed_blueprint(template: str, source: str = "") -> str:
    """The ``DATABASE.md`` a planning run starts from: the template, plus what the input declared.

    The input specification is provenance, not a Blueprint.  Carrying its table declarations across
    deterministically means a model never has the opportunity to paraphrase them away — the very
    loss that leaves a build implementing a schema nobody declared.
    """
    seeded = merge_schema(strip_examples(template), source)
    sqlite_schema_tables(seeded, source="DATABASE.md")
    return seeded
