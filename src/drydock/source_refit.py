"""Source refresh and source-driven refit transactions.

The module owns deterministic source comparison and ticket graph mechanics. LLM execution is
limited to producing the prose body of a ticket; filenames, lineage, numbering, dependencies,
hashes, and filesystem commits remain deterministic.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from drydock.compass_sources import is_compass_source
from drydock.errors import SpecificationError
from drydock.llm import run_prompt
from drydock.manifest import DrydockManifest, StoryNode
from drydock.prompts import load_prompt


@dataclass(frozen=True)
class SourceUpdateResult:
    added: tuple[str, ...]
    changed: tuple[str, ...]
    deleted: tuple[str, ...]
    unchanged: tuple[str, ...]


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


class SourceDeletionDecision(SpecificationError):
    """A full-root import found a source deletion requiring Commander direction."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_files(root: Path) -> dict[str, Path]:
    if root.is_file():
        return {root.name: root}
    if not root.is_dir():
        raise SpecificationError(f"Import source directory not found: {root}")
    return {
        path.relative_to(root).as_posix(): path
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _import_metadata(sources_dir: Path) -> tuple[Path, str]:
    metadata = sources_dir / ".drydock-import"
    if not metadata.is_file():
        raise SpecificationError(f"No imported source metadata found: {metadata}")
    values: dict[str, str] = {}
    for line in metadata.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip()] = value.strip()
    source = Path(values.get("source", "")).expanduser()
    if not source.exists():
        raise SpecificationError(f"Imported source root is unavailable: {source}")
    return source, values.get("format", "")


def update_import(target_dir: Path) -> SourceUpdateResult:
    """Refresh an ordinary imported directory and record per-file hashes in the Manifest."""
    blueprint_dir = target_dir / "blueprint"
    sources_dir = blueprint_dir / "sources"
    source_root, _format = _import_metadata(sources_dir)
    incoming = _source_files(source_root)
    existing = {
        path.relative_to(sources_dir).as_posix(): path
        for path in sorted(sources_dir.rglob("*"))
        if path.is_file() and path.name != ".drydock-import"
    }
    manifest_path = target_dir / "MANIFEST.md"
    manifest = (
        DrydockManifest.load(manifest_path, compatibility=True) if manifest_path.is_file() else None
    )
    lineage = dict(manifest.source_lineage) if manifest else {}
    file_records = dict(lineage.get("files", {})) if isinstance(lineage.get("files"), dict) else {}

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

    deleted = sorted(set(existing) - set(incoming))
    if deleted:
        raise SourceDeletionDecision(
            "Imported source deletion detected: " + ", ".join(deleted) + ". "
            "Choose whether to keep or remove the affected feature, then rerun refit."
        )

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
        record = (
            dict(file_records.get(name, {})) if isinstance(file_records.get(name), dict) else {}
        )
        if name in added or name in changed:
            record["pending_change"] = True
            record["pending_hash"] = incoming_hash
        else:
            record["hash"] = incoming_hash
        file_records[name] = record

    if manifest is not None:
        lineage["version"] = 1
        lineage["files"] = file_records
        manifest.set_source_lineage(lineage)
        manifest.save()
    return SourceUpdateResult(tuple(added), tuple(changed), tuple(deleted), tuple(unchanged))


def persist_source_lineage(manifest_path: Path, blueprint_dir: Path) -> None:
    """Persist deterministic source hashes and validated source-to-Blueprint relationships.

    Planning supplies explicit citations when available. The fallback matcher only fills missing
    relationships when a Blueprint text names the imported relative path or basename; it never
    replaces an existing relationship.
    """
    manifest = DrydockManifest.load(manifest_path, compatibility=True)
    sources_dir = blueprint_dir / "sources"
    records = dict(manifest.source_lineage.get("files", {}))
    blueprints = {
        path.name: path
        for path in blueprint_dir.glob("*.md")
        if path.name not in {"COMPASS.md", "MANIFEST.md"} and not path.name.endswith("_compact.md")
    }
    for source_path in sorted(sources_dir.rglob("*")):
        if not source_path.is_file() or source_path.name == ".drydock-import":
            continue
        if is_compass_source(source_path):
            continue
        relative = source_path.relative_to(sources_dir).as_posix()
        record = dict(records.get(relative, {})) if isinstance(records.get(relative), dict) else {}
        record["hash"] = _sha256(source_path)
        if not record.get("blueprints"):
            matches: list[str] = []
            for name, blueprint in blueprints.items():
                try:
                    text = blueprint.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if relative in text or Path(relative).name in text:
                    matches.append(name)
            if matches:
                record["blueprints"] = matches
        records[relative] = record
    manifest.source_lineage["version"] = 1
    manifest.source_lineage["files"] = records
    manifest.set_source_lineage(manifest.source_lineage)
    manifest.save()


def commit_target(target_dir: Path, message: str) -> None:
    """Commit a Target repository when one exists; never commit the parent workspace."""
    if not (target_dir / ".git").exists():
        return
    status = subprocess.run(
        ["git", "status", "--short"], cwd=target_dir, capture_output=True, text=True, check=False
    )
    if status.returncode != 0 or not status.stdout.strip():
        return
    subprocess.run(["git", "add", "-A"], cwd=target_dir, check=True, timeout=15)
    subprocess.run(["git", "commit", "-m", message], cwd=target_dir, check=True, timeout=30)


def _safe_blueprint_name(path: str) -> str:
    return Path(path).stem


def _lineage_candidates(manifest: DrydockManifest, source: str) -> tuple[str, ...]:
    record = manifest.source_lineage.get("files", {})
    if not isinstance(record, dict):
        return ()
    item = record.get(source, {})
    if not isinstance(item, dict):
        return ()
    blueprints = item.get("blueprints", item.get("blueprint", ()))
    if isinstance(blueprints, str):
        return (blueprints,)
    if isinstance(blueprints, list):
        return tuple(str(value) for value in blueprints)
    return ()


def _ticket_number(blueprint_dir: Path, blueprint_name: str) -> int:
    pattern = re.compile(re.escape(blueprint_name) + r"_refit_(\d+)\.md$")
    numbers = [
        int(match.group(1))
        for path in blueprint_dir.glob(f"{blueprint_name}_refit_*.md")
        if (match := pattern.match(path.name))
    ]
    return max(numbers, default=0) + 1


def _append_manifest_story(
    manifest: DrydockManifest, blueprint: str, ticket_name: str, number: int
) -> None:
    blueprint_stem = Path(blueprint).stem
    prior = []
    for node in manifest.blocks:
        if node.block_type != "story":
            continue
        implements = node.fields.get("implements", "")
        values = implements if isinstance(implements, tuple) else (str(implements),)
        if any(
            value == blueprint or value.startswith(f"{blueprint_stem}_refit_") for value in values
        ):
            prior.append(node)
    depends = prior[-1].block_id if prior else ""
    node_id = f"{Path(ticket_name).stem.lower().replace('-', '-')}-{number}"
    story_number = max((node.number for node in manifest.blocks), default=0) + 1
    lines = [
        f"## story {story_number}: Refit {blueprint} {number}",
        f"id: {node_id}",
        f"summary: Apply refit specification for {blueprint}.",
        "type: feature",
        f"implements: {ticket_name}",
        *([f"depends: {depends}"] if depends else []),
        "state: pending",
    ]
    manifest.blocks.append(
        StoryNode(
            block_type="story",
            number=story_number,
            name=f"Refit {blueprint} {number}",
            block_id=node_id,
            state="pending",
            depends=(depends,) if depends else (),
            fields={
                "id": node_id,
                "summary": f"Apply refit specification for {blueprint}.",
                "type": "feature",
                "implements": ticket_name,
                "depends": (depends,) if depends else (),
                "state": "pending",
            },
            lines=lines,
            line=0,
            dirty=False,
        )
    )


def _render_ticket(blueprint: str, number: int, prior_ticket: str | None, body: str) -> str:
    supersedes = blueprint if prior_ticket is None else f"{blueprint}, {prior_ticket}"
    return (
        f"# REFIT: {Path(blueprint).stem} {number}\n\n"
        "| Field | Value |\n|-------|-------|\n"
        f"| Blueprint | {blueprint} |\n"
        f"| Change Ticket | {number} |\n"
        f"| Supersedes | {supersedes} |\n"
        "| Conflict Authority | This ticket governs in case of conflict. |\n\n"
        "## Specification\n\n"
        f"{body.strip()}\n"
    )


def source_refit_target(
    target_dir: Path,
    *,
    runner: Callable[..., object] | None = None,
    log_dir: Path | None = None,
    model: str | None = None,
    llm_provider: str | None = None,
) -> SourceRefitResult:
    """Author one ordered ticket per affected Blueprint from the imported source delta."""
    manifest_path = target_dir / "MANIFEST.md"
    manifest = DrydockManifest.load(manifest_path, compatibility=True)
    original_manifest = manifest_path.read_text(encoding="utf-8")
    blueprint_dir = target_dir / "blueprint"
    original_tickets = {
        path: path.read_text(encoding="utf-8")
        for path in blueprint_dir.glob("*_refit_*.md")
        if path.is_file()
    }

    def rollback() -> None:
        manifest_path.write_text(original_manifest, encoding="utf-8", newline="\n")
        for path in blueprint_dir.glob("*_refit_*.md"):
            if path not in original_tickets:
                path.unlink()
        for path, content in original_tickets.items():
            path.write_text(content, encoding="utf-8", newline="\n")

    records = manifest.source_lineage.get("files", {})
    if not isinstance(records, dict):
        raise SpecificationError("Manifest has no source lineage; run drydock plan first")
    changed = [
        name
        for name, value in records.items()
        if isinstance(value, dict) and value.get("pending_change")
    ]
    if not changed:
        return SourceRefitResult(target_dir, (), ())
    prompt = load_prompt("refit_sources")
    run = runner if runner is not None else run_prompt
    grouped: dict[str, list[str]] = {}
    for source in changed:
        for blueprint in _lineage_candidates(manifest, source):
            if not (blueprint_dir / blueprint).is_file():
                raise SpecificationError(f"Source lineage names a missing Blueprint: {blueprint}")
            grouped.setdefault(blueprint, []).append(source)
    unmapped = [
        source for source in changed if not any(source in values for values in grouped.values())
    ]
    if unmapped:
        raise SpecificationError(
            "Changed source has no lineage candidate Blueprint: " + ", ".join(unmapped)
        )
    items: list[SourceRefitItem] = []
    for blueprint, sources in sorted(grouped.items()):
        blueprint_name = _safe_blueprint_name(blueprint)
        number = _ticket_number(blueprint_dir, blueprint_name)
        ticket_name = f"{blueprint_name}_refit_{number}.md"
        source_text = "\n\n".join(
            f"=== {name} ===\n{(blueprint_dir / 'sources' / name).read_text(encoding='utf-8')}\n=== END {name} ==="
            for name in sources
        )
        assembled = f"{prompt.body}\n\n# Refit job\n- BLUEPRINT: {blueprint}\n- DATE: {date.today().isoformat()}\n- SOURCES: {', '.join(sources)}\n\n{source_text}\n"
        try:
            result = run(
                assembled,
                blueprint_dir,
                llm=llm_provider,
                model=model or prompt.model,
                command_name="refit_sources",
                parameters={"blueprint": blueprint, "sources": sources},
                log_dir=log_dir,
                target=target_dir.name,
            )
        except Exception:
            rollback()
            raise
        if not getattr(result, "ok", False) or not getattr(result, "text", "").strip():
            rollback()
            raise SpecificationError(f"Source refit authoring failed for {blueprint}")
        body = str(result.text).strip()
        match = re.search(
            r"===\s*(?:blueprint/)?" + re.escape(ticket_name) + r"\s*===\n(.*?)\n===\s*END",
            body,
            re.DOTALL,
        )
        if match:
            body = match.group(1).strip()
        ticket = blueprint_dir / ticket_name
        prior_ticket = f"{blueprint_name}_refit_{number - 1}.md" if number > 1 else None
        ticket.write_text(
            _render_ticket(blueprint, number, prior_ticket, body),
            encoding="utf-8",
            newline="\n",
        )
        _append_manifest_story(manifest, blueprint, ticket_name, number)
        items.append(SourceRefitItem(blueprint, ticket, tuple(sources)))
    for source in changed:
        value = dict(records[source])
        value.pop("pending_change", None)
        if value.get("pending_hash"):
            value["hash"] = value.pop("pending_hash")
        records[source] = value
    manifest.source_lineage["files"] = records
    manifest.set_source_lineage(manifest.source_lineage)
    try:
        manifest.save()
    except Exception:
        rollback()
        raise
    return SourceRefitResult(target_dir, tuple(items), tuple(changed))
