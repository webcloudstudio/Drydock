"""``drydock rigging compact`` — LLM-compact stale files into ``_compact.md`` siblings.

The general compaction entry point. For a Blueprint it discovers every file that needs a compact
derivative and refreshes only the stale ones (a freshness gate, like V1
``bin/rulesengine_compact.sh``). With ``include_rigging`` it also refreshes existing derivatives in
Drydock's own ``Rigging/`` tree.

The LLM only emits text; this module writes the derivative deterministically, so execution needs no
file-write permission and tests inject a fake runner instead of spending API credits.
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
from drydock.prompts import load_prompt

PROMPT_NAME = "rigging_compact"
COMPACT_SUFFIX = "_compact"

# Files always expected to carry a compact derivative inside a Blueprint, even before a sibling
# exists. Source: docs/Drydock_Specification.md — "Rigging - Specification Compaction".
REQUIRED_PAIRS: tuple[str, ...] = ("DATABASE.md", "BUSINESS_RULES.md")

_GENERAL_OBJECTIVE = (
    "Preserve every actionable rule, code block, signature, and constraint. Remove rationale, "
    "examples, and narrative. Keep the result behaviorally faithful to the source."
)

# Per-file "stripped to" targets from docs/Drydock_Specification.md.
_OBJECTIVES: dict[str, str] = {
    "DATABASE.md": (
        "Strip to class names, method signatures, typed parameters, return types, and a one-line "
        "summary per method — the API surface a consuming story reads. Keep every signature exact; "
        "drop method bodies and prose."
    ),
    "BUSINESS_RULES.md": (
        "Strip to actionable rules only. Remove rationale and examples. Every 'must', 'never', and "
        "numeric threshold is preserved verbatim."
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
    status: str  # compacted | skipped-fresh | failed
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

    def failed(self) -> list[CompactItem]:
        return [i for i in self.items if i.status == "failed"]

    def exit_code(self) -> int:
        return 1 if self.failed() else 0


def _is_compact(path: Path) -> bool:
    return path.stem.endswith(COMPACT_SUFFIX)


def _compact_path(source: Path) -> Path:
    return source.with_name(f"{source.stem}{COMPACT_SUFFIX}.md")


def _is_stale(source: Path, compact: Path) -> bool:
    if not compact.exists():
        return True
    return source.stat().st_mtime > compact.stat().st_mtime


def discover(spec_dir: Path, *, include_rigging: bool = False) -> list[Path]:
    """Return source files that need a compact derivative, in stable order.

    Blueprint scope: the required pairs (when their source exists) plus any ``*.md`` that already
    has a ``*_compact.md`` sibling. Rigging scope (``include_rigging``): existing-sibling refreshes
    only. ``*_compact.md`` files are never treated as sources.
    """
    sources: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        if path not in seen:
            seen.add(path)
            sources.append(path)

    for name in REQUIRED_PAIRS:
        candidate = spec_dir / name
        if candidate.is_file():
            add(candidate)

    for md in sorted(spec_dir.glob("*.md")):
        if not _is_compact(md) and _compact_path(md).is_file():
            add(md)

    if include_rigging:
        for md in sorted(get_rigging_root().rglob("*.md")):
            if not _is_compact(md) and _compact_path(md).is_file():
                add(md)

    return sources


def _rel(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _assemble_prompt(
    body: str, *, rel_source: str, today: str, objective: str, source_text: str
) -> str:
    return (
        f"{body}\n\n"
        "## Compaction job\n\n"
        f"- SOURCE_PATH: {rel_source}\n"
        f"- DATE: {today}\n\n"
        "### Objective for this file\n\n"
        f"{objective}\n\n"
        "### Source content (compact this)\n\n"
        "```markdown\n"
        f"{source_text}\n"
        "```\n"
    )


_OUTER_FENCE = re.compile(r"\A```[\w-]*\s*\n(.*)\n```\s*\Z", re.DOTALL)
_LEADING_PROVENANCE = re.compile(r"\A<!--\s*Compacted from.*?-->\s*", re.DOTALL)


def _provenance(rel_source: str, today: str) -> str:
    return (
        f"<!-- Compacted from {rel_source} on {today} by drydock rigging compact — "
        "regenerate with: drydock rigging compact <Blueprint> -->"
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
    runner: RunnerFn | None = None,
    on_text: TextCallback | None = None,
    on_item: Callable[[CompactItem], None] | None = None,
    model: str | None = None,
    llm_provider: str | None = None,
) -> CompactResult:
    """Compact every stale derivative in ``blueprint`` (and Rigging when requested)."""
    # Resolved at call time so tests can monkeypatch ``run_prompt`` through the CLI path.
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

    for source in discover(spec_dir, include_rigging=include_rigging):
        compact_path = _compact_path(source)

        if not force and not _is_stale(source, compact_path):
            record(
                CompactItem(
                    source,
                    compact_path,
                    "skipped-fresh",
                    source_bytes=source.stat().st_size,
                    compact_bytes=compact_path.stat().st_size,
                )
            )
            continue

        rel_source = _rel(source, spec_dir)
        source_text = source.read_text(encoding="utf-8")
        source_bytes = len(source_text.encode("utf-8"))
        assembled = _assemble_prompt(
            prompt.body,
            rel_source=rel_source,
            today=today,
            objective=_OBJECTIVES.get(source.name, _GENERAL_OBJECTIVE),
            source_text=source_text,
        )
        result = run(
            assembled,
            spec_dir,
            llm=llm_provider,
            model=model or prompt.model,
            command_name="rigging compact",
            parameters={"source": str(source), "compact": str(compact_path)},
            on_text=on_text,
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
