"""``drydock refit --relineage`` — rebuild ``LINEAGE.json`` from a Target's git history.

A Target planned before lineage existed has no record of which source version produced which
story, and the routing path cannot run without one. The reconstruction splits cleanly into a
deterministic half and a judgement half.

The deterministic half is git. ``blueprint/sources/`` lives inside the Target repository, so every
version of every source is recoverable with its commit and date, in order, with no inference. That
is replayed into version records exactly as it happened.

The judgement half is attribution: which stories a given source produced. That is a closed-set
matching problem against the Manifest, handled by :mod:`drydock.lineage_attribution`, and it is
allowed to leave stories unattached — planning legitimately invents foundational work no sentence
asked for.

A Target repository is required. Without one there is no history to replay, and inventing a single
synthetic version would silently claim provenance the command cannot actually establish.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path

from drydock import target_git
from drydock.errors import SpecificationError
from drydock.lineage import (
    Lineage,
    Version,
    content_hash,
    load_or_migrate,
    source_release,
    visible_sources,
    write_lineage,
)
from drydock.lineage_attribution import attribute_source
from drydock.manifest import DrydockManifest


@dataclass(frozen=True)
class RelineageSource:
    path: str
    versions: int
    attributed: int


@dataclass(frozen=True)
class RelineageResult:
    target_dir: Path
    sources: tuple[RelineageSource, ...]
    unattached: tuple[str, ...]
    warnings: tuple[str, ...] = ()


def require_target_repo(target_dir: Path) -> None:
    if not target_git.is_repo(target_dir):
        raise SpecificationError(
            f"No git repository in {target_dir}.\n"
            "  --relineage replays source history from the Target repository.\n"
            f"  Initialize one with: git -C {target_dir} init\n"
            "  (drydock init creates one only when the workspace is a repository "
            "that ignores targets/.)"
        )


def replay_source(
    versions: list[tuple[target_git.SourceVersion, str]],
    *,
    release: str = "",
    prior: Mapping[str, Version] | None = None,
) -> list[Version]:
    """Fold ``(commit, text)`` pairs into version records, oldest first. Pure — no filesystem.

    Consecutive commits that did not change the content collapse into one version: git records a
    commit per touch, but lineage records a version per distinct state.

    ``prior`` maps content hash to the version the existing lineage already holds for this source.
    A version it records as pending stays pending. Being committed proves only that the content
    existed, never that a command consumed it: ``import --update`` commits the snapshot it imports,
    so a source version can sit in git history having produced no story at all. Relineage repairs
    provenance it can establish, and must not overwrite unconsumed work with a claim it was done.
    """
    known = prior or {}
    records: list[Version] = []
    for source_version, text in versions:
        digest = content_hash(text)
        if records and records[-1].hash == digest:
            continue
        earlier = known.get(digest)
        unconsumed = earlier is not None and earlier.pending
        records.append(
            Version(
                hash=digest,
                date=source_version.date,
                commit=source_version.commit,
                release=release,
                state="pending" if unconsumed else "consumed",
                via=None if unconsumed else "relineage",
            )
        )
    return records


def relineage_target(
    target_dir: Path,
    *,
    runner: Callable[..., object] | None = None,
    log_dir: Path | None = None,
    model: str | None = None,
    llm_provider: str | None = None,
) -> RelineageResult:
    """Rebuild lineage for a Target, then attribute its existing stories to requirements."""
    require_target_repo(target_dir)
    blueprint_dir = target_dir / "blueprint"
    sources_dir = blueprint_dir / "sources"
    manifest_path = target_dir / "MANIFEST.md"
    if not manifest_path.is_file():
        raise SpecificationError(
            f"No MANIFEST.md for {target_dir.name}; there are no stories to attribute.\n"
            f"  Run: drydock plan {target_dir.name}"
        )

    manifest = DrydockManifest.load(manifest_path, compatibility=True)
    today = _date.today().isoformat()
    lineage = load_or_migrate(target_dir, date=today)
    release = source_release(target_dir)

    # Sources git has ever recorded, plus anything on disk git has not seen yet.
    tracked = list(target_git.tracked_sources(target_dir))
    on_disk = [path.relative_to(sources_dir).as_posix() for path in visible_sources(sources_dir)]
    paths = sorted(dict.fromkeys([*tracked, *on_disk]))

    rebuilt = Lineage(import_record=lineage.import_record)
    reports: list[RelineageSource] = []
    warnings: list[str] = []
    attributed_stories: set[str] = set()

    for rel_path in paths:
        history: list[tuple[target_git.SourceVersion, str]] = []
        for source_version in target_git.file_versions(target_dir, f"blueprint/sources/{rel_path}"):
            text = target_git.show(
                target_dir, source_version.commit, f"blueprint/sources/{rel_path}"
            )
            if text is not None:
                history.append((source_version, text))
        prior_record = lineage.sources.get(rel_path)
        prior = {version.hash: version for version in prior_record.versions} if prior_record else {}
        records = replay_source(history, release=release, prior=prior)

        current = sources_dir / rel_path
        current_text = ""
        if current.is_file():
            current_text = current.read_text(encoding="utf-8", errors="replace")
            digest = content_hash(current_text)
            if not records or records[-1].hash != digest:
                # Uncommitted working-tree content is a real version; it is simply not yet
                # attributable to a commit.
                records.append(
                    Version(hash=digest, date=today, commit=None, release=release, state="pending")
                )

        if not records:
            continue

        attribution = None
        if current_text.strip():
            attribution = attribute_source(
                rel_path,
                current_text,
                manifest,
                working_directory=blueprint_dir,
                runner=runner,
                log_dir=log_dir,
                model=model,
                llm_provider=llm_provider,
                target=target_dir.name,
            )
            warnings.extend(attribution.warnings)
            for requirement in attribution.requirements:
                attributed_stories.update(requirement.stories)
            # Attribution describes the source as it stands, so it belongs to the newest version.
            records[-1].requirements = attribution.requirements

        record = rebuilt.source(rel_path)
        record.versions = records
        if not current.is_file():
            record.state = "deleted"
        reports.append(
            RelineageSource(
                path=rel_path,
                versions=len(records),
                attributed=len(attribution.requirements) if attribution else 0,
            )
        )

    write_lineage(target_dir, rebuilt)

    # A story no requirement claims is foundational work planning invented. Recording that is the
    # point; failing on it would make the command unusable on the Targets it exists to repair.
    unattached = tuple(
        node.block_id
        for node in manifest.blocks
        if node.block_type == "story" and node.block_id not in attributed_stories
    )
    if unattached:
        for node in manifest.blocks:
            if node.block_type == "story" and node.block_id in unattached:
                if not node.fields.get("origin"):
                    node.fields["origin"] = "plan"
                    node.dirty = True
        manifest.save()

    return RelineageResult(target_dir, tuple(reports), unattached, tuple(warnings))
