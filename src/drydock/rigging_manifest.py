"""Maintain the source Rigging selection manifest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from drydock.errors import UsageError

MANIFEST_FILENAME = "MANIFEST.md"
_TABLE_HEADER = "| File | Category | Purpose | Prerequisites |"
_TABLE_SEPARATOR = "|---|---|---|---|"
_DEFAULT_CATEGORY = "Uncategorized"
_DEFAULT_PURPOSE = "—"
_DEFAULT_PREREQUISITES = "—"


@dataclass(frozen=True)
class ManifestAddResult:
    """Files added to the Rigging selection manifest."""

    manifest_path: Path
    added: tuple[Path, ...]
    existing: tuple[Path, ...]


def _rigging_relative(path: Path, rigging_root: Path) -> Path:
    """Resolve a user path and require that it belongs to Rigging."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(rigging_root.resolve())
    except ValueError as exc:
        raise UsageError(f"Rigging input must be inside {rigging_root}: {path}") from exc


def _collect_files(
    files: list[Path] | None,
    directories: list[Path] | None,
    rigging_root: Path,
) -> list[Path]:
    """Return distinct Rigging-relative regular files from user inputs."""
    selected: dict[Path, None] = {}

    for path in files or []:
        if not path.is_file():
            raise UsageError(f"Rigging file does not exist or is not a regular file: {path}")
        relative = _rigging_relative(path, rigging_root)
        if relative.name == MANIFEST_FILENAME and relative.parent == Path("."):
            raise UsageError("Rigging/MANIFEST.md cannot add itself to the manifest")
        selected[relative] = None

    for directory in directories or []:
        if not directory.is_dir():
            raise UsageError(f"Rigging directory does not exist or is not a directory: {directory}")
        _rigging_relative(directory, rigging_root)
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            relative = _rigging_relative(path, rigging_root)
            if relative.name == MANIFEST_FILENAME and relative.parent == Path("."):
                continue
            selected[relative] = None

    return sorted(selected, key=lambda path: path.as_posix())


def _manifest_paths(text: str) -> set[str]:
    """Return File-column paths from the canonical catalog table."""
    paths: set[str] = set()
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().split("|")]
        if len(cells) != 6 or not cells[1].startswith("`") or not cells[1].endswith("`"):
            continue
        paths.add(cells[1][1:-1])
    return paths


def _append_rows(text: str, paths: list[Path]) -> str:
    """Append catalog rows after validating the manifest's table contract."""
    lines = text.splitlines(keepends=True)
    try:
        header_index = next(i for i, line in enumerate(lines) if line.rstrip("\n") == _TABLE_HEADER)
    except StopIteration as exc:
        raise UsageError(
            f"Rigging manifest lacks required catalog header: {_TABLE_HEADER}"
        ) from exc
    if header_index + 1 >= len(lines) or lines[header_index + 1].rstrip("\n") != _TABLE_SEPARATOR:
        raise UsageError("Rigging manifest lacks the required catalog table separator")

    insert_at = header_index + 2
    while insert_at < len(lines) and lines[insert_at].startswith("|"):
        insert_at += 1
    rows = [
        f"| `{path.as_posix()}` | {_DEFAULT_CATEGORY} | {_DEFAULT_PURPOSE} | {_DEFAULT_PREREQUISITES} |\n"
        for path in paths
    ]
    lines[insert_at:insert_at] = rows
    return "".join(lines)


def add_to_manifest(
    *,
    files: list[Path] | None = None,
    directories: list[Path] | None = None,
    rigging_root: Path,
) -> ManifestAddResult:
    """Register regular Rigging files in ``Rigging/MANIFEST.md``.

    Paths are persisted relative to the Rigging root so the catalog remains portable in an
    installed wheel. Existing paths are left unchanged.
    """
    selected = _collect_files(files, directories, rigging_root)
    manifest_path = rigging_root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise UsageError(f"Rigging manifest does not exist: {manifest_path}")

    text = manifest_path.read_text(encoding="utf-8")
    existing_paths = _manifest_paths(text)
    added = [path for path in selected if path.as_posix() not in existing_paths]
    existing = [path for path in selected if path.as_posix() in existing_paths]
    if added:
        manifest_path.write_text(_append_rows(text, added), encoding="utf-8", newline="\n")

    return ManifestAddResult(manifest_path, tuple(added), tuple(existing))
