"""Imported-source roles, Blueprint promotion, and build-asset staging."""

from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

from drydock.errors import SpecificationError

# Build-directory subdirectory holding staged build assets. A fixed Drydock constant, never a
# reproduction of the Manifest path, so no `blueprint/` prefix can reach the deliverable.
BUILD_ASSET_DIR = "sources"

# Import bookkeeping files that are never promoted and never staged.
_IMPORT_MARKERS = {".gitkeep", ".drydock-import"}


@dataclass(frozen=True)
class SourceRole:
    path: str
    role: str
    plan_disposition: str
    build_disposition: str


@dataclass(frozen=True)
class StagedAsset:
    """An imported asset placed in the build directory for the build agent to execute."""

    relative_path: str  # build-dir relative, e.g. "sources/spec.txt"
    source: Path  # blueprint/sources/<rel> — the immutable import
    sha256: str


_ROLE_HEADER = re.compile(r"^## Source Roles\s*$", re.M)


def parse_source_roles(analysis_text: str) -> dict[str, SourceRole]:
    """Read the optional Analyze-to-Plan source-role table.

    An analysis without the table yields no rows, so nothing is staged. Staging is opt-in per
    file via the table's build disposition; a legacy Target keeps its existing behavior.
    """
    match = _ROLE_HEADER.search(analysis_text)
    if not match:
        return {}
    rows: dict[str, SourceRole] = {}
    for line in analysis_text[match.end() :].splitlines():
        if line.startswith("## "):
            break
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4 or cells[0].lower() in {"path", "---"} or set(cells[0]) == {"-"}:
            continue
        path, role, plan, build = cells
        if path:
            rows[path.removeprefix("sources/")] = SourceRole(
                path, role.lower(), plan.lower(), build.lower()
            )
    return rows


def source_role_for(path: str, roles: dict[str, SourceRole]) -> SourceRole | None:
    """Resolve an exact or globbed Analyze role for one imported relative path."""
    exact = roles.get(path)
    if exact is not None:
        return exact
    matches = [
        role
        for pattern, role in roles.items()
        if any(character in pattern for character in "*?[") and fnmatchcase(path, pattern)
    ]
    if not matches:
        return None
    return max(matches, key=lambda role: len(role.path))


def promote_imported_sources(
    blueprint_dir: Path, roles: dict[str, SourceRole], target_dir: Path
) -> list[Path]:
    """Project non-Markdown assets byte-for-byte; Markdown remains source provenance.

    Plan authors governed Markdown specifications. Imported non-Markdown files are assets,
    examples, fixtures, tests, or executable resources and are projected one level above
    ``sources/`` without text decoding or newline normalization.
    """
    sources_dir = blueprint_dir / "sources"
    if not sources_dir.is_dir():
        return []
    promoted: list[Path] = []
    for source in sorted(path for path in sources_dir.rglob("*") if path.is_file()):
        rel = source.relative_to(sources_dir).as_posix()
        if source.name in _IMPORT_MARKERS:
            continue
        role = source_role_for(rel, roles)
        if role is not None and role.plan_disposition == "compass":
            _append_compass(target_dir / "COMPASS.md", source)
            continue
        if source.suffix.lower() == ".md":
            continue
        destination = blueprint_dir / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = source.read_bytes()
        if destination.is_file() and destination.read_bytes() == payload:
            promoted.append(destination)
            continue
        with tempfile.NamedTemporaryFile("wb", dir=destination.parent, delete=False) as handle:
            handle.write(payload)
            temporary = Path(handle.name)
        temporary.replace(destination)
        promoted.append(destination)
    return promoted


def _append_compass(compass: Path, source: Path) -> None:
    content = source.read_text(encoding="utf-8").strip()
    if not content:
        return
    digest = hashlib.sha256(content.encode()).hexdigest()
    marker = f"<!-- Drydock author intent sha256={digest} source={source.name} -->"
    existing = compass.read_text(encoding="utf-8") if compass.is_file() else ""
    if marker in existing:
        return
    compass.parent.mkdir(parents=True, exist_ok=True)
    suffix = "\n\n" if existing.strip() else ""
    compass.write_text(
        existing.rstrip() + suffix + marker + "\n\n" + content + "\n", encoding="utf-8"
    )


def _reject_escaping_rel(rel: str) -> str:
    """Reject a staged-asset path that would climb out of the build asset directory.

    Defense in depth: every rel is derived from ``relative_to(blueprint/sources)``, so it cannot
    escape today. The guard keeps that true for future callers.
    """
    parts = PurePosixPath(rel).parts
    if not parts or ".." in parts or PurePosixPath(rel).is_absolute():
        raise SpecificationError(f"Staged build asset escapes the build asset directory: {rel}")
    return rel


def _staged_destination(build_dir: Path, rel: str) -> Path:
    """Resolve a staged asset's destination inside ``<build_dir>/sources/``."""
    return build_dir / BUILD_ASSET_DIR / _reject_escaping_rel(rel)


def declared_build_assets(
    blueprint_dir: Path, roles: dict[str, SourceRole]
) -> tuple[StagedAsset, ...]:
    """Select the imported assets the Analysis marks ``stage``, with their import digests.

    Pure: reads the Blueprint, writes nothing. Staging and score-time verification share this
    so the two can never disagree about which files are part of the kit.
    """
    sources_dir = blueprint_dir / "sources"
    if not sources_dir.is_dir():
        return ()
    assets: list[StagedAsset] = []
    for source in sorted(path for path in sources_dir.rglob("*") if path.is_file()):
        if source.name in _IMPORT_MARKERS:
            continue
        rel = source.relative_to(sources_dir).as_posix()
        role = source_role_for(rel, roles)
        if role is None or role.build_disposition != "stage":
            continue
        # Markdown is prompt material, never a deliverable file.
        if source.suffix == ".md":
            continue
        _reject_escaping_rel(rel)
        assets.append(
            StagedAsset(
                relative_path=f"{BUILD_ASSET_DIR}/{rel}",
                source=source,
                sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            )
        )
    return tuple(assets)


def stage_build_assets(
    blueprint_dir: Path, roles: dict[str, SourceRole], build_dir: Path
) -> tuple[tuple[StagedAsset, ...], tuple[str, ...]]:
    """Place every asset the Analysis marks ``stage`` into ``<build_dir>/sources/``.

    An imported test kit is only useful to the build agent if it exists on disk: acceptance
    checks run with the build directory as their working directory, and a test suite inlined into
    the prompt can be read but not executed. Copies come from ``blueprint/sources/`` — the
    immutable import — so the recorded digest is the digest of what the author imported.

    Returns the staged assets and the relative paths that had to be overwritten because their
    content differed, which is how a build-authored substitute is surfaced.
    """
    staged = declared_build_assets(blueprint_dir, roles)
    replaced: list[str] = []
    for asset in staged:
        destination = build_dir / asset.relative_path
        if destination.is_file():
            if hashlib.sha256(destination.read_bytes()).hexdigest() == asset.sha256:
                continue
            replaced.append(asset.relative_path)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(asset.source, destination)
    return staged, tuple(replaced)


def verify_staged_assets(
    staged: tuple[StagedAsset, ...], build_dir: Path, *, restore: bool = True
) -> tuple[str, ...]:
    """Return the staged assets that no longer match their import, restoring them by default.

    A build agent that rewrites or truncates its own test kit would otherwise grade itself
    against a test suite of its own making. Scoring passes ``restore=False``: at that point the
    artifact under judgment is fixed, so tampering is reported rather than silently repaired.
    """
    tampered: list[str] = []
    for asset in staged:
        destination = build_dir / asset.relative_path
        if destination.is_file():
            if hashlib.sha256(destination.read_bytes()).hexdigest() == asset.sha256:
                continue
        tampered.append(asset.relative_path)
        if restore and asset.source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(asset.source, destination)
    return tuple(tampered)


def tampered_build_assets(
    target_dir: Path, blueprint_dir: Path, build_dir: Path
) -> tuple[str, ...]:
    """Report staged assets in ``build_dir`` that no longer match their import.

    Reads the declaration from the Target's ANALYSIS.md so scoring can check the kit without
    the build run's in-memory state. Reports only; never repairs.
    """
    analysis = target_dir / "ANALYSIS.md"
    if not analysis.is_file():
        return ()
    roles = parse_source_roles(analysis.read_text(encoding="utf-8"))
    declared = declared_build_assets(blueprint_dir, roles)
    return verify_staged_assets(declared, build_dir, restore=False)
