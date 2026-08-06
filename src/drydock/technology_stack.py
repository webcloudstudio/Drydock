"""The Technology Stack artifact: the target's technology decisions of record.

``TECHNOLOGY_STACK.md`` maps each technology the product uses to the Rigging
best-practice file that governs building it, or to nothing when no such guidance
exists. ``drydock analyze`` proposes the file once; the Commander owns it
thereafter. ``drydock plan`` reads it to emit per-story ``stack:`` fields.

A technology without Rigging guidance is normal and never an error: the builder
reports an unresolved name as a missing context file and proceeds on general
best practice.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from drydock.paths import get_rigging_root

FILENAME = "TECHNOLOGY_STACK.md"

HEADER = ("Technology", "Rigging", "Notes")

#: Rendered in the Rigging column when a technology has no governing Rigging file.
NONE_CELL = "—"

#: Cell values that mean "no Rigging guidance".
_EMPTY_CELLS = frozenset({"", "-", "—", "--", "none", "n/a"})

#: Marker line recording that the Commander accepted the stack as it stands.
#: Its presence is the whole approval state; its value is the approval date.
_APPROVED_RE = re.compile(r"^\*\*Approved:\*\*\s*(.+?)\s*$", re.MULTILINE)

_DEFAULT_CATEGORY = "Technologies"
_CATEGORY_ORDER = ["Web Server", "Persistence", "AWS", "Technologies", "Branding"]
_CATEGORY_HEADER = re.compile(r"^\*\*Category:\*\*\s*(.+?)\s*$", re.MULTILINE)

_PREAMBLE = (
    "Technology decisions of record for this Target. One row per technology, naming the",
    "Rigging best-practice file that governs building it.",
    "",
    f"A `{NONE_CELL}` in the Rigging column means no Rigging guidance exists for that",
    "technology; the builder applies general best practice instead. Adding a row never",
    "requires a matching Rigging file.",
    "",
    "`drydock analyze` proposes this file once. It is owned by the Commander thereafter and",
    "is never overwritten. `drydock plan` reads it to assign per-story `stack:` guidance.",
)


@dataclass(frozen=True)
class StackEntry:
    """One technology and the Rigging file that governs it."""

    technology: str
    rigging: str | None = None
    notes: str = ""


# ── Rigging catalog ─────────────────────────────────────────────────────────────


def _category(path: Path) -> str:
    """Read the ``**Category:**`` header from a Rigging file's header block.

    Only the first 20 lines are scanned — the header block sits at the top of every
    Rigging file. Files without the header fall into the default category.
    """
    try:
        head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:20])
    except OSError:
        return _DEFAULT_CATEGORY
    match = _CATEGORY_HEADER.search(head)
    return match.group(1) if match else _DEFAULT_CATEGORY


def rigging_catalog() -> list[tuple[str, str]]:
    """Return ``(filename, category)`` pairs for every selectable Rigging file.

    Source: ``Rigging/BRA*.md`` plus ``Rigging/stack/*.md``, excluding ``README.md``
    and ``_compact`` variants. Categories come from each file's ``**Category:**``
    header; only the tooling opens these files, never the LLM.
    """
    try:
        root = get_rigging_root()
    except Exception:
        return []
    paths = [p for p in root.glob("BRA*.md") if "_compact" not in p.name]
    paths += [p for p in (root / "stack").glob("*.md") if "_compact" not in p.name]
    return sorted((p.name, _category(p)) for p in paths if p.name != "README.md")


def rigging_names() -> list[str]:
    """Return every selectable Rigging filename."""
    return [name for name, _ in rigging_catalog()]


def rigging_groups(catalog: list[tuple[str, str]] | None = None) -> list[dict]:
    """Group catalog entries by category for a grouped selector.

    Known categories render in ``_CATEGORY_ORDER``; unknown categories follow
    alphabetically.
    """
    catalog = rigging_catalog() if catalog is None else catalog
    by_category: dict[str, list[str]] = {}
    for name, category in catalog:
        by_category.setdefault(category, []).append(name)
    ordered = [c for c in _CATEGORY_ORDER if c in by_category]
    ordered += sorted(c for c in by_category if c not in _CATEGORY_ORDER)
    return [{"label": c, "options": sorted(by_category[c])} for c in ordered]


def _normalize(value: str) -> str:
    """Reduce a technology or filename to a comparable token."""
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def suggest_rigging(technology: str, catalog: list[str] | None = None) -> str | None:
    """Return the Rigging filename that best matches ``technology``, or ``None``.

    Exact normalized equality wins outright; otherwise a close fuzzy match is
    accepted. A technology with no plausible match returns ``None`` rather than a
    wrong guess — an unmatched technology is a supported outcome, not a failure.
    """
    names = rigging_names() if catalog is None else catalog
    token = _normalize(technology)
    if not token or not names:
        return None
    by_token: dict[str, str] = {}
    for name in names:
        by_token.setdefault(_normalize(name.removesuffix(".md")), name)
    if token in by_token:
        return by_token[token]
    close = difflib.get_close_matches(token, list(by_token), n=1, cutoff=0.85)
    return by_token[close[0]] if close else None


# ── Parse and render ────────────────────────────────────────────────────────────


def _escape_cell(value: str) -> str:
    return value.replace("|", r"\|").replace("\n", " ")


def _split_row(line: str) -> list[str]:
    return [cell.strip().replace(r"\|", "|") for cell in re.split(r"(?<!\\)\|", line.strip("|"))]


def render(entries: list[StackEntry], approved: str | None = None) -> str:
    """Render entries as the canonical ``TECHNOLOGY_STACK.md`` document.

    ``approved`` is the approval date to record; ``None`` leaves the document
    unapproved. Callers that rewrite an existing document must carry its current
    approval value forward — editing a row is not an act of unapproval.
    """
    lines = ["# Technology Stack", ""]
    if approved:
        lines.extend([f"**Approved:** {approved}", ""])
    lines.extend([*_PREAMBLE, ""])
    lines.append("| " + " | ".join(HEADER) + " |")
    lines.append("|" + "---|" * len(HEADER))
    lines.extend(
        f"| {_escape_cell(entry.technology)} | "
        f"{_escape_cell(entry.rigging or NONE_CELL)} | "
        f"{_escape_cell(entry.notes)} |"
        for entry in entries
    )
    return "\n".join(lines) + "\n"


def parse(text: str) -> list[StackEntry]:
    """Parse the Technology Stack table.

    Rows that do not fit the schema are skipped rather than raising: this file is
    hand-edited and must never block a run. A row with an empty Technology cell is
    dropped, since it carries no decision.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if tuple(_split_row(line)) != HEADER or index + 1 >= len(lines):
            continue
        entries: list[StackEntry] = []
        for row_line in lines[index + 2 :]:
            if "|" not in row_line:
                break
            cells = _split_row(row_line)
            if not cells or not cells[0]:
                continue
            # A short row is read as far as it goes: a technology alone is a valid
            # decision ("we use this, no Rigging guidance"), so it is never dropped.
            raw_rigging = cells[1] if len(cells) > 1 else ""
            rigging = raw_rigging if raw_rigging.strip().lower() not in _EMPTY_CELLS else ""
            entries.append(
                StackEntry(
                    technology=cells[0],
                    rigging=rigging or None,
                    notes=cells[2] if len(cells) > 2 else "",
                )
            )
        return entries
    return []


# ── Target-local file access ────────────────────────────────────────────────────


def path_for(target_dir: Path) -> Path:
    return target_dir / FILENAME


def load(target_dir: Path) -> list[StackEntry]:
    """Return the target's stack entries, or ``[]`` when absent or unreadable."""
    path = path_for(target_dir)
    try:
        return parse(path.read_text(encoding="utf-8"))
    except OSError:
        return []


def load_text(target_dir: Path) -> str:
    """Return the raw document text, or ``""`` when absent."""
    try:
        return path_for(target_dir).read_text(encoding="utf-8")
    except OSError:
        return ""


def write(target_dir: Path, entries: list[StackEntry], approved: str | None = None) -> Path:
    """Write the Technology Stack document, replacing any existing content."""
    path = path_for(target_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(entries, approved), encoding="utf-8")
    return path


# ── Commander approval ──────────────────────────────────────────────────────────


def parse_approved(text: str) -> str | None:
    """Return the recorded approval date, or ``None`` when the document is unapproved."""
    match = _APPROVED_RE.search(text)
    return match.group(1) if match else None


def approved_on(target_dir: Path) -> str | None:
    """Return the target's Technology Stack approval date, or ``None``."""
    return parse_approved(load_text(target_dir))


def is_approved(target_dir: Path) -> bool:
    """Return True when the Commander has accepted the target's Technology Stack.

    An absent file is not approved: the stack is an outstanding action until the
    Commander either edits and approves it or approves it as proposed.
    """
    return approved_on(target_dir) is not None


def approve(target_dir: Path, when: str | None = None) -> Path:
    """Record Commander approval of the target's Technology Stack.

    Rewrites the document from its parsed rows so the marker is placed
    canonically. Approving an already approved stack re-dates it.
    """
    return write(target_dir, load(target_dir), when or date.today().isoformat())


def stack_files_from(entries: list[StackEntry]) -> list[str]:
    """Return the distinct Rigging filenames named by ``entries``, in order."""
    seen: list[str] = []
    for entry in entries:
        if entry.rigging and entry.rigging not in seen:
            seen.append(entry.rigging)
    return seen


def stack_files(target_dir: Path) -> list[str]:
    """Return the distinct Rigging filenames named by the target's Technology Stack."""
    return stack_files_from(load(target_dir))


# ── Seeding and migration ───────────────────────────────────────────────────────

_LEGACY_QUESTIONNAIRE = Path("QuarterDeck") / "questionnaires" / "discovery-stack.json"


def _legacy_selection(target_dir: Path) -> list[str]:
    """Return Rigging filenames from a superseded ``discovery-stack`` answer."""
    path = target_dir / _LEGACY_QUESTIONNAIRE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    for question in data.get("questions", []):
        if question.get("id") != "stack_components":
            continue
        answer = question.get("answer", "")
        values = answer if isinstance(answer, list) else str(answer).split(",")
        return [str(v).strip() for v in values if str(v).strip()]
    return []


def _archive_legacy_questionnaire(target_dir: Path) -> None:
    """Mark the superseded stack questionnaire archived, preserving its content."""
    path = target_dir / _LEGACY_QUESTIONNAIRE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if data.get("archived"):
        return
    data["archived"] = True
    data["superseded_by"] = FILENAME
    for question in data.get("questions", []):
        question["required_before_plan"] = False
    try:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return


def _entries_from_rigging(names: list[str]) -> list[StackEntry]:
    """Derive stack rows from bare Rigging filenames."""
    return [StackEntry(technology=name.removesuffix(".md"), rigging=name) for name in names]


def ensure_technology_stack(
    target_dir: Path, entries: list[StackEntry] | None = None
) -> Path | None:
    """Create ``TECHNOLOGY_STACK.md`` when absent; never overwrite an existing file.

    When no entries are supplied, a superseded ``discovery-stack`` answer is
    migrated into rows. The superseded questionnaire is archived once the file
    exists so it stops gating and stops being counted as open.

    Returns the written path, or ``None`` when the file already existed or there
    was nothing to seed.
    """
    path = path_for(target_dir)
    if path.is_file():
        _archive_legacy_questionnaire(target_dir)
        return None
    rows = list(entries or [])
    if not rows:
        rows = _entries_from_rigging(_legacy_selection(target_dir))
    if not rows:
        return None
    written = write(target_dir, rows)
    _archive_legacy_questionnaire(target_dir)
    return written
