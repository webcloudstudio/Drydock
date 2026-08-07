"""``LINEAGE.json`` — the record of which source version produced which work.

Drydock builds software from imported specifications, so the chain from a Commander's sentence to
the story that implemented it has to be recorded rather than inferred. This module owns that
record.

The unit of lineage is a **source version**, not a file and not a parsed fragment of prose. Import
performs no analysis: it copies the source and lets git record it, so a version is exactly a
`(content hash, commit)` pair and the delta between two versions is a git diff. What a diff *means*
— which requirements it contains and which stories they become — is decided later, by the router,
and written back here once decided. Nothing guesses at import time.

A version stays ``pending`` until ``plan`` or ``refit`` consumes it. Consumption appends the
requirements the consumer found and the stories they became; it never rewrites or discards an
earlier version, which is what makes the history auditable. Requirements point at Manifest story
ids and never at Blueprints: stories already carry ``implements:``, so recording a Blueprint here
would be a second copy of a mapping that can then disagree with the first.

``LINEAGE.json`` lives at the Target root beside ``DECISIONS.json`` and follows the same
conventions: machine-owned, never hand-edited, two-space JSON, tolerant load. It is created at
import, before ``MANIFEST.md`` exists, which is why it cannot live in the Manifest.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from drydock.compass_sources import is_compass_source
from drydock.source_files import iter_source_files

LINEAGE_FILENAME = "LINEAGE.json"
LINEAGE_VERSION = 1

#: A version is unconsumed until a command records what it became.
VERSION_STATES = frozenset({"pending", "consumed"})
#: Which command consumed a version.
VIA_KINDS = frozenset({"plan", "refit", "relineage"})
#: A source withdrawn upstream keeps its record so a ticket can still cite what was removed.
SOURCE_STATES = frozenset({"current", "deleted"})

_LEGACY_IMPORT_MARKER = ".drydock-import"


@dataclass(frozen=True)
class Requirement:
    """A named requirement the router found in a source version, and what it became."""

    name: str
    text: str
    stories: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "text": self.text, "stories": list(self.stories)}

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> Requirement:
        return cls(
            name=str(raw.get("name", "")),
            text=str(raw.get("text", "")),
            stories=tuple(str(item) for item in _sequence(raw.get("stories"))),
        )


@dataclass
class Version:
    """One recorded state of a source file."""

    hash: str
    date: str
    commit: str | None = None
    release: str = ""
    state: str = "pending"
    via: str | None = None
    ticket: str | None = None
    requirements: tuple[Requirement, ...] = ()

    @property
    def pending(self) -> bool:
        return self.state == "pending"

    def to_dict(self) -> dict[str, object]:
        return {
            "commit": self.commit,
            "date": self.date,
            "hash": self.hash,
            "release": self.release,
            "state": self.state,
            "via": self.via,
            "ticket": self.ticket,
            "requirements": [item.to_dict() for item in self.requirements],
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> Version:
        commit = raw.get("commit")
        via = raw.get("via")
        ticket = raw.get("ticket")
        state = str(raw.get("state", "pending"))
        return cls(
            hash=str(raw.get("hash", "")),
            date=str(raw.get("date", "")),
            commit=str(commit) if commit else None,
            release=str(raw.get("release", "")),
            state=state if state in VERSION_STATES else "pending",
            via=str(via) if via else None,
            ticket=str(ticket) if ticket else None,
            requirements=tuple(
                Requirement.from_dict(item)
                for item in _sequence(raw.get("requirements"))
                if isinstance(item, Mapping)
            ),
        )


@dataclass
class SourceRecord:
    """The full recorded history of one imported source file."""

    state: str = "current"
    versions: list[Version] = field(default_factory=list)

    @property
    def latest(self) -> Version | None:
        return self.versions[-1] if self.versions else None

    @property
    def last_consumed(self) -> Version | None:
        for version in reversed(self.versions):
            if version.state == "consumed":
                return version
        return None

    def pending(self) -> tuple[Version, ...]:
        return tuple(version for version in self.versions if version.pending)

    def to_dict(self) -> dict[str, object]:
        return {"state": self.state, "versions": [item.to_dict() for item in self.versions]}

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> SourceRecord:
        state = str(raw.get("state", "current"))
        return cls(
            state=state if state in SOURCE_STATES else "current",
            versions=[
                Version.from_dict(item)
                for item in _sequence(raw.get("versions"))
                if isinstance(item, Mapping)
            ],
        )


@dataclass
class ImportRecord:
    """Where ``drydock import --update`` re-reads from."""

    root: str | None = None
    format: str = ""

    def to_dict(self) -> dict[str, object]:
        return {"root": self.root, "format": self.format}

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> ImportRecord:
        root = raw.get("root")
        return cls(root=str(root) if root else None, format=str(raw.get("format", "")))


@dataclass
class Lineage:
    version: int = LINEAGE_VERSION
    import_record: ImportRecord = field(default_factory=ImportRecord)
    sources: dict[str, SourceRecord] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not self.sources and self.import_record.root is None

    def source(self, rel_path: str) -> SourceRecord:
        return self.sources.setdefault(rel_path, SourceRecord())

    def pending_versions(self) -> tuple[tuple[str, Version], ...]:
        return tuple(
            (rel_path, version)
            for rel_path, record in sorted(self.sources.items())
            for version in record.pending()
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "import": self.import_record.to_dict(),
            "sources": {path: record.to_dict() for path, record in sorted(self.sources.items())},
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> Lineage:
        sources = raw.get("sources")
        return cls(
            version=int(raw.get("version", LINEAGE_VERSION) or LINEAGE_VERSION),
            import_record=ImportRecord.from_dict(
                raw.get("import") if isinstance(raw.get("import"), Mapping) else {}
            ),
            sources={
                str(path): SourceRecord.from_dict(record)
                for path, record in (sources.items() if isinstance(sources, Mapping) else ())
                if isinstance(record, Mapping)
            },
        )


def _sequence(value: object) -> Sequence[object]:
    return value if isinstance(value, list) else ()


def content_hash(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def lineage_path(target_dir: Path) -> Path:
    return target_dir / LINEAGE_FILENAME


def render_lineage(lineage: Lineage) -> str:
    return json.dumps(lineage.to_dict(), indent=2) + "\n"


def load_lineage(target_dir: Path) -> Lineage:
    """Read ``LINEAGE.json``. A missing or corrupt file yields an empty record, never an error.

    Lineage is bookkeeping: a damaged file must not block an import or a build. ``--relineage``
    rebuilds it from git.
    """
    path = lineage_path(target_dir)
    if not path.is_file():
        return Lineage()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Lineage()
    if not isinstance(raw, Mapping):
        return Lineage()
    return Lineage.from_dict(raw)


def write_lineage(target_dir: Path, lineage: Lineage) -> Path:
    """Write ``LINEAGE.json`` atomically so a crash cannot truncate the record."""
    path = lineage_path(target_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
    ) as handle:
        handle.write(render_lineage(lineage))
        temporary = Path(handle.name)
    temporary.replace(path)
    return path


def source_release(target_dir: Path) -> str:
    """The Target's release identifier, recorded against each version."""
    from drydock.metadata import load_metadata_vars

    try:
        return load_metadata_vars(target_dir).get("version", "") or ""
    except (OSError, ValueError):
        return ""


def record_import_root(target_dir: Path, source: Path, import_format: str) -> Lineage:
    """Record the root ``--update`` refreshes from, never narrowing a wider prior root.

    Importing a single file out of a directory that was already imported must not rewrite the
    recorded root to that one file; ``--update`` would then report every sibling as deleted.
    """
    lineage = load_or_migrate(target_dir)
    resolved = source.expanduser()
    recorded = lineage.import_record.root
    if recorded:
        prior = Path(recorded).expanduser()
        if prior.is_dir() and prior in resolved.resolve().parents:
            resolved = prior
            import_format = lineage.import_record.format or import_format
    lineage.import_record = ImportRecord(root=str(resolved), format=import_format)
    write_lineage(target_dir, lineage)
    return lineage


def append_version(
    lineage: Lineage,
    rel_path: str,
    *,
    hash: str,
    date: str,
    release: str = "",
    commit: str | None = None,
) -> Version | None:
    """Append a version unless the newest recorded one already has this content.

    Re-importing unchanged material is routine and must not accumulate duplicate versions.
    """
    record = lineage.source(rel_path)
    record.state = "current"
    latest = record.latest
    if latest is not None and latest.hash == hash:
        return None
    version = Version(hash=hash, date=date, commit=commit, release=release)
    record.versions.append(version)
    return version


def mark_source_deleted(lineage: Lineage, rel_path: str) -> SourceRecord:
    """Flag a source withdrawn upstream while keeping every recorded version."""
    record = lineage.source(rel_path)
    record.state = "deleted"
    return record


def stamp_pending_commits(lineage: Lineage, commit: str) -> int:
    """Fill in the commit sha for versions recorded before the commit existed.

    An import writes its version records and *then* commits, so the sha is unknown at write time.
    The caller folds this stamp into the same commit with ``target_git.amend_head``.
    """
    stamped = 0
    for record in lineage.sources.values():
        for version in record.versions:
            if version.commit is None:
                version.commit = commit
                stamped += 1
    return stamped


def consume_version(
    lineage: Lineage,
    rel_path: str,
    *,
    via: str,
    version: Version | None = None,
    ticket: str | None = None,
    requirements: Iterable[Requirement] = (),
) -> Version | None:
    """Record what a pending version became. Never rewrites an already consumed version."""
    record = lineage.source(rel_path)
    target = version if version is not None else next(iter(record.pending()), None)
    if target is None:
        return None
    target.state = "consumed"
    target.via = via
    target.ticket = ticket
    target.requirements = tuple(requirements)
    return target


def attach_stories(version: Version, attribution: Mapping[str, Sequence[str]]) -> None:
    """Attach story ids to already recorded requirements, keyed by requirement name."""
    version.requirements = tuple(
        Requirement(
            name=item.name,
            text=item.text,
            stories=tuple(dict.fromkeys((*item.stories, *attribution.get(item.name, ())))),
        )
        for item in version.requirements
    )


def visible_sources(sources_dir: Path) -> tuple[Path, ...]:
    """Every non-hidden, non-Compass source file. Compass material is governed separately."""
    if not sources_dir.is_dir():
        return ()
    return tuple(
        path for path in sorted(iter_source_files(sources_dir)) if not is_compass_source(path)
    )


def seed_from_disk(
    lineage: Lineage,
    sources_dir: Path,
    *,
    date: str,
    release: str = "",
    consumed_by: str | None = None,
) -> tuple[str, ...]:
    """Record a version for every source currently on disk that is not already recorded.

    Seeded versions are pending unless the caller can name the command that already consumed
    them. Only migration can: an existing planned Target demonstrably ran ``plan`` over its
    sources, so backdating a ``plan`` entry is a statement of fact. A fresh import has no such
    evidence and must leave the work visible.
    """
    seeded: list[str] = []
    for path in visible_sources(sources_dir):
        rel_path = path.relative_to(sources_dir).as_posix()
        version = append_version(
            lineage, rel_path, hash=file_hash(path), date=date, release=release
        )
        if version is None:
            continue
        if consumed_by:
            version.state = "consumed"
            version.via = consumed_by
        seeded.append(rel_path)
    return tuple(seeded)


def consume_after_plan(
    target_dir: Path,
    sources_dir: Path,
    *,
    date: str,
    commit: str | None = None,
    attributor: Callable[[str, str], object] | None = None,
) -> tuple[Lineage, tuple[str, ...]]:
    """Record that ``plan`` consumed every pending source version, and what it produced.

    Planning is the one command that reads the whole source and decomposes it, so it is the right
    place to capture the requirement-to-story link while the reasoning is still available. The
    attribution call is optional: without it the version is still recorded as consumed, just
    without provenance, and ``refit --relineage`` can fill it in later.
    """
    lineage = load_or_migrate(target_dir, date=date)
    release = source_release(target_dir)
    warnings: list[str] = []
    for path in visible_sources(sources_dir):
        rel_path = path.relative_to(sources_dir).as_posix()
        append_version(lineage, rel_path, hash=file_hash(path), date=date, release=release)
        record = lineage.source(rel_path)
        pending = record.pending()
        if not pending:
            continue
        requirements: tuple[Requirement, ...] = ()
        if attributor is not None:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            attribution = attributor(rel_path, text)
            requirements = tuple(getattr(attribution, "requirements", ()) or ())
            warnings.extend(getattr(attribution, "warnings", ()) or ())
        for version in pending:
            version.state = "consumed"
            version.via = "plan"
            if commit and version.commit is None:
                version.commit = commit
            if requirements and version is pending[-1]:
                version.requirements = requirements
    write_lineage(target_dir, lineage)
    return lineage, tuple(warnings)


def record_initial_snapshot(target_dir: Path, sources_dir: Path, *, date: str = "") -> Lineage:
    """Record a version for everything an import just copied in.

    Every imported version starts pending. On a first import ``plan`` consumes it; on an import
    into a planned Target ``refit`` does. Import itself never claims work was consumed.
    """
    if not date:
        from datetime import date as _date

        date = _date.today().isoformat()
    lineage = load_or_migrate(target_dir, date=date)
    seed_from_disk(lineage, sources_dir, date=date, release=source_release(target_dir))
    write_lineage(target_dir, lineage)
    return lineage


def _read_legacy_marker(sources_dir: Path) -> ImportRecord | None:
    marker = sources_dir / _LEGACY_IMPORT_MARKER
    if not marker.is_file():
        return None
    values: dict[str, str] = {}
    try:
        text = marker.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip()] = value.strip()
    root = values.get("source", "").strip()
    return ImportRecord(root=root or None, format=values.get("format", ""))


def migrate_legacy(target_dir: Path, *, date: str) -> tuple[Lineage, tuple[str, ...]]:
    """Build a ``LINEAGE.json`` for a Target that predates it.

    Two legacy stores are absorbed. ``blueprint/sources/.drydock-import`` held the import root, and
    the Manifest's ``source_lineage:`` field held per-file hashes plus a ``blueprints`` list. That
    list is **read and discarded**: it was populated only by a filename-substring match that no
    authored Blueprint could ever satisfy, so it was empty in practice and wrong in principle —
    lineage points at stories now. Pending flags survive, because unconsumed work must not be lost.
    """
    from drydock.manifest import DrydockManifest

    sources_dir = target_dir / "blueprint" / "sources"
    lineage = Lineage()
    notices: list[str] = []

    marker = _read_legacy_marker(sources_dir)
    if marker is not None:
        lineage.import_record = marker
        notices.append(f"absorbed {_LEGACY_IMPORT_MARKER} into {LINEAGE_FILENAME}")

    legacy_pending: set[str] = set()
    legacy_deleted: set[str] = set()
    manifest_path = target_dir / "MANIFEST.md"
    if manifest_path.is_file():
        try:
            manifest = DrydockManifest.load(manifest_path, compatibility=True)
        except Exception:  # noqa: BLE001 - migration must never block the calling command
            manifest = None
        if manifest is not None:
            records = manifest.source_lineage.get("files", {})
            if isinstance(records, dict):
                discarded = 0
                for name, value in records.items():
                    if not isinstance(value, dict):
                        continue
                    if value.get("pending_change"):
                        legacy_pending.add(str(name))
                    if value.get("pending_delete"):
                        legacy_deleted.add(str(name))
                    if value.get("blueprints"):
                        discarded += 1
                if discarded:
                    notices.append(
                        f"discarded {discarded} legacy source-to-Blueprint mapping(s); "
                        "lineage records stories"
                    )
            if manifest.clear_source_lineage():
                manifest.save()
                notices.append("retired MANIFEST.md source_lineage")

    # A Target that already has a Manifest demonstrably ran plan over its sources, so recording a
    # backdated plan entry states a fact. Without one, nothing has consumed anything yet.
    planned = manifest_path.is_file()
    release = source_release(target_dir)
    for path in visible_sources(sources_dir):
        rel_path = path.relative_to(sources_dir).as_posix()
        version = append_version(
            lineage, rel_path, hash=file_hash(path), date=date, release=release
        )
        if version is None:
            continue
        if planned and rel_path not in legacy_pending and rel_path not in legacy_deleted:
            version.state = "consumed"
            version.via = "plan"
        if rel_path in legacy_deleted:
            mark_source_deleted(lineage, rel_path)
    return lineage, tuple(notices)


def load_or_migrate(target_dir: Path, *, date: str = "") -> Lineage:
    """The single entry point every caller uses to read lineage.

    An existing ``LINEAGE.json`` short-circuits, so migration runs at most once per Target. A
    Target with no legacy state still gets a valid empty record rather than an error: commands
    that need an import root report that specifically.
    """
    path = lineage_path(target_dir)
    if path.is_file():
        return load_lineage(target_dir)
    if not date:
        from datetime import date as _date

        date = _date.today().isoformat()
    lineage, notices = migrate_legacy(target_dir, date=date)
    write_lineage(target_dir, lineage)
    marker = target_dir / "blueprint" / "sources" / _LEGACY_IMPORT_MARKER
    if marker.is_file():
        marker.unlink()
    for notice in notices:
        print(f"  lineage: {notice}")
    return lineage
