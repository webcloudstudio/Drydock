"""Detect imported intent material and seed target COMPASS.md verbatim."""

from __future__ import annotations

import re
from pathlib import Path

_INTENT_FILENAMES = frozenset({"compass.md", "intent.md", "constitution.md"})
_COMPASS_STATE_FILENAME = ".drydock-compass"
_SELF_IDENTIFY_RE = re.compile(
    r"(?im)"
    r"("
    r"^#{1,6}\s*(?:compass|constitution|guardrails|author'?s?\s+intent)\b"
    r"|"
    r"\bthis\s+is\s+the\s+authors?\s+intent\b"
    r"|"
    r"\bauthor'?s?\s+intent\b"
    r")"
)


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
    return bool(_SELF_IDENTIFY_RE.search(text[:16000]))


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
    compass_path.write_text("\n\n".join(chunks) + "\n", encoding="utf-8", newline="\n")
    mark_compass_imported(target_dir, sources[0])
    return compass_path
