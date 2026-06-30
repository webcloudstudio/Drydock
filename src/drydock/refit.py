"""``drydock refit`` — conform change tickets in blueprint/changes/ to the build process.

Each ``TICKET-NNN-{Name}.md`` file is read, its typed spec header is normalized (``Amends:``,
``Depends On:``, ``Version:``), stories and ACs are generated or refined, and MANIFEST.md is
patched with new story rows for those tickets. Applied manifest rows are never touched. Tests
inject a fake runner instead of spending API credits.
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
class RefitResult:
    target_dir: Path
    items: list[RefitItem]

    def conformed(self) -> list[RefitItem]:
        return [i for i in self.items if i.status == "conformed"]

    def skipped(self) -> list[RefitItem]:
        return [i for i in self.items if i.status == "skipped-no-amends"]

    def failed(self) -> list[RefitItem]:
        return [i for i in self.items if i.status == "failed"]

    def exit_code(self) -> int:
        return 1 if self.failed() else 0


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

    try:
        from drydock.build_plan import parse_build_plan

        plan = parse_build_plan(manifest_path)
        existing_states: dict[str, str] = {b.block_id: b.state for b in plan.blocks}
    except Exception:
        existing_states = {}

    manifest_text = manifest_path.read_text(encoding="utf-8")
    new_blocks = _split_manifest_blocks(new_rows)

    for block_text in new_blocks:
        id_match = _BLOCK_ID_RE.search(block_text)
        if not id_match:
            continue
        block_id = id_match.group(1)

        if existing_states.get(block_id) == "closed/verified":
            continue

        boundaries = _find_block_boundaries(manifest_text, block_id)
        normalized = block_text.rstrip("\n") + "\n"
        if boundaries is not None:
            start, end = boundaries
            manifest_text = manifest_text[:start] + normalized + manifest_text[end:]
        else:
            manifest_text = manifest_text.rstrip("\n") + "\n\n" + normalized

    manifest_path.write_text(manifest_text, encoding="utf-8", newline="\n")


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

    if not changes_dir.is_dir():
        return RefitResult(target_dir=target_dir, items=[])

    tickets = sorted(p for p in changes_dir.glob("*.md") if p.is_file())
    if not tickets:
        return RefitResult(target_dir=target_dir, items=[])

    prompt = load_prompt(PROMPT_NAME)
    today = date.today().isoformat()
    items: list[RefitItem] = []

    for ticket_path in tickets:
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

    return RefitResult(target_dir=target_dir, items=items)
