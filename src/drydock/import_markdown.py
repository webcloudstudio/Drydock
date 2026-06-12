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
    target: str
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


def import_markdown(
    blueprint: str, target: str, source: Path, target_directory: Path
) -> ImportResult:
    """Preserve Markdown under ``targets/<Target>/blueprint/sources/`` and seed templates."""
    source = source.expanduser().resolve()
    target_dir = target_directory / target
    blueprint_dir = target_dir / "blueprint"
    initialized = not (blueprint_dir / "ARCHITECTURE.md").exists()
    init_specification(blueprint, target_dir, update=True)

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
        target=target,
        blueprint_dir=blueprint_dir,
        source=source,
        imported=tuple(imported),
        initialized=initialized,
    )
