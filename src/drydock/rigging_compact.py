"""``drydock rigging compact`` — extract role-based compact derivatives from spec files.

Each eligible Markdown file is compacted through a filename-selected prompt role:
contracts (default), architecture, or database API. Files with no compactable technical surface
are classified by the LLM and skipped with status ``no-surface``. The LLM only emits text; this
module writes the derivative deterministically. Tests inject a fake runner instead of spending API
credits.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from drydock.compass_sources import is_compass_file
from drydock.errors import SpecificationError
from drydock.llm import run_prompt
from drydock.paths import get_rigging_root
from drydock.prompt_assembly import (
    PromptAssembly,
    contextual_markdown_parts,
    lines_part,
    part,
    section_heading_part,
    system_preamble_part,
)
from drydock.prompts import load_prompt

COMPACT_SUFFIX = "_compact"

# Files always expected to carry a compact derivative inside a Blueprint.
REQUIRED_PAIRS: tuple[str, ...] = ("DATABASE.md", "BUSINESS_RULES.md")

# Sources whose failed or no-surface compaction blocks the caller; every other
# source is optional and the assembler falls through to the full file.
_REQUIRED_SOURCES = frozenset({"ARCHITECTURE.md", "DATABASE.md", *REQUIRED_PAIRS})


@dataclass(frozen=True)
class CompactRole:
    key: str
    label: str
    prompt_name: str
    objective: str


_CONTRACTS_ROLE = CompactRole(
    key="contracts",
    label="Contracts",
    prompt_name="rigging_compact_contracts",
    objective=(
        "Extract the consumer-facing contract surface of this file. Preserve routes, callable "
        "units, schemas, request and response shapes, required configuration, and validation "
        "rules another build step must satisfy. Drop implementation detail, rationale, and "
        "build-only prose. If there is no technical contract surface, emit: "
        "COMPACT_ERROR: no technical surface — builder use only"
    ),
)

_ARCHITECTURE_ROLE = CompactRole(
    key="architecture",
    label="Architecture",
    prompt_name="rigging_compact_architecture",
    objective=(
        "Extract the builder-facing structural contract of this architecture file. Preserve "
        "module layout, ownership boundaries, wiring shape, technical constraints, and required "
        "cross-cutting implementation rules. Drop narrative, repetition, and low-value detail, "
        "but keep rules that constrain where code may live or how components may interact."
    ),
)

_DATABASE_ROLE = CompactRole(
    key="database_api",
    label="Database API",
    prompt_name="rigging_compact_database",
    objective=(
        "Extract the builder-facing persistence contract of this database file. Preserve store "
        "interfaces, reads, writes, schemas, accepted inputs, returned data shapes, mutation "
        "rules, and persistence guardrails used by consuming steps. Drop internal implementation "
        "narrative and rationale."
    ),
)


def resolve_role(source: Path) -> CompactRole:
    """Return the compaction role selected for ``source`` by exact filename."""
    if source.name == "ARCHITECTURE.md":
        return _ARCHITECTURE_ROLE
    if source.name == "DATABASE.md":
        return _DATABASE_ROLE
    return _CONTRACTS_ROLE


class CompletedRun(Protocol):
    """The subset of an ``LlmResult`` this module consumes."""

    @property
    def ok(self) -> bool: ...

    text: str
    execution_id: str


RunnerFn = Callable[..., CompletedRun]
TextCallback = Callable[[str], None]


@dataclass(frozen=True)
class CompactItem:
    source: Path
    compact: Path
    role: str
    prompt_name: str
    # status: compacted | skipped-fresh | skipped-unchanged | no-surface | failed
    status: str
    source_bytes: int | None = None
    compact_bytes: int | None = None
    execution_id: str | None = None
    error: str | None = None

    @property
    def percent(self) -> float | None:
        if self.source_bytes and self.compact_bytes is not None and self.source_bytes > 0:
            return self.compact_bytes * 100 / self.source_bytes
        return None


@dataclass(frozen=True)
class CompactResult:
    spec_dir: Path
    items: list[CompactItem]

    def compacted(self) -> list[CompactItem]:
        return [i for i in self.items if i.status == "compacted"]

    def skipped(self) -> list[CompactItem]:
        return [i for i in self.items if i.status == "skipped-fresh"]

    def unchanged(self) -> list[CompactItem]:
        return [i for i in self.items if i.status == "skipped-unchanged"]

    def no_surface(self) -> list[CompactItem]:
        return [i for i in self.items if i.status == "no-surface"]

    def failed(self) -> list[CompactItem]:
        return [i for i in self.items if i.status == "failed"]

    def exit_code(self) -> int:
        return 1 if self.failed() else 0


def ensure_compact_files(
    blueprint_dir: Path,
    *,
    sources: list[Path],
    reason: str,
    log_dir: Path | None = None,
    target: str = "",
    runner: RunnerFn | None = None,
    on_text: TextCallback | None = None,
    model: str | None = None,
    llm_provider: str | None = None,
) -> CompactResult:
    """Ensure explicit source files have fresh compact derivatives.

    Missing files are ignored. ARCHITECTURE.md, DATABASE.md, and the required pairs
    are treated as required: a no-surface or failed compaction raises
    ``SpecificationError`` because downstream build context depends on them. All
    other sources (context-referenced feature and screen specifications) are
    optional: a no-surface classification writes the ``*_compact.skip.md`` marker
    and a failure is reported, but neither blocks — the assembler falls through to
    the full file when no compact derivative exists.
    """
    explicit = [path for path in sources if path.is_file()]
    if not explicit:
        return CompactResult(spec_dir=blueprint_dir, items=[])

    result = compact(
        blueprint_dir.name or target or "blueprint",
        blueprint_dir,
        include_files=explicit,
        skip_autodiscovery=True,
        log_dir=log_dir,
        target=target,
        runner=runner,
        on_text=on_text,
        model=model,
        llm_provider=llm_provider,
    )

    for item in result.items:
        role = f"{item.role} via {item.prompt_name}.md"
        # No-op refreshes (already fresh / structurally unchanged) do no work and are
        # not worth a console line during a build; only report work done or errors.
        if item.status == "compacted":
            detail = f"{item.compact.name} refreshed from {item.source.name}"
        elif item.status == "no-surface":
            detail = f"{item.source.name} rejected: {item.error}"
        elif item.status == "failed":
            detail = f"{item.source.name} failed: {item.error}"
        else:
            detail = None
        if detail is not None and on_text is not None:
            on_text(f"AUTO-COMPACT: {detail} [{role}] ({reason})")
        if item.status in {"no-surface", "failed"} and item.source.name in _REQUIRED_SOURCES:
            raise SpecificationError(
                f"Auto-compaction failed for {item.source.name}: {item.error or item.status}"
            )

    return result


SKIP_SUFFIX = "_compact.skip"


def _is_compact(path: Path) -> bool:
    """True for any compact derivative: *_compact.md or *_compact.skip.md."""
    return COMPACT_SUFFIX in path.stem


def _compact_path(source: Path) -> Path:
    return source.with_name(f"{source.stem}{COMPACT_SUFFIX}.md")


def _skip_path(source: Path) -> Path:
    return source.with_name(f"{source.stem}{SKIP_SUFFIX}.md")


_PROVENANCE_SHA_RE = re.compile(r"sha256=([0-9a-f]{64})")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sibling_source_sha(sibling: Path) -> str | None:
    """The source sha256 recorded in a derivative's provenance line, or None."""
    with sibling.open(encoding="utf-8") as handle:
        first_line = handle.readline()
    match = _PROVENANCE_SHA_RE.search(first_line)
    return match.group(1) if match else None


def _is_stale(source: Path) -> bool:
    """True when no sibling derivative is fresh for the source.

    A sibling is fresh when it is at least as new as the source (mtime fast
    path) or when its provenance records the source's current content sha256 —
    a rewrite that did not change the source's bytes never re-triggers
    compaction.
    """
    source_mtime = source.stat().st_mtime
    source_sha: str | None = None
    for sibling in (_compact_path(source), _skip_path(source)):
        if not sibling.exists():
            continue
        if sibling.stat().st_mtime >= source_mtime:
            return False
        if source_sha is None:
            source_sha = _sha256_text(source.read_text(encoding="utf-8"))
        if _sibling_source_sha(sibling) == source_sha:
            # Refresh mtime so the fast path answers without re-hashing next time.
            os.utime(sibling)
            return False
    return True


def compact_derivative_is_current(source: Path) -> bool:
    """True when a current compact or no-surface derivative exists for ``source``."""
    return source.is_file() and not _is_stale(source)


def _resolve_md(path: Path, base: Path) -> Path:
    """Resolve a file path relative to base if not absolute. Must be a .md file."""
    p = Path(path)
    if not p.is_absolute():
        p = base / p
    return p.resolve()


def discover(
    spec_dir: Path,
    *,
    include_rigging: bool = False,
    include_files: list[Path] | None = None,
    exclude_files: list[Path] | None = None,
    include_dirs: list[Path] | None = None,
    skip_autodiscovery: bool = False,
) -> list[Path]:
    """Return source files that need a compact derivative, in stable order.

    Blueprint scope: the required pairs (when their source exists) plus any ``*.md`` that already
    has a ``*_compact.md`` sibling. ``include_rigging`` adds existing-sibling refreshes from
    Drydock's own Rigging tree. ``include_files`` and ``include_dirs`` add explicit targets.
    ``exclude_files`` removes resolved paths from the candidate set. ``*_compact.md`` files are
    never treated as sources, and neither are the Compass files (``COMPASS.md``,
    ``PLAN_COMPASS.md``, ``ANALYZE_COMPASS.md``) — they carry no contract surface.
    ``skip_autodiscovery`` suppresses the Blueprint-scope scan entirely,
    leaving only ``include_files`` and ``include_dirs`` as sources.
    """
    sources: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        resolved = path.resolve()
        if is_compass_file(resolved):
            # Compass files are human direction with no contract surface: never compacted,
            # however they are named or included.
            return
        if resolved not in seen and not _is_compact(resolved) and resolved.suffix == ".md":
            seen.add(resolved)
            sources.append(resolved)

    if not skip_autodiscovery:
        for name in REQUIRED_PAIRS:
            candidate = spec_dir / name
            if candidate.is_file():
                add(candidate)

    if not skip_autodiscovery:
        for md in sorted(spec_dir.glob("*.md")):
            if not _is_compact(md) and (_compact_path(md).is_file() or _skip_path(md).is_file()):
                add(md)

    if include_rigging:
        for md in sorted(get_rigging_root().rglob("*.md")):
            if not _is_compact(md) and (_compact_path(md).is_file() or _skip_path(md).is_file()):
                add(md)

    if include_dirs:
        for d in include_dirs:
            for md in sorted(d.glob("*.md")):
                if md.is_file():
                    add(md)

    if include_files:
        for f in include_files:
            if f.is_file():
                add(f)

    if exclude_files:
        excluded = {f.resolve() for f in exclude_files}
        sources = [s for s in sources if s not in excluded]

    return sources


def _rel(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _assemble_prompt(
    body: str, *, rel_source: str, today: str, objective: str, source_text: str
) -> str:
    return _assemble_prompt_assembly(
        body,
        rel_source=rel_source,
        today=today,
        objective=objective,
        source_text=source_text,
    ).rendered_text


def _assemble_prompt_assembly(
    body: str,
    *,
    rel_source: str,
    today: str,
    objective: str,
    source_text: str,
    existing_compact: str | None = None,
) -> PromptAssembly:
    _ = existing_compact
    return PromptAssembly(
        parts=(
            system_preamble_part(),
            section_heading_part("# Input Context"),
            lines_part(
                "Compaction job",
                ["## Compaction job", "", f"- SOURCE_PATH: {rel_source}", f"- DATE: {today}", ""],
                kind="job",
            ),
            lines_part(
                "Compaction objective",
                ["### Objective for this file", "", objective, ""],
                kind="section",
            ),
            *contextual_markdown_parts(
                rel_source,
                source_text,
                filename=Path(rel_source).name,
                role="source file",
            ),
            section_heading_part("# Agent Task"),
            part("Prompt body", body + "\n\n", kind="prompt-body"),
        )
    )


_OUTER_FENCE = re.compile(r"\A```[\w-]*\s*\n(.*)\n```\s*\Z", re.DOTALL)
_LEADING_PROVENANCE = re.compile(r"\A<!--\s*Compacted from.*?-->\s*", re.DOTALL)
_COMPACT_ERROR = re.compile(r"^\s*COMPACT_ERROR:\s*(.+)", re.MULTILINE)


def _extract_compact_error(text: str) -> str | None:
    """Return the error message if the LLM flagged no technical surface, else None."""
    m = _COMPACT_ERROR.search(text.strip())
    return m.group(1).strip() if m else None


def _provenance(rel_source: str, today: str, source_sha: str) -> str:
    return (
        f"<!-- Compacted from {rel_source} sha256={source_sha} on {today} "
        "by drydock rigging compact — "
        "regenerate with: drydock rigging compact --include-file {rel_source} -->"
    )


def _strip_provenance(text: str) -> str:
    """Drop the dated provenance header so regenerated bodies compare content-only."""
    return _LEADING_PROVENANCE.sub("", text.strip()).strip()


def _finalize(text: str, *, rel_source: str, today: str, source_sha: str) -> str:
    body = text.strip()
    fenced = _OUTER_FENCE.match(body)
    if fenced:
        body = fenced.group(1).strip()
    body = _LEADING_PROVENANCE.sub("", body).strip()
    return f"{_provenance(rel_source, today, source_sha)}\n\n{body}\n"


def compact(
    blueprint: str,
    blueprint_dir: Path,
    *,
    include_rigging: bool = False,
    force: bool = False,
    include_files: list[Path] | None = None,
    exclude_files: list[Path] | None = None,
    include_dirs: list[Path] | None = None,
    skip_autodiscovery: bool = False,
    log_dir: Path | None = None,
    target: str = "",
    runner: RunnerFn | None = None,
    on_text: TextCallback | None = None,
    on_item: Callable[[CompactItem], None] | None = None,
    model: str | None = None,
    llm_provider: str | None = None,
) -> CompactResult:
    """Compact every stale derivative in ``blueprint`` (and optional extra paths).

    ``log_dir`` routes LLM execution artifacts to a specific directory; callers pass
    the workspace logs root so all artifacts land in one place. ``target`` is embedded
    in per-run filenames to distinguish runs across targets.
    """
    run = runner if runner is not None else run_prompt

    spec_dir = blueprint_dir
    if not spec_dir.is_dir():
        raise SpecificationError(f"Blueprint directory not found: {spec_dir}")

    today = date.today().isoformat()
    items: list[CompactItem] = []

    def record(item: CompactItem) -> None:
        items.append(item)
        if on_item is not None:
            on_item(item)

    sources = discover(
        spec_dir,
        include_rigging=include_rigging,
        include_files=include_files,
        exclude_files=exclude_files,
        include_dirs=include_dirs,
        skip_autodiscovery=skip_autodiscovery,
    )

    for source in sources:
        role = resolve_role(source)
        compact_path = _compact_path(source)
        skip_path = _skip_path(source)

        if not force and not _is_stale(source):
            fresh_sibling = compact_path if compact_path.exists() else skip_path
            record(
                CompactItem(
                    source,
                    fresh_sibling,
                    role.label,
                    role.prompt_name,
                    "skipped-fresh",
                    source_bytes=source.stat().st_size,
                    compact_bytes=fresh_sibling.stat().st_size if fresh_sibling.exists() else None,
                )
            )
            continue

        prompt = load_prompt(role.prompt_name)
        rel_source = _rel(source, spec_dir)
        source_text = source.read_text(encoding="utf-8")
        source_bytes = len(source_text.encode("utf-8"))
        existing_compact = (
            compact_path.read_text(encoding="utf-8") if compact_path.is_file() else None
        )
        if on_text is not None:
            on_text(
                "AUTO-COMPACT: compacting "
                f"{rel_source} -> {compact_path.name} "
                f"[{role.label} via {role.prompt_name}.md] "
                f"{source_bytes} B"
            )
        prompt_assembly = _assemble_prompt_assembly(
            prompt.body,
            rel_source=rel_source,
            today=today,
            objective=role.objective,
            source_text=source_text,
            existing_compact=existing_compact,
        )
        result = run(
            prompt_assembly.rendered_text,
            spec_dir,
            llm=llm_provider,
            model=model or prompt.model,
            command_name="rigging compact",
            parameters={
                "source": str(source),
                "compact": str(compact_path),
                "role": role.key,
                "prompt": role.prompt_name,
            },
            log_dir=log_dir,
            target=target,
            on_text=None,
            prompt_assembly=prompt_assembly,
        )

        if not result.ok or not result.text.strip():
            record(
                CompactItem(
                    source,
                    compact_path,
                    role.label,
                    role.prompt_name,
                    "failed",
                    source_bytes=source_bytes,
                    execution_id=result.execution_id,
                    error="empty output" if result.ok else "LLM execution failed",
                )
            )
            continue

        error_msg = _extract_compact_error(result.text)
        source_sha = _sha256_text(source_text)
        if error_msg:
            skip_content = (
                f"<!-- no-surface: {rel_source} sha256={source_sha} on {today} "
                f"by drydock rigging compact — {error_msg} -->\n"
            )
            skip_path.write_text(skip_content, encoding="utf-8", newline="\n")
            record(
                CompactItem(
                    source,
                    skip_path,
                    role.label,
                    role.prompt_name,
                    "no-surface",
                    source_bytes=source_bytes,
                    execution_id=result.execution_id,
                    error=error_msg,
                )
            )
            continue

        finalized = _finalize(
            result.text, rel_source=rel_source, today=today, source_sha=source_sha
        )
        if existing_compact is not None and _strip_provenance(finalized) == _strip_provenance(
            existing_compact
        ):
            # The regenerated body is identical: keep the existing bytes and refresh
            # mtime so staleness stops re-triggering — unless the old provenance
            # predates sha recording, in which case write the new header so the
            # sha gate can answer without an LLM run next time.
            if _sibling_source_sha(compact_path) != source_sha:
                compact_path.write_text(finalized, encoding="utf-8", newline="\n")
            else:
                os.utime(compact_path)
            record(
                CompactItem(
                    source,
                    compact_path,
                    role.label,
                    role.prompt_name,
                    "skipped-unchanged",
                    source_bytes=source_bytes,
                    compact_bytes=len(existing_compact.encode("utf-8")),
                    execution_id=result.execution_id,
                )
            )
            continue
        compact_path.write_text(finalized, encoding="utf-8", newline="\n")
        record(
            CompactItem(
                source,
                compact_path,
                role.label,
                role.prompt_name,
                "compacted",
                source_bytes=source_bytes,
                compact_bytes=len(finalized.encode("utf-8")),
                execution_id=result.execution_id,
            )
        )

    return CompactResult(spec_dir=spec_dir, items=items)
