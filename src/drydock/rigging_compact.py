"""``drydock rigging compact`` — extract usage-surface compact derivatives from spec files.

Each eligible Markdown file is compacted to an MCP-inspired form containing only caller-facing
callable units (routes, methods, schemas). Builder files that have no technical surface (branding,
tone guides, process prose) are classified by the LLM and skipped with status ``no-surface``.
The full source is used by builder stories; consumer stories receive the compact derivative.

The LLM only emits text; this module writes the derivative deterministically. Tests inject a
fake runner instead of spending API credits.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

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

PROMPT_NAME = "rigging_compact"
COMPACT_SUFFIX = "_compact"

# Files always expected to carry a compact derivative inside a Blueprint.
REQUIRED_PAIRS: tuple[str, ...] = ("DATABASE.md", "BUSINESS_RULES.md")

_GENERAL_OBJECTIVE = (
    "Extract the caller-facing usage surface of this file. For each callable unit (route, method, "
    "function, schema, or required configuration entry), emit one MCP-style block with a typed "
    "input table and a returns description. Drop all implementation detail, rationale, and "
    "build-time constraints. If no callable units exist, emit: "
    "COMPACT_ERROR: no technical surface — builder use only"
)

_OBJECTIVES: dict[str, str] = {
    "DATABASE.md": (
        "Extract class names and method signatures as MCP-style blocks. For each method: one-line "
        "description, typed parameter table (name / type / required / description), and return "
        "type. Drop method bodies, implementation notes, and rationale."
    ),
    "BUSINESS_RULES.md": (
        "Extract callable enforcement points — any rule that a consuming story must satisfy to "
        "pass validation. Represent each as a named block with the condition and the expected "
        "outcome. Drop rationale, examples, and motivational prose."
    ),
}


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
    # status: compacted | skipped-fresh | no-surface | failed
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

    def no_surface(self) -> list[CompactItem]:
        return [i for i in self.items if i.status == "no-surface"]

    def failed(self) -> list[CompactItem]:
        return [i for i in self.items if i.status == "failed"]

    def exit_code(self) -> int:
        return 1 if self.failed() else 0


SKIP_SUFFIX = "_compact.skip"


def _is_compact(path: Path) -> bool:
    """True for any compact derivative: *_compact.md or *_compact.skip.md."""
    return COMPACT_SUFFIX in path.stem


def _compact_path(source: Path) -> Path:
    return source.with_name(f"{source.stem}{COMPACT_SUFFIX}.md")


def _skip_path(source: Path) -> Path:
    return source.with_name(f"{source.stem}{SKIP_SUFFIX}.md")


def _is_stale(source: Path) -> bool:
    """True when neither the compact nor skip sibling is as new as the source."""
    for sibling in (_compact_path(source), _skip_path(source)):
        if sibling.exists() and sibling.stat().st_mtime >= source.stat().st_mtime:
            return False
    return True


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
    never treated as sources. ``skip_autodiscovery`` suppresses the Blueprint-scope scan entirely,
    leaving only ``include_files`` and ``include_dirs`` as sources.
    """
    sources: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        resolved = path.resolve()
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
    body: str, *, rel_source: str, today: str, objective: str, source_text: str
) -> PromptAssembly:
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
                "### Source content (extract usage surface from this)",
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


def _provenance(rel_source: str, today: str) -> str:
    return (
        f"<!-- Compacted from {rel_source} on {today} by drydock rigging compact — "
        "regenerate with: drydock rigging compact --include-file {rel_source} -->"
    )


def _finalize(text: str, *, rel_source: str, today: str) -> str:
    body = text.strip()
    fenced = _OUTER_FENCE.match(body)
    if fenced:
        body = fenced.group(1).strip()
    body = _LEADING_PROVENANCE.sub("", body).strip()
    return f"{_provenance(rel_source, today)}\n\n{body}\n"


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

    prompt = load_prompt(PROMPT_NAME)
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
        compact_path = _compact_path(source)
        skip_path = _skip_path(source)

        if not force and not _is_stale(source):
            fresh_sibling = compact_path if compact_path.exists() else skip_path
            record(
                CompactItem(
                    source,
                    fresh_sibling,
                    "skipped-fresh",
                    source_bytes=source.stat().st_size,
                    compact_bytes=fresh_sibling.stat().st_size if fresh_sibling.exists() else None,
                )
            )
            continue

        rel_source = _rel(source, spec_dir)
        source_text = source.read_text(encoding="utf-8")
        source_bytes = len(source_text.encode("utf-8"))
        prompt_assembly = _assemble_prompt_assembly(
            prompt.body,
            rel_source=rel_source,
            today=today,
            objective=_OBJECTIVES.get(source.name, _GENERAL_OBJECTIVE),
            source_text=source_text,
        )
        result = run(
            prompt_assembly.rendered_text,
            spec_dir,
            llm=llm_provider,
            model=model or prompt.model,
            command_name="rigging compact",
            parameters={"source": str(source), "compact": str(compact_path)},
            log_dir=log_dir,
            target=target,
            on_text=on_text,
            prompt_assembly=prompt_assembly,
        )

        if not result.ok or not result.text.strip():
            record(
                CompactItem(
                    source,
                    compact_path,
                    "failed",
                    source_bytes=source_bytes,
                    execution_id=result.execution_id,
                    error="empty output" if result.ok else "LLM execution failed",
                )
            )
            continue

        error_msg = _extract_compact_error(result.text)
        if error_msg:
            skip_content = (
                f"<!-- no-surface: {rel_source} on {today} by drydock rigging compact"
                f" — {error_msg} -->\n"
            )
            skip_path.write_text(skip_content, encoding="utf-8", newline="\n")
            record(
                CompactItem(
                    source,
                    skip_path,
                    "no-surface",
                    source_bytes=source_bytes,
                    execution_id=result.execution_id,
                    error=error_msg,
                )
            )
            continue

        finalized = _finalize(result.text, rel_source=rel_source, today=today)
        compact_path.write_text(finalized, encoding="utf-8", newline="\n")
        record(
            CompactItem(
                source,
                compact_path,
                "compacted",
                source_bytes=source_bytes,
                compact_bytes=len(finalized.encode("utf-8")),
                execution_id=result.execution_id,
            )
        )

    return CompactResult(spec_dir=spec_dir, items=items)
