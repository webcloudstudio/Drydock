"""Import arbitrary Markdown source material into a Drydock Blueprint."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from drydock.errors import SpecificationError
from drydock.init_specification import init_specification


@dataclass(frozen=True)
class ImportResult:
    blueprint: str
    blueprint_dir: Path
    source: Path
    imported: tuple[Path, ...]
    initialized: bool


def _markdown_files(source: Path) -> list[tuple[Path, Path]]:
    if source.is_file():
        if source.suffix.lower() != ".md":
            raise SpecificationError(f"Markdown import requires a .md file: {source}")
        return [(source, Path(source.name))]
    if not source.is_dir():
        raise SpecificationError(f"Import source not found: {source}")
    files = [
        (path, path.relative_to(source))
        for path in sorted(source.rglob("*"))
        if path.is_file() and path.suffix.lower() == ".md"
    ]
    if not files:
        raise SpecificationError(f"No Markdown files found under: {source}")
    return files


def import_markdown(blueprint: str, source: Path, blueprint_directory: Path) -> ImportResult:
    """Preserve a Markdown file or directory under ``<Blueprint>/sources/``."""
    source = source.expanduser().resolve()
    blueprint_dir = blueprint_directory / blueprint
    initialized = not blueprint_dir.exists()
    if initialized:
        init_specification(blueprint, blueprint_directory)
    elif not blueprint_dir.is_dir():
        raise SpecificationError(f"Blueprint path is not a directory: {blueprint_dir}")

    sources_dir = blueprint_dir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    (sources_dir / ".drydock-import").write_text(
        f"source: {source}\nformat: markdown\n", encoding="utf-8"
    )
    imported: list[Path] = []
    for source_path, relative in _markdown_files(source):
        destination = sources_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, destination)
        imported.append(destination)

    return ImportResult(
        blueprint=blueprint,
        blueprint_dir=blueprint_dir,
        source=source,
        imported=tuple(imported),
        initialized=initialized,
    )
