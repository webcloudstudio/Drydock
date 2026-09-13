"""Normalized refit change tickets with preserved upstream front matter.

Ticket systems may provide arbitrary Markdown front matter.  Drydock copies that material
unchanged and reserves only the ``drydock_`` namespace for its own typed fields.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from drydock.errors import SpecificationError

PREFIX = "drydock_"
KINDS = frozenset({
    "blueprint",
    "contract",
    "database-private",
    "database-access-pattern",
    "database-data",
    "documentation",
})
OPERATIONS = frozenset({"add", "change", "remove"})
COMPATIBILITIES = frozenset({"unchanged", "data", "rebuild"})
REQUIRED_FIELDS = frozenset({
    "drydock_id",
    "drydock_subject",
    "drydock_description",
    "drydock_create_dtm",
    "drydock_source_dtm",
    "drydock_source",
    "drydock_source_ref",
    "drydock_amends",
    "drydock_kind",
    "drydock_operation",
    "drydock_status",
})

_FRONT_MATTER_RE = re.compile(r"\A---\r?\n(?P<header>.*?)\r?\n---\r?\n?(?P<body>.*)\Z", re.DOTALL)
_FIELD_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):(?:[ \t]*(.*))?$")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class FrontMatter:
    """Raw header lines, simple field values, and Markdown body from one ticket file."""

    header_lines: tuple[str, ...]
    fields: dict[str, str]
    body: str


@dataclass(frozen=True)
class NormalizedTicket:
    """Validated Drydock fields plus preserved upstream front matter."""

    path: Path
    front_matter: FrontMatter
    drydock_fields: dict[str, str]

    @property
    def ticket_id(self) -> str:
        return self.drydock_fields["drydock_id"]

    @property
    def amends(self) -> str:
        return self.drydock_fields["drydock_amends"]


def split_front_matter(text: str) -> FrontMatter:
    """Extract optional leading YAML-like front matter without interpreting unknown fields."""
    match = _FRONT_MATTER_RE.match(text)
    if not match:
        return FrontMatter((), {}, text)
    header = match.group("header")
    lines = tuple(header.splitlines())
    fields: dict[str, str] = {}
    for line in lines:
        parsed = _FIELD_RE.match(line)
        if parsed:
            fields[parsed.group(1)] = (parsed.group(2) or "").strip()
    return FrontMatter(lines, fields, match.group("body"))


def is_normalized(front_matter: FrontMatter) -> bool:
    return "drydock_id" in front_matter.fields


def parse_normalized_ticket(path: Path) -> NormalizedTicket | None:
    """Read a normalized ticket, or ``None`` when the file is a source ticket."""
    front_matter = split_front_matter(path.read_text(encoding="utf-8"))
    if not is_normalized(front_matter):
        return None
    fields = {key: value for key, value in front_matter.fields.items() if key.startswith(PREFIX)}
    missing = sorted(field for field in REQUIRED_FIELDS if not fields.get(field))
    if missing:
        raise SpecificationError(
            f"Normalized ticket {path.name} is missing required fields: {', '.join(missing)}"
        )
    kind = fields["drydock_kind"]
    if kind not in KINDS:
        raise SpecificationError(f"Normalized ticket {path.name} has invalid drydock_kind: {kind}")
    operation = fields["drydock_operation"]
    if operation not in OPERATIONS:
        raise SpecificationError(
            f"Normalized ticket {path.name} has invalid drydock_operation: {operation}"
        )
    compatibility = fields.get("drydock_compatibility", "")
    if kind == "database-access-pattern" and compatibility not in COMPATIBILITIES:
        raise SpecificationError(
            f"Normalized ticket {path.name} requires drydock_compatibility: "
            f"{', '.join(sorted(COMPATIBILITIES))}"
        )
    if compatibility and compatibility not in COMPATIBILITIES:
        raise SpecificationError(
            f"Normalized ticket {path.name} has invalid drydock_compatibility: {compatibility}"
        )
    return NormalizedTicket(path=path, front_matter=front_matter, drydock_fields=fields)


def _source_datetime(front_matter: FrontMatter, now: datetime) -> str:
    for key in ("updated", "updated_at", "created", "created_at", "timestamp", "date"):
        if value := front_matter.fields.get(key):
            return value
    return now.isoformat()


def _source_parent(front_matter: FrontMatter) -> str:
    for key in ("issue_key", "ticket_key", "key", "id", "ticket_id"):
        if value := front_matter.fields.get(key):
            return value
    return ""


def _subject(front_matter: FrontMatter, source_path: Path) -> str:
    for key in ("summary", "subject", "title", "name"):
        if value := front_matter.fields.get(key):
            return value
    first_line = next((line.strip() for line in front_matter.body.splitlines() if line.strip()), "")
    if first_line.startswith("#"):
        first_line = first_line.lstrip("#").strip()
    return first_line or source_path.stem.replace("-", " ")


def _description(front_matter: FrontMatter, subject: str) -> str:
    body = _WHITESPACE_RE.sub(" ", front_matter.body).strip()
    return body[:240] or subject


def ticket_slug(subject: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", subject)
    return "-".join(word[:1].upper() + word[1:] for word in words) or "Change"


def next_ticket_id(directory: Path) -> str:
    """Allocate the next normalized ticket number without interpreting source filenames."""
    numbers: list[int] = []
    if directory.is_dir():
        for path in directory.glob("*.md"):
            try:
                normalized = parse_normalized_ticket(path)
            except SpecificationError:
                continue
            if normalized is None:
                continue
            match = re.fullmatch(r"TICKET-(\d+)", normalized.ticket_id)
            if match:
                numbers.append(int(match.group(1)))
    return f"TICKET-{max(numbers, default=0) + 1:03d}"


def render_normalized_ticket(
    source_path: Path,
    source_text: str,
    *,
    ticket_id: str,
    amends: str,
    kind: str = "blueprint",
    operation: str = "change",
    compatibility: str | None = None,
    now: datetime | None = None,
    source_ref: str | None = None,
    source_kind: str = "ticket-file",
) -> str:
    """Render one normalized ticket while retaining all non-Drydock source fields verbatim."""
    timestamp = now or datetime.now(UTC)
    front_matter = split_front_matter(source_text)
    reserved = sorted(key for key in front_matter.fields if key.startswith(PREFIX))
    if reserved:
        raise SpecificationError(
            f"Source ticket {source_path.name} uses reserved Drydock fields: {', '.join(reserved)}"
        )
    if kind not in KINDS or operation not in OPERATIONS:
        raise SpecificationError("Cannot render normalized ticket with invalid kind or operation.")
    if kind == "database-access-pattern" and compatibility not in COMPATIBILITIES:
        raise SpecificationError("database-access-pattern tickets require a valid compatibility.")

    subject = _subject(front_matter, source_path)
    fields = [
        f"drydock_id: {ticket_id}",
        f"drydock_subject: {subject}",
        f"drydock_description: {_description(front_matter, subject)}",
        f"drydock_create_dtm: {timestamp.isoformat()}",
        f"drydock_source_dtm: {_source_datetime(front_matter, timestamp)}",
    ]
    if parent := _source_parent(front_matter):
        fields.append(f"drydock_parent: {parent}")
    fields.extend([
        f"drydock_source: {source_kind}",
        f"drydock_source_ref: {source_ref or source_path.name}",
        f"drydock_amends: {amends}",
        f"drydock_kind: {kind}",
        f"drydock_operation: {operation}",
        "drydock_status: pending",
    ])
    if compatibility:
        fields.append(f"drydock_compatibility: {compatibility}")
    header = ["---", *front_matter.header_lines, *fields, "---"]
    evidence = source_text.strip()
    lines = [
        *header,
        "",
        "## Change",
        "",
        _description(front_matter, subject),
        "",
        "## Contract Delta",
        "",
        "To be established from the source ticket and the amended Blueprint.",
        "",
        "## Source Evidence",
        "",
        evidence,
        "",
        "## Acceptance Conditions",
        "",
        "To be established during refit matching.",
        "",
        "## Impact",
        "",
        f"Owner: {amends}",
        "",
    ]
    return "\n".join(lines)
