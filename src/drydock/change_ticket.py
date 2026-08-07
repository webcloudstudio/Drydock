"""The one change-ticket format, shared by both refit paths.

A change ticket is how work reaches ``build`` without editing a Blueprint. Blueprints are frozen
once planned, so the graph only ever grows: a ticket becomes a new story whose ``implements:``
names the ticket file, and the effective specification is the Blueprint plus its ticket chain.

Two commands author tickets and they must produce the same artifact. ``drydock refit`` conforms
hand-authored tickets — the production workflow, where a change arrives through an enterprise
approval process. ``drydock refit --sources`` authors them from an imported source delta — the
development workflow, where the Commander edits the specification and expects the system to keep
up. Production cutover changes who writes a ticket, not what a ticket is, so both write
``blueprint/changes/TICKET-NNN-{Name}.md`` with the header below.

Scope is the field that keeps an addition from overreaching. A ticket that merely adds behavior
must not claim authority over its parent Blueprint, or a single new sentence would silently
supersede every assertion already proven about that Blueprint. ``additive`` supersedes nothing;
``amending`` supersedes only the sections it names, and those sections are checked against the
parent so a ticket cannot amend something that does not exist.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from drydock.errors import SpecificationError

CHANGES_DIRNAME = "changes"
SCOPES = ("additive", "amending")
AMENDED_SECTIONS_HEADING = "## Amended Sections"

_TICKET_RE = re.compile(r"^TICKET-(\d{3,})-(.+)\.md$")
_ROW_RE = re.compile(r"^\|\s*([A-Za-z][A-Za-z ]*?)\s*\|\s*(.*?)\s*\|\s*$", re.MULTILINE)
_VERSION_RE = re.compile(r"^(\d{8})\s+V(\d+)$")
_HEADING_RE = re.compile(r"^#{2,6}\s+(.*?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class TicketHeader:
    """The typed header every change ticket carries."""

    version: str
    description: str
    amends: str
    depends_on: tuple[str, ...] = ()
    scope: str = "amending"
    origin: str = ""
    created: str = ""
    stories: tuple[str, ...] = ()


@dataclass
class TicketBody:
    """The authored content of a ticket, kept separate from its header."""

    summary: str = ""
    specification: str = ""
    amended_sections: tuple[str, ...] = ()
    downstream_impact: tuple[str, ...] = ()
    requirements: tuple[tuple[str, str], ...] = field(default_factory=tuple)


def changes_dir(blueprint_dir: Path) -> Path:
    return blueprint_dir / CHANGES_DIRNAME


def next_ticket_number(blueprint_dir: Path) -> int:
    """Ticket numbers are the author's ordering signal, so they only ever increase."""
    directory = changes_dir(blueprint_dir)
    if not directory.is_dir():
        return 1
    numbers = [
        int(match.group(1))
        for path in directory.glob("TICKET-*.md")
        if (match := _TICKET_RE.match(path.name))
    ]
    return max(numbers, default=0) + 1


def slugify_ticket_name(text: str) -> str:
    """``Mark a book read`` → ``Mark-A-Book-Read``, matching the TICKET-NNN-{Name} convention."""
    words = [word for word in re.split(r"[^A-Za-z0-9]+", text) if word]
    return "-".join(word[:1].upper() + word[1:] for word in words) or "Change"


def ticket_filename(number: int, name: str) -> str:
    return f"TICKET-{number:03d}-{slugify_ticket_name(name)}.md"


def ticket_version(existing_text: str | None, today: str) -> str:
    """``20260806 V1``, incrementing only when a version already exists for the same day."""
    stamp = today.replace("-", "")
    if existing_text:
        header = parse_ticket_header(existing_text)
        if header is not None:
            match = _VERSION_RE.match(header.version.strip())
            if match and match.group(1) == stamp:
                return f"{stamp} V{int(match.group(2)) + 1}"
    return f"{stamp} V1"


def scope_for_delta(delta: str | None) -> str:
    """An addition adds; a change or a removal alters what is already specified."""
    return "additive" if delta == "added" else "amending"


def scope_clause(scope: str, amends: str) -> str:
    """The sentence that fixes a ticket's authority over its parent.

    Without this, every ticket implicitly governed its whole parent Blueprint, so a one-sentence
    addition superseded assertions it never mentioned.
    """
    if scope == "additive":
        return (
            f"This ticket is additive. It supersedes nothing; every assertion in {amends} "
            "remains in force."
        )
    return (
        f"This ticket amends {amends}. It supersedes only the sections named under "
        f"`{AMENDED_SECTIONS_HEADING}`; every other assertion in {amends} remains in force."
    )


def parent_sections(parent_text: str) -> tuple[str, ...]:
    return tuple(match.group(1).strip() for match in _HEADING_RE.finditer(parent_text))


def validate_amended_sections(
    sections: Sequence[str], *, amends: str, parent_text: str | None
) -> None:
    """An amending ticket may only supersede sections the parent actually has.

    A ticket naming a section that does not exist supersedes nothing, which is worse than failing:
    the change looks governed and is not.
    """
    if parent_text is None:
        return
    known = {section.casefold() for section in parent_sections(parent_text)}
    unknown = [section for section in sections if section.strip().casefold() not in known]
    if unknown:
        raise SpecificationError(
            f"Ticket amends sections absent from {amends}: {', '.join(unknown)}"
        )


def render_ticket(
    header: TicketHeader,
    *,
    name: str,
    body: TicketBody,
    parent_text: str | None = None,
) -> str:
    """Render the normative ticket. Validation happens here so no invalid ticket reaches disk."""
    if header.scope not in SCOPES:
        raise SpecificationError(
            f"Unknown ticket scope: {header.scope} (expected one of {', '.join(SCOPES)})"
        )
    if header.scope == "amending" and body.amended_sections:
        validate_amended_sections(
            body.amended_sections, amends=header.amends, parent_text=parent_text
        )

    rows = [
        ("Version", header.version),
        ("Description", header.description),
        ("Amends", header.amends),
        ("Depends On", ", ".join(header.depends_on)),
        ("Scope", header.scope),
    ]
    if header.origin:
        rows.append(("Origin", header.origin))
    if header.created:
        rows.append(("Created", header.created))
    if header.stories:
        rows.append(("Stories", ", ".join(header.stories)))

    lines = [f"# CHANGE: {name}", "", "| Field       | Value |", "|-------------|-------|"]
    lines.extend(f"| {label} | {value} |" for label, value in rows)
    lines.extend(["", scope_clause(header.scope, header.amends), ""])

    if body.summary:
        lines.extend(["## Summary", "", body.summary.strip(), ""])
    if body.requirements:
        lines.extend(["## Requirements", ""])
        for requirement_name, text in body.requirements:
            lines.extend([f"### {requirement_name}", "", f"> {text.strip()}", ""])
    if body.specification:
        lines.extend(["## Specification", "", body.specification.strip(), ""])
    if body.amended_sections:
        lines.extend([AMENDED_SECTIONS_HEADING, ""])
        lines.extend(f"- {section}" for section in body.amended_sections)
        lines.append("")
    if body.downstream_impact:
        lines.extend([
            "## Downstream Impact",
            "",
            "This ticket changes a contract other stories consume. Rebuild or defer each:",
            "",
        ])
        lines.extend(f"- {item}" for item in body.downstream_impact)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse_ticket_header(text: str) -> TicketHeader | None:
    """Read the header table. Returns ``None`` when the ticket has no ``Amends`` row.

    Tolerant by design: hand-authored tickets predate ``Scope``/``Origin``/``Created``/``Stories``
    and must keep working, so only ``Amends`` is required.
    """
    rows = {label.strip().casefold(): value for label, value in _ROW_RE.findall(text)}
    amends = rows.get("amends", "").strip()
    if not amends or amends.casefold() == "value":
        return None
    scope = rows.get("scope", "").strip().casefold() or "amending"
    return TicketHeader(
        version=rows.get("version", "").strip(),
        description=rows.get("description", "").strip(),
        amends=amends,
        depends_on=tuple(
            item.strip() for item in rows.get("depends on", "").split(",") if item.strip()
        ),
        scope=scope if scope in SCOPES else "amending",
        origin=rows.get("origin", "").strip(),
        created=rows.get("created", "").strip(),
        stories=tuple(item.strip() for item in rows.get("stories", "").split(",") if item.strip()),
    )
