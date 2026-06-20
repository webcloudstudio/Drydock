"""Import arbitrary Markdown source material into a Drydock Blueprint."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from drydock.errors import SpecificationError, UsageError
from drydock.init_specification import init_specification

_CODE_EXTENSIONS: frozenset[str] = frozenset(
    {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".rb", ".java", ".cpp", ".c", ".h"}
)


@dataclass(frozen=True)
class ImportResult:
    blueprint: str
    target: str
    blueprint_dir: Path
    source: Path
    imported: tuple[Path, ...]
    initialized: bool


def detect_import_format(source: Path) -> str:
    """Infer the import format from the source path.

    Precedence: speckit (.specify/ present) → source (code files present) → markdown.
    Raises UsageError when format cannot be determined.
    """
    if (source / ".specify").is_dir():
        return "speckit"
    if source.is_dir() and any(
        p.suffix in _CODE_EXTENSIONS for p in source.rglob("*") if p.is_file()
    ):
        return "source"
    if source.suffix.lower() == ".md":
        return "markdown"
    if source.is_dir() and any(p.suffix.lower() == ".md" for p in source.rglob("*") if p.is_file()):
        return "markdown"
    raise UsageError(
        f"Cannot detect import format for: {source}\n"
        "  Specify --format markdown, --format source, or --format speckit."
    )


def _import_files(source: Path) -> list[tuple[Path, Path]]:
    if source.is_file():
        return [(source, Path(source.name))]
    if not source.is_dir():
        raise SpecificationError(f"Import source not found: {source}")
    files = [
        (path, path.relative_to(source)) for path in sorted(source.rglob("*")) if path.is_file()
    ]
    if not files:
        raise SpecificationError(f"No files found under: {source}")
    return files


def import_markdown(
    blueprint: str, target: str, source: Path, target_directory: Path
) -> ImportResult:
    """Preserve a Markdown import file or directory under ``blueprint/sources/``.

    A directory is copied recursively without filtering by extension so referenced
    assets and companion files remain available to downstream analysis.

    Seeds only root identity files (METADATA.md, README.md). Typed spec files are
    ``plan create`` outputs; COMPASS.md is an ``analyze`` output. After import,
    ``blueprint/`` holds only ``sources/``.
    """
    source = source.expanduser().resolve()
    target_dir = target_directory / target
    blueprint_dir = target_dir / "blueprint"
    initialized = not (target_dir / "METADATA.md").exists()
    init_specification(blueprint, target_dir, update=True, root_identity_only=True)

    sources_dir = blueprint_dir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    (sources_dir / ".drydock-import").write_text(
        f"source: {source}\nformat: markdown\n", encoding="utf-8"
    )
    imported: list[Path] = []
    for source_path, relative in _import_files(source):
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


def import_intent(target: str, source: Path, target_directory: Path) -> ImportResult:
    """Copy a user intent document to COMPASS.md at the Target root.

    The source file is placed as-is; no LLM or template transformation is applied.
    The user is expected to open and edit it (manually or via QuarterDeck) to match
    the COMPASS.md format before running drydock analyze.
    """
    source = source.expanduser().resolve()
    if not source.is_file():
        raise SpecificationError(f"Intent source not found: {source}")

    target_dir = target_directory / target
    target_dir.mkdir(parents=True, exist_ok=True)

    dest = target_dir / "COMPASS.md"
    shutil.copyfile(source, dest)

    return ImportResult(
        blueprint=target,
        target=target,
        blueprint_dir=target_dir,
        source=source,
        imported=(dest,),
        initialized=False,
    )
