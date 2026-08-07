"""Source refresh and source-driven refit transactions.

The module owns deterministic source comparison and ticket graph mechanics. LLM execution is
limited to producing the prose body of a ticket; filenames, lineage, numbering, dependencies,
hashes, and filesystem commits remain deterministic.
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from drydock.compass_sources import is_compass_source
from drydock.errors import SpecificationError, UsageError
from drydock.lineage import (
    append_version,
    load_or_migrate,
    mark_source_deleted,
    source_release,
    write_lineage,
)
from drydock.source_files import iter_source_files
from drydock.target_git import commit_target

__all__ = [
    "SourceRefitItem",
    "SourceRefitResult",
    "SourceUpdateResult",
    "commit_target",
    "source_refit_target",
    "update_import",
]


@dataclass(frozen=True)
class SourceUpdateResult:
    added: tuple[str, ...]
    changed: tuple[str, ...]
    deleted: tuple[str, ...]
    unchanged: tuple[str, ...]
    pending_versions: int = 0


@dataclass(frozen=True)
class SourceRefitItem:
    blueprint: str
    ticket: Path
    source_files: tuple[str, ...]


@dataclass(frozen=True)
class SourceRefitResult:
    target_dir: Path
    items: tuple[SourceRefitItem, ...]
    changed_sources: tuple[str, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_files(root: Path) -> dict[str, Path]:
    """Visible files under ``root``, keyed by import-relative path.

    Hidden entries are excluded on both sides of the comparison so Drydock's own bookkeeping
    (``.drydock-import``, ``.gitkeep``) never registers as an added or deleted source.
    """
    if root.is_file():
        return {root.name: root}
    if not root.is_dir():
        raise SpecificationError(f"Import source directory not found: {root}")
    return {path.relative_to(root).as_posix(): path for path in sorted(iter_source_files(root))}


def update_import(target_dir: Path, *, at: str = "") -> SourceUpdateResult:
    """Refresh the imported snapshot and record a new source version for everything that moved.

    The Manifest is never opened. Lineage is import-time bookkeeping and ``LINEAGE.json`` owns it,
    which also means ``--update`` works on a Target that has not been planned yet.
    """
    blueprint_dir = target_dir / "blueprint"
    sources_dir = blueprint_dir / "sources"
    at = at or date.today().isoformat()
    lineage = load_or_migrate(target_dir, date=at)
    if not lineage.import_record.root:
        raise SpecificationError(
            f"No recorded import root for {target_dir.name}; "
            f"run: drydock import {target_dir.name} <Source>"
        )
    source_root = Path(lineage.import_record.root).expanduser()
    if not source_root.exists():
        raise SpecificationError(f"Imported source root is unavailable: {source_root}")
    incoming = _source_files(source_root)
    existing = _source_files(sources_dir) if sources_dir.is_dir() else {}

    compass_changed = [
        name
        for name in sorted(set(incoming) & set(existing))
        if is_compass_source(Path(name)) and _sha256(incoming[name]) != _sha256(existing[name])
    ]
    if compass_changed:
        raise SpecificationError(
            "Compass-owned source changed; replan is required before refresh: "
            + ", ".join(compass_changed)
        )

    release = source_release(target_dir)

    # A source removed upstream is a fact, not a blocked refresh. The local copy is retained so
    # a refit ticket can still cite what was withdrawn; the lineage record carries the deletion
    # until refit consumes it.
    deleted = sorted(set(existing) - set(incoming))
    for name in deleted:
        mark_source_deleted(lineage, name)

    added: list[str] = []
    changed: list[str] = []
    unchanged: list[str] = []
    for name, source_path in incoming.items():
        destination = sources_dir / name
        incoming_hash = _sha256(source_path)
        if name not in existing:
            added.append(name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, destination)
        elif _sha256(existing[name]) != incoming_hash:
            changed.append(name)
            shutil.copyfile(source_path, destination)
        else:
            unchanged.append(name)
        if is_compass_source(destination):
            continue
        append_version(lineage, name, hash=incoming_hash, date=at, release=release)

    write_lineage(target_dir, lineage)
    return SourceUpdateResult(
        tuple(added),
        tuple(changed),
        tuple(deleted),
        tuple(unchanged),
        len(lineage.pending_versions()),
    )


def source_refit_target(
    target_dir: Path,
    *,
    runner: Callable[..., object] | None = None,
    log_dir: Path | None = None,
    model: str | None = None,
    llm_provider: str | None = None,
) -> SourceRefitResult:
    """Route pending source versions into change tickets and Manifest stories.

    Deferred: the routing contract is being rewired onto ``LINEAGE.json``. The previous
    implementation resolved a changed source to Blueprints through a Manifest field that nothing
    ever populated, so it could not succeed on any Target.
    """
    raise UsageError(
        "drydock refit --sources is deferred in this build while source routing moves to "
        "LINEAGE.json"
    )
