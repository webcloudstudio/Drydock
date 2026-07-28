"""``drydock refit`` — conform change tickets in blueprint/changes/ to the build process.

Each ``TICKET-NNN-{Name}.md`` file is read, its typed spec header is normalized (``Amends:``,
``Depends On:``, ``Version:``), stories and ACs are generated or refined, and MANIFEST.md is
patched with new story rows for those tickets. After the ticket pass, a deterministic drift
reconciliation compares every ``applied_specs`` record against the current Blueprint content:
each drifted file resets its consumer blocks and their transitive dependents to ``pending``
and drops the stale provenance records, so the next ``drydock build`` rebuilds them in
dependency order. Sealed foundational specifications (``FOUNDATIONAL_SPECS``) may only drift
under a change ticket that amends them; unticketed foundational drift is reported and left
untouched. Tests inject a fake runner instead of spending API credits.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Protocol

from drydock.build_plan import (
    cascade_reset_ids,
    compact_source,
    foundational_source,
    parse_build_plan,
    set_applied_specs,
    stale_applied_specs,
)
from drydock.errors import SpecificationError
from drydock.llm import run_prompt
from drydock.manifest_edit import batch_set_block_fields
from drydock.prompt_assembly import (
    PromptAssembly,
    contextual_markdown_parts,
    lines_part,
    part,
    section_heading_part,
    system_preamble_part,
)
from drydock.prompts import load_prompt

PROMPT_NAME = "refit"

_BLOCK_RE = re.compile(r"=== (.+?) ===\n(.*?)\n=== END \1 ===", re.DOTALL)
_BLOCK_START_RE = re.compile(r"^## \w[^:]*:\s+.+", re.MULTILINE)
_BLOCK_ID_RE = re.compile(r"^id:\s+(\S+)", re.MULTILINE)
_AMENDS_TABLE_RE = re.compile(r"\|\s*Amends\s*\|\s*([^|]+)\|")
_AMENDS_BARE_RE = re.compile(r"^Amends:\s*(\S+)", re.MULTILINE)
_DEPENDS_ON_RE = re.compile(r"\|\s*Depends On\s*\|\s*([^|]+)\|")


class CompletedRun(Protocol):
    @property
    def ok(self) -> bool: ...

    text: str
    execution_id: str


RunnerFn = Callable[..., CompletedRun]
TextCallback = Callable[[str], None]


@dataclass(frozen=True)
class RefitItem:
    ticket: Path
    # "conformed" | "skipped-no-amends" | "failed"
    status: str
    execution_id: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class RefitReset:
    """One drifted Blueprint file and the manifest blocks reset for its rebuild."""

    path: str
    foundational: bool
    reset_ids: tuple[str, ...]


@dataclass(frozen=True)
class RefitResult:
    target_dir: Path
    items: list[RefitItem]
    resets: list[RefitReset] = field(default_factory=list)
    drift_errors: list[str] = field(default_factory=list)

    def conformed(self) -> list[RefitItem]:
        return [i for i in self.items if i.status == "conformed"]

    def skipped(self) -> list[RefitItem]:
        return [i for i in self.items if i.status == "skipped-no-amends"]

    def failed(self) -> list[RefitItem]:
        return [i for i in self.items if i.status == "failed"]

    def exit_code(self) -> int:
        return 1 if self.failed() or self.drift_errors else 0


def _parse_amends(ticket_text: str) -> str | None:
    """Extract Amends field value from a ticket. Checks header table then bare line."""
    m = _AMENDS_TABLE_RE.search(ticket_text)
    if m:
        return m.group(1).strip()
    m = _AMENDS_BARE_RE.search(ticket_text)
    if m:
        return m.group(1).strip()
    return None


def _parse_parent_depends(parent_text: str) -> list[str]:
    """Read the Depends On field from a parent spec header table."""
    m = _DEPENDS_ON_RE.search(parent_text)
    if not m:
        return []
    raw = m.group(1).strip()
    return [f.strip() for f in raw.split(",") if f.strip()]


def _resolve_ticket_deps(amends: str, blueprint_dir: Path) -> list[str]:
    """Return [parent_spec] + parent's Depends On list (deterministic, no LLM).

    If the parent spec is absent, returns [amends] only rather than failing.
    """
    parent_path = blueprint_dir / amends
    if not parent_path.is_file():
        return [amends]
    parent_text = parent_path.read_text(encoding="utf-8")
    parent_deps = _parse_parent_depends(parent_text)
    return [amends] + [d for d in parent_deps if d != amends]


def _assemble_refit_prompt(
    body: str,
    *,
    ticket_filename: str,
    ticket_text: str,
    parent_filename: str,
    parent_text: str,
    resolved_deps: list[str],
    today: str,
) -> PromptAssembly:
    """Build the per-ticket PromptAssembly: system preamble + job block + content + body."""
    deps_str = ", ".join(resolved_deps) if resolved_deps else "(none)"
    return PromptAssembly(
        parts=(
            system_preamble_part(),
            section_heading_part("# Input Context"),
            lines_part(
                "Refit job",
                [
                    "## Refit job",
                    "",
                    f"- TICKET_PATH: changes/{ticket_filename}",
                    f"- DATE: {today}",
                    f"- AMENDS: {parent_filename}",
                    f"- DEPENDS_ON: {deps_str}",
                    "",
                ],
                kind="job",
            ),
            *contextual_markdown_parts(
                f"changes/{ticket_filename}",
                ticket_text,
                filename=ticket_filename,
                role="change ticket",
            ),
            *contextual_markdown_parts(
                parent_filename,
                parent_text,
                filename=parent_filename,
                role="parent spec",
            ),
            section_heading_part("# Agent Task"),
            part("Prompt body", body + "\n\n", kind="prompt-body"),
        )
    )


def _parse_refit_output(
    text: str, ticket_filename: str
) -> tuple[str | None, str | None, str | None]:
    """Extract ticket content and MANIFEST_ROWS from LLM output.

    Returns (ticket_content, manifest_rows, error_message).
    error_message is set when REFIT_ERROR.txt is present or output is malformed.
    """
    blocks = {m.group(1): m.group(2).strip() for m in _BLOCK_RE.finditer(text)}

    if "REFIT_ERROR.txt" in blocks:
        return None, None, blocks["REFIT_ERROR.txt"]

    ticket_key = f"changes/{ticket_filename}"
    ticket_content = blocks.get(ticket_key)
    manifest_rows = blocks.get("MANIFEST_ROWS")

    if ticket_content is None and manifest_rows is None:
        return None, None, "LLM output contained no recognized artifact blocks"

    return ticket_content, manifest_rows, None


def _split_manifest_blocks(rows_text: str) -> list[str]:
    """Split MANIFEST_ROWS content into individual block strings."""
    parts = re.split(r"(?=^## )", rows_text.strip(), flags=re.MULTILINE)
    return [p for p in parts if p.strip() and p.lstrip().startswith("##")]


def _find_block_boundaries(text: str, block_id: str) -> tuple[int, int] | None:
    """Return (start, end) character offsets of the block with the given id, or None."""
    starts = [m.start() for m in _BLOCK_START_RE.finditer(text)]
    starts.append(len(text))

    for i, start in enumerate(starts[:-1]):
        end = starts[i + 1]
        block_text = text[start:end]
        id_match = _BLOCK_ID_RE.search(block_text)
        if id_match and id_match.group(1) == block_id:
            return start, end
    return None


def _patch_manifest(manifest_path: Path, new_rows: str) -> None:
    """Insert or update manifest rows.

    Rules:
    - closed/verified rows are left untouched.
    - pending/implemented rows with the same id are replaced.
    - New ids are appended.
    - The applied_specs block is never touched (it is in the preamble, not a ## block).
    """
    if not manifest_path.is_file() or not new_rows.strip():
        return

    from drydock.manifest import DrydockManifest

    graph = DrydockManifest.load(manifest_path, compatibility=True)
    new_blocks = _split_manifest_blocks(new_rows)
    replacement_ids: list[str] = []
    for block_text in new_blocks:
        id_match = _BLOCK_ID_RE.search(block_text)
        if not id_match:
            continue
        replacement_ids.append(id_match.group(1))
    if not replacement_ids:
        return

    # Parse one complete candidate graph so row references are resolved together.
    retained = [
        "\n".join(node.lines) for node in graph.blocks if node.block_id not in set(replacement_ids)
    ]
    candidate_text = "\n".join(graph.preamble).rstrip()
    candidate_text += "\n\n" + "\n\n".join([*retained, *new_blocks]) + "\n"
    proposed = DrydockManifest.parse(candidate_text, source=manifest_path, compatibility=True)

    proposed_by_id = proposed.by_id()
    for block_id in replacement_ids:
        node = proposed_by_id[block_id]
        if block_id in graph.by_id():
            graph.replace(block_id, node, preserve_verified=True)
        else:
            graph.add(node)
    graph.save()


def _reconcile_drift(
    manifest_path: Path,
    blueprint_dir: Path,
    amended_sources: set[str],
) -> tuple[list[RefitReset], list[str]]:
    """Reset consumer blocks for drifted applied specs; gate foundational drift on tickets.

    ``amended_sources`` are the source filenames named by this run's ticket ``Amends:``
    fields. A drifted foundational file not covered by one is reported as a drift error
    and left untouched. Every other drifted file resets its cascade to ``pending`` and
    its ``applied_specs`` records (and those stamped by reset blocks) are removed.
    """
    if not manifest_path.is_file():
        return [], []

    plan = parse_build_plan(manifest_path)
    stale = stale_applied_specs(plan, blueprint_dir)
    if not stale:
        return [], []

    errors: list[str] = []
    resettable = []
    for spec in stale:
        sealed = foundational_source(spec.rel_path)
        if sealed is not None and sealed not in amended_sources:
            errors.append(
                f"{spec.rel_path}: sealed foundational specification changed without a "
                f"change ticket. Create blueprint/changes/TICKET-NNN-<Name>.md with "
                f"'Amends: {sealed}' and rerun 'drydock refit'."
            )
            continue
        resettable.append(spec)

    if not resettable:
        return [], errors

    all_ids = cascade_reset_ids(plan, [spec.rel_path for spec in resettable])
    by_id = plan.by_id()
    updates: dict[str, dict[str, str | None]] = {
        block_id: {"state": "pending"} for block_id in all_ids if by_id[block_id].state != "pending"
    }
    if updates:
        batch_set_block_fields(manifest_path, updates)

    reset_set = set(all_ids)
    reset_paths = {spec.rel_path for spec in resettable}
    remaining = {
        rel_path: record
        for rel_path, record in plan.applied_specs.items()
        if rel_path not in reset_paths and record.applied_by not in reset_set
    }
    if remaining != plan.applied_specs:
        set_applied_specs(manifest_path, remaining)

    resets = [
        RefitReset(
            path=spec.rel_path,
            foundational=foundational_source(spec.rel_path) is not None,
            reset_ids=cascade_reset_ids(plan, [spec.rel_path]),
        )
        for spec in resettable
    ]
    return resets, errors


def refit_target(
    target_dir: Path,
    *,
    log_dir: Path | None = None,
    runner: RunnerFn | None = None,
    on_text: TextCallback | None = None,
    model: str | None = None,
    llm_provider: str | None = None,
) -> RefitResult:
    """Conform change tickets in blueprint/changes/ to the build process and patch MANIFEST.md."""
    from drydock.config import blueprint_dir_for

    run = runner if runner is not None else run_prompt

    if not target_dir.is_dir():
        raise SpecificationError(f"Target directory not found: {target_dir}")

    blueprint_dir = blueprint_dir_for(target_dir)
    changes_dir = blueprint_dir / "changes"
    manifest_path = target_dir / "MANIFEST.md"

    tickets = (
        sorted(p for p in changes_dir.glob("*.md") if p.is_file()) if changes_dir.is_dir() else []
    )

    prompt = load_prompt(PROMPT_NAME) if tickets else None
    today = date.today().isoformat()
    items: list[RefitItem] = []
    amended_sources: set[str] = set()

    for ticket_path in tickets:
        assert prompt is not None
        ticket_text = ticket_path.read_text(encoding="utf-8")
        amends = _parse_amends(ticket_text)

        if amends is None:
            items.append(
                RefitItem(
                    ticket=ticket_path,
                    status="skipped-no-amends",
                    error="no Amends: field found",
                )
            )
            continue

        amended_sources.add(Path(compact_source(amends)).name)
        resolved_deps = _resolve_ticket_deps(amends, blueprint_dir)
        parent_path = blueprint_dir / amends
        parent_text = parent_path.read_text(encoding="utf-8") if parent_path.is_file() else ""

        prompt_assembly = _assemble_refit_prompt(
            prompt.body,
            ticket_filename=ticket_path.name,
            ticket_text=ticket_text,
            parent_filename=amends,
            parent_text=parent_text,
            resolved_deps=resolved_deps,
            today=today,
        )

        result = run(
            prompt_assembly.rendered_text,
            blueprint_dir,
            llm=llm_provider,
            model=model or prompt.model,
            command_name="refit",
            parameters={"ticket": str(ticket_path), "amends": amends},
            log_dir=log_dir,
            target=target_dir.name,
            on_text=on_text,
            prompt_assembly=prompt_assembly,
        )

        if not result.ok or not result.text.strip():
            items.append(
                RefitItem(
                    ticket=ticket_path,
                    status="failed",
                    execution_id=result.execution_id,
                    error="empty output" if result.ok else "LLM execution failed",
                )
            )
            continue

        ticket_content, manifest_rows, error_msg = _parse_refit_output(
            result.text, ticket_path.name
        )

        if error_msg:
            items.append(
                RefitItem(
                    ticket=ticket_path,
                    status="failed",
                    execution_id=result.execution_id,
                    error=error_msg,
                )
            )
            continue

        if ticket_content:
            ticket_path.write_text(ticket_content.rstrip() + "\n", encoding="utf-8", newline="\n")

        if manifest_rows:
            _patch_manifest(manifest_path, manifest_rows)

        items.append(
            RefitItem(
                ticket=ticket_path,
                status="conformed",
                execution_id=result.execution_id,
            )
        )

    resets, drift_errors = _reconcile_drift(manifest_path, blueprint_dir, amended_sources)

    return RefitResult(target_dir=target_dir, items=items, resets=resets, drift_errors=drift_errors)
