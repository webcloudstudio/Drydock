"""Import a Spec Kit project into a Drydock Blueprint by preserving files under sources/.

No LLM call is made. The Spec Kit structure (.specify/ and specs/) is copied to
``blueprint/sources/`` for later translation by ``drydock analyze`` or conformance workflows.
``.specify/``'s children are flattened into ``blueprint/sources/`` directly (for example
``.specify/memory/constitution.md`` becomes ``blueprint/sources/memory/constitution.md``) so no
hidden directory is created under ``blueprint/sources/``; ``specs/`` keeps its existing prefix.
Discovery helpers are provided as reusable functions for downstream commands.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from drydock.errors import SpecificationError
from drydock.init_specification import init_specification
from drydock.source_refit import record_import_root

# Spec Kit directories that contain the project specification.
_SPECKIT_SUBDIRS: tuple[str, ...] = (".specify", "specs")


@dataclass(frozen=True)
class SpecKitFeature:
    name: str
    spec: str | None = None
    plan: str | None = None
    research: str | None = None
    data_model: str | None = None
    contracts: dict[str, str] = field(default_factory=dict)
    quickstart: str | None = None


@dataclass(frozen=True)
class ImportSpecKitResult:
    blueprint: str
    target: str
    blueprint_dir: Path
    source: Path
    features_found: tuple[str, ...]
    imported: tuple[Path, ...]
    initialized: bool


def _read_optional(path: Path) -> str | None:
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return None
    return None


def _read_contracts(feature_dir: Path) -> dict[str, str]:
    contracts: dict[str, str] = {}
    contracts_dir = feature_dir / "contracts"
    if contracts_dir.is_dir():
        try:
            for p in sorted(contracts_dir.iterdir()):
                if p.is_file():
                    content = _read_optional(p)
                    if content is not None:
                        contracts[p.name] = content
        except OSError:
            pass
    return contracts


def discover_speckit(source: Path) -> tuple[str | None, list[SpecKitFeature]]:
    """Discover Spec Kit constitution and feature directories.

    Returns ``(constitution_text, features)``.
    Raises ``SpecificationError`` if source is not a Spec Kit project.
    Reusable by ``drydock analyze`` and other downstream commands.
    """
    specify_dir = source / ".specify"
    if not specify_dir.is_dir():
        raise SpecificationError(
            f"Not a Spec Kit project (no .specify/ directory): {source}\n"
            "  Use --format markdown or --format source for other source types."
        )

    constitution = _read_optional(specify_dir / "memory" / "constitution.md")

    features: list[SpecKitFeature] = []
    specs_dir = source / "specs"
    if specs_dir.is_dir():
        try:
            for feature_dir in sorted(specs_dir.iterdir()):
                if not feature_dir.is_dir():
                    continue
                features.append(
                    SpecKitFeature(
                        name=feature_dir.name,
                        spec=_read_optional(feature_dir / "spec.md"),
                        plan=_read_optional(feature_dir / "plan.md"),
                        research=_read_optional(feature_dir / "research.md"),
                        data_model=_read_optional(feature_dir / "data-model.md"),
                        contracts=_read_contracts(feature_dir),
                        quickstart=_read_optional(feature_dir / "quickstart.md"),
                    )
                )
        except OSError:
            pass

    return constitution, features


def import_speckit(
    blueprint: str, target: str, source: Path, target_directory: Path
) -> ImportSpecKitResult:
    """Copy Spec Kit files to ``blueprint/sources/``.

    Seeds only root identity files (METADATA.md, README.md). After import,
    ``blueprint/`` holds only ``sources/``; typed spec files are ``plan create``
    outputs and COMPASS.md is an ``analyze`` output.
    """
    source = source.expanduser().resolve()
    if not source.is_dir():
        raise SpecificationError(
            f"Import source must be a directory for --format speckit: {source}"
        )

    # Validates .specify/ exists and reads the project structure.
    _constitution, features = discover_speckit(source)

    target_dir = target_directory / target
    blueprint_dir = target_dir / "blueprint"
    initialized = not (target_dir / "METADATA.md").exists()
    init_specification(blueprint, target_dir, update=True, root_identity_only=True)

    sources_dir = blueprint_dir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    record_import_root(sources_dir, source, "speckit")

    imported: list[Path] = []
    for subdir_name in _SPECKIT_SUBDIRS:
        subdir = source / subdir_name
        if not subdir.is_dir():
            continue
        try:
            for path in sorted(subdir.rglob("*")):
                if not path.is_file():
                    continue
                # Flatten ".specify/" itself so no hidden directory lands in
                # blueprint/sources/; "specs/" keeps its existing prefix.
                rel = (
                    path.relative_to(subdir)
                    if subdir_name == ".specify"
                    else path.relative_to(source)
                )
                destination = sources_dir / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
                imported.append(destination)
        except OSError as exc:
            raise SpecificationError(f"Cannot copy Spec Kit files: {exc}") from exc

    return ImportSpecKitResult(
        blueprint=blueprint,
        target=target,
        blueprint_dir=blueprint_dir,
        source=source,
        features_found=tuple(f.name for f in features),
        imported=tuple(imported),
        initialized=initialized,
    )
