"""Detect imported intent material and seed target COMPASS.md verbatim."""

from __future__ import annotations

import re
from pathlib import Path

_INTENT_FILENAMES = frozenset({"compass.md", "intent.md", "constitution.md"})

# The Compass files are human direction, not technical surface. They are never
# compacted and never carry a ``*_compact.md`` derivative: there is no contract
# to extract from them, and COMPASS.md is injected into every build step whole.
COMPASS_FILENAMES = frozenset({"COMPASS.md", "PLAN_COMPASS.md", "ANALYZE_COMPASS.md"})
_COMPASS_STATE_FILENAME = ".drydock-compass"
# A document is intent material when its *leading* heading declares it so. Every Typed
# Specification template carries a ``## Guardrails`` section, so matching the marker anywhere
# in the body classified ordinary Blueprint sources as Compass material and excluded them from
# source lineage. Only the first heading identifies the document.
_INTENT_HEADING_RE = re.compile(
    r"(?i)^#{1,6}\s*(?:compass|constitution|guardrails|author'?s?\s+intent)\b"
)
_HEADING_RE = re.compile(r"(?m)^#{1,6}\s+\S.*$")
_SELF_IDENTIFY_RE = re.compile(r"(?i)\bthis\s+is\s+the\s+author'?s?\s+intent\b")


def _state_path(target_dir: Path) -> Path:
    return target_dir / _COMPASS_STATE_FILENAME


def mark_compass_imported(target_dir: Path, source: Path | None = None) -> None:
    """Mark target COMPASS.md as imported raw material awaiting analyze normalization."""
    lines = ["state: imported"]
    if source is not None:
        lines.append(f"source: {source}")
    _state_path(target_dir).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def compass_import_pending(target_dir: Path) -> bool:
    """Return True when COMPASS.md was imported and has not yet been normalized."""
    path = _state_path(target_dir)
    if not path.is_file():
        return False
    return any(
        line.strip() == "state: imported" for line in path.read_text(encoding="utf-8").splitlines()
    )


def clear_compass_import_pending(target_dir: Path) -> None:
    """Clear normalize-once state after analyze writes a formatted COMPASS.md."""
    try:
        _state_path(target_dir).unlink()
    except FileNotFoundError:
        pass


def mark_compass_authored(target_dir: Path) -> None:
    """Mark target COMPASS.md as Commander-authored: one Compass, and this is it.

    An authored Compass is the project's only Compass. Imported material may still be routed
    to the Compass disposition by an Analysis — the Source Roles table is model-written, and a
    model that disagrees with the author's own table will write ``compass`` where the author
    wrote ``context`` — but that routing may not append to a Compass a human wrote. Two Compass
    documents in one file is two sets of governing rules, and the second one silently wins the
    recency position.
    """
    _state_path(target_dir).write_text("state: authored\n", encoding="utf-8", newline="\n")


def compass_is_authored(target_dir: Path) -> bool:
    """Return True when the Compass was supplied by the Commander rather than composed."""
    path = _state_path(target_dir)
    if not path.is_file():
        return False
    return any(
        line.strip() == "state: authored" for line in path.read_text(encoding="utf-8").splitlines()
    )


def is_compass_file(name: str | Path) -> bool:
    """Return True when a file name is one of the Compass files."""
    return Path(name).name in COMPASS_FILENAMES


def is_compass_source(path: Path) -> bool:
    """Return True when an imported Markdown file is project intent/guardrail material."""
    if path.suffix.lower() != ".md":
        return False
    if path.name.lower() in _INTENT_FILENAMES:
        return True
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    head = text[:16000]
    if _SELF_IDENTIFY_RE.search(head):
        return True
    first_heading = _HEADING_RE.search(head)
    return bool(first_heading and _INTENT_HEADING_RE.match(first_heading.group(0)))


def collect_compass_sources(source_files: list[Path]) -> list[Path]:
    """Return intent-like source files in deterministic import order."""
    return [path for path in sorted(source_files) if is_compass_source(path)]


def seed_compass_from_sources(
    target_dir: Path,
    source_files: list[Path],
    *,
    overwrite_unpopulated: bool,
) -> Path | None:
    """Write target COMPASS.md from imported intent files when safe.

    The imported content is copied verbatim. If multiple intent-like files are present,
    each file body is preserved with a Markdown comment separator naming the source.
    Existing populated COMPASS.md files are never overwritten.
    """
    compass_path = target_dir / "COMPASS.md"
    if compass_path.is_file() and not overwrite_unpopulated:
        return None

    sources = collect_compass_sources(source_files)
    if not sources:
        return None

    chunks: list[str] = []
    for source in sources:
        try:
            text = source.read_text(encoding="utf-8").rstrip()
        except OSError:
            continue
        if not text:
            continue
        if len(sources) > 1:
            chunks.append(f"<!-- Source: {source.name} -->\n\n{text}")
        else:
            chunks.append(text)
    if not chunks:
        return None

    compass_path.parent.mkdir(parents=True, exist_ok=True)
    from drydock.compass_guardrail import apply_guardrail

    content = apply_guardrail("\n\n".join(chunks), target_dir.name, target_dir)
    compass_path.write_text(content, encoding="utf-8", newline="\n")
    mark_compass_imported(target_dir, sources[0])
    return compass_path


#: Compass sections that bind how a Blueprint artifact may be written, in the order a reader
#: needs them. ``Verification Protocol`` is the section that governs acceptance criteria: which
#: story may invoke a supplied harness, and what every invocation must supply. A repair pass
#: that adds an assertion without it writes against rules it was never shown.
NORMATIVE_COMPASS_HEADINGS = ("Constraints", "Guardrails", "Verification Protocol")

_SECTION_HEADING_RE = re.compile(r"(?m)^(?P<hashes>#{1,6})\s+(?P<title>\S.*?)\s*$")


def compass_section(text: str, heading: str) -> str:
    """Return one Compass section including its heading, or an empty string.

    The section runs to the next heading at the same or shallower depth, so subsections stay
    with the section that owns them. Matching is case-insensitive on the heading text alone.
    """
    wanted = heading.strip().casefold()
    matches = list(_SECTION_HEADING_RE.finditer(text))
    for index, match in enumerate(matches):
        if match.group("title").casefold() != wanted:
            continue
        depth = len(match.group("hashes"))
        end = len(text)
        for following in matches[index + 1 :]:
            if len(following.group("hashes")) <= depth:
                end = following.start()
                break
        return text[match.start() : end].rstrip()
    return ""


def normative_compass_sections(
    target_dir: Path, headings: tuple[str, ...] = NORMATIVE_COMPASS_HEADINGS
) -> str:
    """Return the Compass sections that bind artifact authorship, or an empty string.

    An absent Compass, or one that declares none of these sections, yields nothing: a prompt
    gains a Compass block only when there is Compass to carry.
    """
    path = target_dir / "COMPASS.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    found = [section for section in (compass_section(text, name) for name in headings) if section]
    return "\n\n".join(found)
