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

from drydock import change_ticket, lineage_impact, lineage_route, target_git
from drydock.compass_sources import is_compass_source
from drydock.errors import SpecificationError
from drydock.lineage import (
    Requirement,
    append_version,
    consume_version,
    lineage_path,
    load_or_migrate,
    mark_source_deleted,
    render_lineage,
    source_release,
    visible_sources,
    write_lineage,
)
from drydock.manifest import DrydockManifest
from drydock.refit import _resolve_ticket_deps
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
    scope: str
    stories: tuple[str, ...]


@dataclass(frozen=True)
class SourceRefitResult:
    target_dir: Path
    items: tuple[SourceRefitItem, ...]
    consumed_sources: tuple[str, ...]
    downstream: tuple[str, ...] = ()


#: Source-driven refit reads prose. Anything else is analyze's job.
_TEXT_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".rst", ".adoc", ""})


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


def _diff_for(target_dir: Path, rel_path: str, record) -> tuple[str, str | None, str]:
    """The delta a router must read: last consumed commit → newest recorded version."""
    base = record.last_consumed.commit if record.last_consumed else None
    head = record.latest.commit if record.latest else ""
    text = target_git.diff(target_dir, base, f"blueprint/sources/{rel_path}")
    if not text.strip():
        # No repository, or the change is not yet committed. The current file is the delta.
        source_path = target_dir / "blueprint" / "sources" / rel_path
        if source_path.is_file():
            text = source_path.read_text(encoding="utf-8", errors="replace")
    return head, base, text


def source_refit_target(
    target_dir: Path,
    *,
    runner: Callable[..., object] | None = None,
    log_dir: Path | None = None,
    model: str | None = None,
    llm_provider: str | None = None,
) -> SourceRefitResult:
    """Route pending source versions into change tickets and Manifest stories.

    The transaction is all-or-nothing. Every validation gate runs before the first write, and any
    later failure restores the Manifest, the lineage record, and the changes directory, because a
    half-applied refit leaves the graph describing work nobody authorized.
    """
    blueprint_dir = target_dir / "blueprint"
    manifest_path = target_dir / "MANIFEST.md"
    today = date.today().isoformat()

    lineage = load_or_migrate(target_dir, date=today)
    # Sources on disk that lineage has never seen mean the record is missing, not that the Target
    # is up to date. A Target with no sources at all simply has nothing to route.
    unrecorded = [
        path
        for path in visible_sources(blueprint_dir / "sources")
        if path.relative_to(blueprint_dir / "sources").as_posix() not in lineage.sources
    ]
    if unrecorded:
        raise SpecificationError(
            f"No source lineage for {target_dir.name}.\n"
            f"  Run: drydock refit {target_dir.name} --relineage"
        )
    pending = lineage.pending_versions()
    if not pending:
        return SourceRefitResult(target_dir, (), (), ())
    if not manifest_path.is_file():
        raise SpecificationError(
            f"No MANIFEST.md for {target_dir.name}; plan the Target before refitting it.\n"
            f"  Run: drydock plan {target_dir.name}"
        )

    # Source-driven refit reasons about prose. A changed binary or code file has no requirement
    # text to route, and routing a contentless delta would produce a ticket that says nothing.
    non_text = sorted({
        rel_path for rel_path, _ in pending if Path(rel_path).suffix.lower() not in _TEXT_SUFFIXES
    })
    if non_text:
        raise SpecificationError(
            "Source-driven refit operates on markdown and text sources; "
            f"changed: {', '.join(non_text)}\n"
            f"  Run: drydock analyze {target_dir.name}"
        )

    manifest = DrydockManifest.load(manifest_path, compatibility=True)
    recovery = target_git.head_commit(target_dir)
    original_manifest = manifest_path.read_text(encoding="utf-8")
    original_lineage = render_lineage(lineage)
    changes_directory = change_ticket.changes_dir(blueprint_dir)
    original_tickets = {
        path: path.read_text(encoding="utf-8")
        for path in changes_directory.glob("*.md")
        if path.is_file()
    }

    def rollback() -> None:
        manifest_path.write_text(original_manifest, encoding="utf-8", newline="\n")
        lineage_path(target_dir).write_text(original_lineage, encoding="utf-8", newline="\n")
        for path in changes_directory.glob("*.md"):
            if path not in original_tickets:
                path.unlink()
        for path, content in original_tickets.items():
            path.write_text(content, encoding="utf-8", newline="\n")

    diffs = []
    for rel_path, _version in pending:
        head, base, text = _diff_for(target_dir, rel_path, lineage.source(rel_path))
        diffs.append((rel_path, head, base, text))

    proposal = lineage_route.route_requirements(
        diffs,
        manifest,
        blueprint_dir,
        runner=runner,
        log_dir=log_dir,
        model=model,
        llm_provider=llm_provider,
        target=target_dir.name,
    )
    routed = lineage_route.validate_route(proposal, manifest=manifest, blueprint_dir=blueprint_dir)

    existing_facts = lineage_impact.facts_from_manifest(manifest.blocks)
    routed_facts = tuple(
        lineage_impact.StoryFacts(story_id=story.id, implements=story.implements)
        for story in routed
    )
    impact = lineage_impact.analyse(
        routed_facts,
        existing_facts,
        contract_changed=[story.id for story in routed if story.contract_changed],
        deleted_provisions=proposal.deleted_provisions,
    )
    if impact.blocks():
        raise SpecificationError(lineage_impact.blocking_message(impact))

    schedule = lineage_route.assign_schedule(routed, manifest)
    requirement_text = {item.name: item.text for item in proposal.requirements}

    items: list[SourceRefitItem] = []
    try:
        changes_directory.mkdir(parents=True, exist_ok=True)
        for blueprint in sorted({story.implements for story in routed}):
            group = [story for story in routed if story.implements == blueprint]
            number = change_ticket.next_ticket_number(blueprint_dir)
            name = _ticket_name(group, requirement_text)
            filename = change_ticket.ticket_filename(number, name)
            parent_path = blueprint_dir / blueprint
            parent_text = parent_path.read_text(encoding="utf-8") if parent_path.is_file() else None
            # Inherited edges are computed, never routed: a child node takes its parent's
            # dependencies by definition.
            depends_on = _resolve_ticket_deps(blueprint, blueprint_dir)
            scope = "amending" if any(s.scope == "amending" for s in group) else "additive"
            sections = tuple(dict.fromkeys(section for s in group for section in s.sections))
            # A Target without a repository still has provenance worth recording: name the
            # source, and cite the commit only when one exists.
            origins = tuple(
                dict.fromkeys(
                    f"{rel_path}@{head}" if head else rel_path for rel_path, head, _, _ in diffs
                )
            )
            header = change_ticket.TicketHeader(
                version=change_ticket.ticket_version(None, today),
                description=_ticket_description(group),
                amends=blueprint,
                depends_on=tuple(depends_on),
                scope=scope,
                origin=", ".join(origins),
                created=today,
                stories=tuple(story.id for story in group),
            )
            body = change_ticket.TicketBody(
                summary=_ticket_description(group),
                specification="\n\n".join(f"- {story.summary}" for story in group if story.summary),
                amended_sections=sections if scope == "amending" else (),
                downstream_impact=tuple(
                    f"{consumer} (consumes: {provision})"
                    for consumer, provision in impact.downstream
                ),
                requirements=tuple(
                    (story.requirement, requirement_text.get(story.requirement, ""))
                    for story in group
                    if story.requirement
                ),
            )
            ticket_path = changes_directory / filename
            ticket_path.write_text(
                change_ticket.render_ticket(header, name=name, body=body, parent_text=parent_text),
                encoding="utf-8",
                newline="\n",
            )
            for story in group:
                manifest.add(
                    DrydockManifest.create_node(
                        "story",
                        story.id,
                        story.summary.splitlines()[0] if story.summary else story.id,
                        number=max((node.number for node in manifest.blocks), default=0) + 1,
                        state="pending",
                        depends=story.depends,
                        summary=story.summary.replace("\n", " ").strip() or story.id,
                        origin=header.origin,
                        created=today,
                        type="feature",
                        phase=schedule[story.id]["phase"],
                        block=schedule[story.id]["block"],
                        implements=f"{change_ticket.CHANGES_DIRNAME}/{filename}",
                        context=blueprint,
                    )
                )
            items.append(
                SourceRefitItem(
                    blueprint=blueprint,
                    ticket=ticket_path,
                    scope=scope,
                    stories=tuple(story.id for story in group),
                )
            )

        for rel_path, version in pending:
            consume_version(
                lineage,
                rel_path,
                via="refit",
                version=version,
                ticket=items[0].ticket.name if items else None,
                requirements=[
                    Requirement(
                        name=item.name,
                        text=item.text,
                        stories=tuple(s.id for s in routed if s.requirement == item.name),
                    )
                    for item in proposal.requirements
                ],
            )
        manifest.save()
        write_lineage(target_dir, lineage)
    except Exception:
        rollback()
        if recovery:
            print(f"  recover with: git -C {target_dir} reset --hard {recovery}")
        raise

    return SourceRefitResult(
        target_dir,
        tuple(items),
        tuple(rel_path for rel_path, _ in pending),
        tuple(f"{consumer} (consumes: {provision})" for consumer, provision in impact.downstream),
    )


def _ticket_name(stories, requirement_text) -> str:
    for story in stories:
        if story.requirement:
            return story.requirement.replace("-", " ").title()
    return stories[0].id.replace("-", " ").title()


def _ticket_description(stories) -> str:
    return " ".join(story.summary.replace("\n", " ").strip() for story in stories).strip()
