"""Import existing source code into a Drydock Blueprint by preserving files under sources/.

No LLM call is made. The source tree is copied to ``blueprint/sources/`` for later analysis by
``drydock analyze`` or conformance workflows. Stack detection is provided as a reusable helper
so downstream commands can determine the technology context without re-reading the source.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from drydock.compass_sources import seed_compass_from_sources
from drydock.errors import SpecificationError
from drydock.init_specification import init_specification
from drydock.metadata import METADATA_NAME, set_field

_EXCLUDE_DIRS: frozenset[str] = frozenset({
    "venv",
    ".venv",
    "env",
    "__pycache__",
    "node_modules",
    ".git",
    "dist",
    "build",
    ".eggs",
})

# Stack detection markers — used by this module and reusable by analyze/build steps.
_STACK_FILE_MARKERS: list[tuple[str, str]] = [
    ("requirements.txt", "Python"),
    ("package.json", "Node.js"),
    ("Cargo.toml", "Rust"),
    ("go.mod", "Go"),
]
_STACK_CONTENT_MARKERS: list[tuple[str, str, str]] = [
    ("requirements.txt", "flask", "Flask"),
    ("requirements.txt", "django", "Django"),
    ("requirements.txt", "fastapi", "FastAPI"),
]
_SQLITE_SUFFIXES: frozenset[str] = frozenset({".db", ".sqlite", ".sqlite3"})


@dataclass(frozen=True)
class ImportSourceResult:
    blueprint: str
    target: str
    blueprint_dir: Path
    source: Path
    imported: tuple[Path, ...]
    initialized: bool


def detect_stack(source: Path) -> list[str]:
    """Return detected technology stack labels for a source directory.

    Reusable by ``drydock analyze`` and other downstream commands that need the
    technology context without re-scanning the source tree.
    """
    hints: list[str] = []
    seen: set[str] = set()

    def add(label: str) -> None:
        if label not in seen:
            hints.append(label)
            seen.add(label)

    for filename, label in _STACK_FILE_MARKERS:
        if (source / filename).is_file():
            add(label)

    for filename, substring, label in _STACK_CONTENT_MARKERS:
        candidate = source / filename
        if candidate.is_file():
            try:
                if substring in candidate.read_text(encoding="utf-8", errors="replace").lower():
                    add(label)
            except OSError:
                pass

    # Bootstrap — check templates/ and static/ for the string "bootstrap"
    for subdir_name in ("templates", "static"):
        subdir = source / subdir_name
        if subdir.is_dir():
            try:
                for p in subdir.rglob("*"):
                    if p.is_file():
                        try:
                            if (
                                "bootstrap"
                                in p.read_text(encoding="utf-8", errors="replace").lower()
                            ):
                                add("Bootstrap")
                                break
                        except OSError:
                            continue
            except OSError:
                pass

    # SQLite — any .db/.sqlite file in the tree
    try:
        for p in source.rglob("*"):
            if p.is_file() and p.suffix.lower() in _SQLITE_SUFFIXES:
                add("SQLite")
                break
    except OSError:
        pass

    return hints


def _is_excluded(rel: Path) -> bool:
    return any(part in _EXCLUDE_DIRS for part in rel.parts)


def import_source(
    blueprint: str, target: str, source: Path, target_directory: Path
) -> ImportSourceResult:
    """Copy source code files to ``blueprint/sources/``.

    Seeds only root identity files (METADATA.md, README.md). After import,
    ``blueprint/`` holds only ``sources/``; typed spec files are ``plan create``
    outputs and COMPASS.md is an ``analyze`` output.
    """
    source = source.expanduser().resolve()
    if not source.is_dir():
        raise SpecificationError(f"Import source must be a directory for --format source: {source}")

    target_dir = target_directory / target
    blueprint_dir = target_dir / "blueprint"
    initialized = not (target_dir / "METADATA.md").exists()
    init_specification(blueprint, target_dir, update=True, root_identity_only=True)

    sources_dir = blueprint_dir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    (sources_dir / ".drydock-import").write_text(
        f"source: {source}\nformat: source\n", encoding="utf-8"
    )

    imported: list[Path] = []
    try:
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(source)
            if _is_excluded(rel):
                continue
            destination = sources_dir / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            imported.append(destination)
    except OSError as exc:
        raise SpecificationError(f"Cannot copy source files: {exc}") from exc
    seed_compass_from_sources(target_dir, imported, overwrite_unpopulated=False)

    detected = detect_stack(source)
    if detected:
        set_field(
            target_dir / METADATA_NAME,
            "stack",
            "/".join(detected),
            overwrite=False,
        )

    return ImportSourceResult(
        blueprint=blueprint,
        target=target,
        blueprint_dir=blueprint_dir,
        source=source,
        imported=tuple(imported),
        initialized=initialized,
    )
