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

from drydock.paths import get_rigging_root, language_directories

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

#: Selector order, which is build order: the categories that hold foundations come first, in
#: tier order (``rigging_contract.TIER_ORDER``), then the additive ones. ``Frontend`` exists
#: because ``bootstrap5.md`` is not a web server — it was filed under ``Web Server`` and shown to
#: the Commander as one, next to the three files that genuinely are.
_CATEGORY_ORDER = [
    "Language",
    "Web Server",
    "Persistence",
    "Branding",
    "Frontend",
    "AWS",
    "Technologies",
]
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
    paths += [folder / f"{folder.name}.md" for folder in language_directories(root)]
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


def _strip_code_span(value: str) -> str:
    """Drop inline-code backticks around a cell value.

    The file is hand-edited and the specification prints filenames as code spans, so
    ``` `python.md` ``` and ``python.md`` name the same Rigging file. Without this the
    backticked form parses as a distinct, unresolvable name and degrades silently into
    a missing build-time context file.
    """
    stripped = value.strip()
    if len(stripped) > 1 and stripped.startswith("`") and stripped.endswith("`"):
        return stripped.strip("`").strip()
    return stripped


def _split_row(line: str) -> list[str]:
    return [
        _strip_code_span(cell).replace(r"\|", "|")
        for cell in re.split(r"(?<!\\)\|", line.strip("|"))
    ]


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
    return approved_on(target_dir) is not None and not foundation_defects(load(target_dir))


def approve(target_dir: Path, when: str | None = None) -> Path:
    """Record Commander approval of the target's Technology Stack.

    Rewrites the document from its parsed rows so the marker is placed
    canonically. Approving an already approved stack re-dates it.
    """
    entries = load(target_dir)
    defects = foundation_defects(entries)
    if defects:
        raise ValueError("; ".join(defects))
    return write(target_dir, entries, when or date.today().isoformat())


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


def declared_language(target_dir: Path, entries: list[StackEntry] | None = None) -> str | None:
    """The Target's implementation language, or ``None`` when the stack names none."""
    rows = load(target_dir) if entries is None else entries
    from drydock.paths import resolve_rigging_file

    selected = []
    for name in stack_files_from(rows):
        path = resolve_rigging_file(name)
        if path and re.search(
            r"^\*\*Type:\*\*\s*language\s*$", path.read_text(encoding="utf-8"), re.MULTILINE
        ):
            selected.append(path.stem)
    return selected[0] if len(selected) == 1 else None


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


# ── Foundation selection ────────────────────────────────────────────────────────


def type_counts() -> dict[str, dict[str, int]]:
    """Load the single count policy shared by validation and selectors."""
    return json.loads((get_rigging_root() / "rigging_types.json").read_text(encoding="utf-8"))


def rigging_types() -> dict[str, str]:
    from drydock.paths import resolve_rigging_file

    result = {}
    for name in rigging_names():
        path = resolve_rigging_file(name) or get_rigging_root() / name
        match = re.search(r"^\*\*Type:\*\*\s*(\S+)", path.read_text(encoding="utf-8"), re.MULTILINE)
        if match:
            result[name] = match[1]
    return result


def foundation_defects(entries: list[StackEntry]) -> list[str]:
    """Validate selected types, shipped language bundles and language prerequisites."""
    from drydock.paths import resolve_rigging_file

    types = rigging_types()
    selected = stack_files_from(entries)
    defects = []
    for kind, bounds in type_counts().items():
        names = [name for name in selected if types.get(name) == kind]
        if not bounds["min"] <= len(names) <= bounds["max"]:
            defects.append(
                f"{kind}: {len(names)} selected; select {bounds['min']}..{bounds['max']} ({', '.join(names)})"
            )
    languages = [name for name in selected if types.get(name) == "language"]
    for name in languages:
        folder = get_rigging_root() / "languages" / Path(name).stem
        if not all(
            path.exists()
            for path in (
                folder / name,
                folder / name.replace(".md", "_compact.md"),
                folder / "persistence",
                folder / "acceptance",
            )
        ):
            defects.append(f"language: no complete shipped bundle for {name}")
    for name in selected:
        if name not in types:
            continue
        path = resolve_rigging_file(name) or get_rigging_root() / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for declaration in re.findall(r"^Prerequisites?:\s*(.+)$", text, re.MULTILINE):
            for prerequisite in re.findall(r"`([^`]+)`", declaration):
                required = Path(prerequisite).name
                if types.get(required) == "language" and required not in languages:
                    defects.append(f"{name}: requires language {required}")
    for entry in entries:
        suggested = suggest_rigging(entry.technology) if not entry.rigging else None
        if suggested and types.get(suggested) in type_counts():
            defects.append(
                f"{entry.technology}: selects no Rigging file; select {suggested} or remove the row"
            )
    return defects


def require_approved(target_dir: Path) -> None:
    from drydock.errors import SpecificationError

    defects = foundation_defects(load(target_dir))
    if approved_on(target_dir) is None:
        defects.append(
            "TECHNOLOGY_STACK.md requires Commander approval before planning or building"
        )
    if defects:
        raise SpecificationError("; ".join(defects))


def selection_identity(entries: list[StackEntry]) -> frozenset[str]:
    types = rigging_types()
    return frozenset(
        name for name in stack_files_from(entries) if types.get(name) in {"language", "database"}
    )


def selected_foundations(entries: list[StackEntry]) -> dict[str, str | list[str]]:
    """Return selected foundations, preserving every database engine."""
    return split_foundations(entries)[0]


#: What a new Target gets when nobody has chosen yet. It is a starting point the Commander
#: overrides in one click, not a policy: Drydock still refuses to *infer* a web server for a
#: stack that names one and selects no file.
DEFAULT_FOUNDATIONS = {
    "language": "python.md",
    "web-server": "fastapi.md",
    "database": "sqlite.md",
}

#: Kinds whose display name is not simply the kind title-cased.
_KIND_LABELS = {"cli": "CLI"}


def split_foundations(
    entries: list[StackEntry],
) -> tuple[dict[str, str | list[str]], list[StackEntry]]:
    """Split stack rows into the foundation choices and everything else.

    A row is a foundation choice when it selects a Rigging file that publishes a foundation, or
    when it selects nothing and names a technology that would resolve to one. The second case is
    the unanswered row ``foundation_defects`` refuses: it belongs in the exclusive selector, not
    in the free-text table where it can only be half-answered.
    """
    types = rigging_types()
    exclusive = {kind for kind, bounds in type_counts().items() if bounds["max"] == 1}
    chosen: dict[str, str | list[str]] = {}
    remaining = []
    for entry in entries:
        name = entry.rigging or suggest_rigging(entry.technology)
        kind = types.get(name or "")
        if kind in exclusive:
            chosen.setdefault(kind, entry.rigging or "")
        else:
            remaining.append(entry)
    return chosen, remaining


def foundation_groups(entries: list[StackEntry] | None = None) -> list[dict]:
    """Render each max-one type as a radio group, with None for optional types."""
    from drydock.rigging_contract import foundation_contracts, tier_label, tier_number

    rows = list(entries or [])
    chosen = split_foundations(rows)[0] if rows else dict(DEFAULT_FOUNDATIONS)
    types = rigging_types()
    contracts = foundation_contracts()
    groups = []
    for kind, bounds in type_counts().items():
        if bounds["max"] != 1:
            continue
        options = sorted(name for name, value in types.items() if value == kind)
        if kind == "language":
            shipped = {folder.name + ".md" for folder in language_directories()}
            options = [name for name in options if name in shipped]
        contract = next((contracts[name] for name in options if name in contracts), None)
        tier = contract.tier if contract else "application"
        groups.append(
            dict(
                kind=kind,
                tier=tier,
                tier_number=tier_number(tier),
                tier_label=tier_label(tier, kind),
                label=_KIND_LABELS.get(kind, kind.replace("-", " ").title()),
                options=options,
                selected=chosen.get(kind, ""),
                multiple=False,
                required=bounds["min"] > 0,
            )
        )
    return groups


def with_foundations(
    entries: list[StackEntry], chosen: dict[str, str | list[str]]
) -> list[StackEntry]:
    """Replace foundation choices; database choices may contain several engines."""
    remaining = split_foundations(entries)[1]
    added = []
    for group in foundation_groups(entries):
        values = chosen.get(group["kind"], "")
        names = [values] if isinstance(values, str) else values
        for name in dict.fromkeys(n.strip() for n in names if n.strip()):
            added.append(StackEntry(technology=name.removesuffix(".md"), rigging=name))
    return added + remaining
