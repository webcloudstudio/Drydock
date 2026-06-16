"""``drydock plan create`` — LLM-driven authoring of the Blueprint and executable Manifest.

`plan create` implements the reviewed analysis. In one LLM call it rewrites the imported source
material into typed Blueprint specification files, emits the single ``BUILD_PLAN_COMPASS.md``
build-ordering file, and the executable ``MANIFEST.md`` — all as delimited ``=== NAME ===`` blocks.
The module parses the blocks, merges prior block states, runs a deterministic integrity gate, and
writes the files. The model emits text; the module writes files. Tests inject a fake runner and
never spend API credits.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from drydock.build_plan import BuildPlan, parse_build_plan
from drydock.errors import SpecificationError
from drydock.llm import run_prompt
from drydock.paths import get_prompts_root
from drydock.prompts import load_prompt
from drydock.standard_artifacts import (
    ensure_standard_artifacts,
    render_console,
    sync_plan_soundings,
)

PROMPT_NAME = "plan_create"

_BLOCK_RE = re.compile(r"=== (.+?) ===\n(.*?)\n=== END \1 ===", re.DOTALL)
_QUALITY_RE = re.compile(r"^Quality:\s*(\S+)", re.MULTILINE)
_SHAPE_RE = re.compile(r"Project type:\s*`?([A-Za-z][\w-]*)`?", re.MULTILINE)
_ID_RE = re.compile(r"^id:\s*(.+?)\s*$", re.MULTILINE)
_STATE_RE = re.compile(r"^state:\s*.+?\s*$", re.MULTILINE)
_MANIFEST_SPLIT_RE = re.compile(r"(?m)(?=^## (?:feature|story|spike|ac)\s+\d+:)")

# Block names the LLM emits that are not authored Blueprint spec files.
_RESERVED_BLOCKS = frozenset({"MANIFEST.md", "BUILD_PLAN_COMPASS.md", "PLAN_CREATE_BLOCKED.txt"})

_CONTRACT_FILES = ("MANIFEST_CONTRACT.md", "BLUEPRINTS_CONTRACT.md")


class CompletedRun(Protocol):
    @property
    def ok(self) -> bool: ...

    text: str
    execution_id: str


RunnerFn = Callable[..., CompletedRun]
TextCallback = Callable[[str], None]


@dataclass(frozen=True)
class PlanCreateResult:
    plan: BuildPlan
    target_dir: Path
    quarterdeck_dir: Path
    changed: bool
    authored_files: tuple[Path, ...] = ()
    warnings: tuple[str, ...] = ()
    execution_id: str | None = None


# ── Parsing ──────────────────────────────────────────────────────────────────────


def _parse_blocks(text: str) -> dict[str, str]:
    """Return block-name → stripped content from ``=== NAME ===`` delimiters."""
    return {m.group(1): m.group(2).strip() for m in _BLOCK_RE.finditer(text)}


def _read_if(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _collect_sources(blueprint_dir: Path) -> list[Path]:
    sources_dir = blueprint_dir / "sources"
    if not sources_dir.is_dir():
        return []
    return sorted(p for p in sources_dir.rglob("*.md") if p.is_file())


def _collect_spikes(target_dir: Path) -> list[Path]:
    qd = target_dir / "QuarterDeck" / "questionnaires"
    if not qd.is_dir():
        return []
    return sorted(qd.glob("spike-*.json"))


# ── Prompt assembly ────────────────────────────────────────────────────────────────


def _fenced(label: str, body: str, *, lang: str = "markdown") -> list[str]:
    return [f"## {label}", "", f"```{lang}", body.rstrip("\n"), "```", ""]


def _assemble_prompt(
    body: str,
    target_dir: Path,
    blueprint_dir: Path,
    analysis_text: str,
    today: str,
    *,
    old_manifest: str | None,
) -> str:
    shape_match = _SHAPE_RE.search(analysis_text)
    quality_match = _QUALITY_RE.search(analysis_text)
    parts: list[str] = [
        body,
        "",
        "## Planning job",
        "",
        f"- TARGET: {target_dir.name}",
        f"- BLUEPRINT_PATH: {blueprint_dir}",
        f"- DATE: {today}",
        f"- SYSTEM_SHAPE: {shape_match.group(1) if shape_match else 'unknown'}",
        f"- ANALYSIS_QUALITY: {quality_match.group(1) if quality_match else 'unknown'}",
        "",
    ]

    parts += _fenced("ANALYSIS.md (the reviewed plan)", analysis_text)

    for name in ("SEA_TRIALS.md", "SOUNDINGS.md", "COMPASS.md"):
        text = _read_if(target_dir / name)
        if text:
            parts += _fenced(name, text)

    config_text = _read_if(blueprint_dir / "BUILD_CONFIGURATION.md")
    if config_text:
        parts += _fenced("BUILD_CONFIGURATION.md (settled commander decisions)", config_text)

    spikes = _collect_spikes(target_dir)
    if spikes:
        parts += ["## Answered spikes (consume these decisions)", ""]
        for spike in spikes:
            parts += [f"### {spike.name}", "", "```json", spike.read_text(encoding="utf-8").rstrip(), "```", ""]

    if old_manifest:
        parts += _fenced(
            "Existing MANIFEST.md (prior plan — block states are preserved by the module)",
            old_manifest,
        )

    try:
        prompts_root = get_prompts_root()
        for contract in _CONTRACT_FILES:
            contract_path = prompts_root / contract
            if contract_path.is_file():
                parts += _fenced(contract, contract_path.read_text(encoding="utf-8"))
    except Exception:
        pass

    parts += ["## Imported source files", ""]
    for path in _collect_sources(blueprint_dir):
        parts += [f"### {path.relative_to(blueprint_dir).as_posix()}", "", "```markdown",
                  path.read_text(encoding="utf-8").rstrip(), "```", ""]

    return "\n".join(parts)


# ── State merge ─────────────────────────────────────────────────────────────────────


def _merge_states(manifest_text: str, old_states: dict[str, str]) -> str:
    """Preserve prior non-``pending`` block states by id when re-authoring the Manifest."""
    if not old_states:
        return manifest_text
    chunks = _MANIFEST_SPLIT_RE.split(manifest_text)

    def _patch(chunk: str) -> str:
        id_match = _ID_RE.search(chunk)
        if not id_match:
            return chunk
        prior = old_states.get(id_match.group(1).strip())
        if not prior or prior == "pending":
            return chunk
        if _STATE_RE.search(chunk):
            return _STATE_RE.sub(f"state: {prior}", chunk, count=1)
        return chunk

    return "".join(_patch(chunk) for chunk in chunks)


# ── Integrity gate ──────────────────────────────────────────────────────────────────


def _has_cycle(edges: dict[str, set[str]]) -> bool:
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in edges}

    def visit(node: str) -> bool:
        color[node] = GRAY
        for nxt in edges.get(node, set()):
            if nxt not in color:
                continue
            if color[nxt] == GRAY or (color[nxt] == WHITE and visit(nxt)):
                return True
        color[node] = BLACK
        return False

    return any(color[node] == WHITE and visit(node) for node in edges)


def _integrity_check(plan: BuildPlan, blueprint_dir: Path) -> list[str]:
    """Fatal issues raise SpecificationError; non-fatal issues return as warnings."""
    ids = {block.block_id for block in plan.blocks}
    fatal: list[str] = []
    warnings: list[str] = []

    edges: dict[str, set[str]] = {}
    for block in plan.blocks:
        edges[block.block_id] = set(block.depends)
        for dep in block.depends:
            if dep not in ids:
                fatal.append(f"{block.block_id}: depends on unknown id {dep!r}")

    if _has_cycle(edges):
        fatal.append("dependency graph contains a cycle")

    for block in plan.blocks:
        if block.block_type != "story":
            continue
        implements = block.fields.get("implements", ())
        targets = implements if isinstance(implements, tuple) else (implements,)
        for name in targets:
            if name and not (blueprint_dir / name).is_file():
                fatal.append(f"{block.block_id}: implements missing spec file {name!r}")
        has_ac = any(b.block_type == "ac" and b.parent == block.block_id for b in plan.blocks)
        if not has_ac:
            warnings.append(f"{block.block_id}: story has no acceptance check")

    if fatal:
        raise SpecificationError(
            "Plan integrity check failed:\n  " + "\n  ".join(fatal)
        )
    return warnings


# ── QuarterDeck projection ──────────────────────────────────────────────────────────


def _ticket_status(state: str) -> str:
    return {
        "pending": "backlog",
        "implemented": "review",
        "closed/verified": "done",
        "closed/failed": "review",
    }.get(state, "backlog")


def _write_quarterdeck(plan: BuildPlan, target_dir: Path) -> Path:
    quarterdeck = target_dir / "QuarterDeck"
    quarterdeck.mkdir(parents=True, exist_ok=True)
    ensure_standard_artifacts(plan.project, target_dir)
    sync_plan_soundings(plan, target_dir)
    # The QuarterDeck runtime is served from the package; only console state is
    # written into the Target (see quarterdeck_run.run_quarterdeck).

    ac_by_parent: dict[str, list[str]] = {}
    for block in plan.blocks:
        if block.block_type == "ac" and block.parent:
            ac_by_parent.setdefault(block.parent, []).append(block.name)
    tickets = []
    for block in plan.blocks:
        if block.block_type == "ac":
            continue
        ticket = {
            "id": block.block_id,
            "title": block.name,
            "kind": block.block_type,
            "status": _ticket_status(block.state),
            "body": str(block.fields.get("summary", "")),
        }
        if block.parent:
            ticket["parent"] = block.parent
        if ac_by_parent.get(block.block_id):
            ticket["ac"] = ac_by_parent[block.block_id]
        tickets.append(ticket)
    (quarterdeck / "tickets.json").write_text(
        json.dumps({"tickets": tickets}, indent=2) + "\n", encoding="utf-8"
    )
    (quarterdeck / "planning-session.md").write_text(
        f"# Planning Session: {plan.project}\n\n"
        f"Plan state: **{plan.state}**\n\n"
        "Review the proposed decomposition and acceptance gates on the Delivery Board. "
        "Approve the complete plan here before building.\n",
        encoding="utf-8",
    )
    (quarterdeck / "console.yaml").write_text(
        render_console(plan.project, plan_path=plan.path), encoding="utf-8"
    )
    return quarterdeck


# ── File writing ────────────────────────────────────────────────────────────────────


def _safe_blueprint_path(blueprint_dir: Path, name: str) -> Path:
    """Resolve an emitted block name under blueprint/, rejecting path traversal."""
    dest = (blueprint_dir / name).resolve()
    if blueprint_dir.resolve() not in dest.parents and dest != blueprint_dir.resolve():
        raise SpecificationError(f"Emitted file escapes the Blueprint directory: {name!r}")
    return dest


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip("\n") + "\n", encoding="utf-8", newline="\n")


# ── Entry point ─────────────────────────────────────────────────────────────────────


def create_plan(
    blueprint: str,
    target: str,
    target_directory: Path,
    *,
    runner: RunnerFn | None = None,
    on_text: TextCallback | None = None,
) -> PlanCreateResult:
    """Author the Blueprint and executable Manifest from the reviewed analysis."""
    target_dir = target_directory / target
    blueprint_dir = target_dir / "blueprint"
    if not blueprint_dir.is_dir():
        raise SpecificationError(
            f"Blueprint directory not found: {blueprint_dir}\n  Import source material first."
        )

    analysis_path = target_dir / "ANALYSIS.md"
    analysis_text = _read_if(analysis_path)
    if not analysis_text:
        raise SpecificationError(
            f"ANALYSIS.md not found: {analysis_path}\n  Run: drydock analyze {target}"
        )

    if (target_dir / "BLOCKERS.md").is_file():
        raise SpecificationError(
            "BLOCKERS.md is present — planning is blocked. Answer the blockers and re-run "
            f"`drydock analyze {target}` before `drydock plan create {target}`."
        )
    quality_match = _QUALITY_RE.search(analysis_text)
    if quality_match and quality_match.group(1).lower() == "blocked":
        raise SpecificationError(
            "ANALYSIS.md quality is Blocked — resolve blockers and re-run analyze before planning."
        )

    plan_path = target_dir / "MANIFEST.md"
    old_manifest = _read_if(plan_path)
    old = parse_build_plan(plan_path) if plan_path.is_file() else None
    old_states = {block.block_id: block.state for block in old.blocks} if old else {}

    run = runner if runner is not None else run_prompt
    prompt = load_prompt(PROMPT_NAME)
    today = datetime.now(timezone.utc).date().isoformat()  # noqa: UP017
    assembled = _assemble_prompt(
        prompt.body, target_dir, blueprint_dir, analysis_text, today, old_manifest=old_manifest
    )

    result = run(
        assembled,
        target_dir,
        model=prompt.model,
        command_name="plan create",
        parameters={"target": target, "blueprint": str(blueprint_dir)},
        on_text=on_text,
    )
    exec_id = getattr(result, "execution_id", None)
    if not result.ok or not result.text.strip():
        raise SpecificationError("plan create LLM execution failed")

    blocks = _parse_blocks(result.text)
    if "PLAN_CREATE_BLOCKED.txt" in blocks:
        raise SpecificationError(
            "Planning cannot proceed — analysis is Blocked. "
            "The existing Blueprint is preserved.\n  " + blocks["PLAN_CREATE_BLOCKED.txt"].strip()
        )
    for required in ("MANIFEST.md", "BUILD_PLAN_COMPASS.md"):
        if required not in blocks:
            raise SpecificationError(f"plan create output missing === {required} === block")

    # 1. Author the typed Blueprint spec files (everything that is not a reserved block).
    authored: list[Path] = []
    for name, content in blocks.items():
        if name in _RESERVED_BLOCKS:
            continue
        dest = _safe_blueprint_path(blueprint_dir, name)
        _write_text(dest, content)
        authored.append(dest)

    # 2. The single build-ordering inventory.
    _write_text(blueprint_dir / "BUILD_PLAN_COMPASS.md", blocks["BUILD_PLAN_COMPASS.md"])

    # 3. The executable plan, with prior block states preserved.
    manifest_text = _merge_states(blocks["MANIFEST.md"], old_states)
    _write_text(plan_path, manifest_text)

    # 4. Structural validation + deterministic integrity gate.
    plan = parse_build_plan(plan_path)
    warnings = _integrity_check(plan, blueprint_dir)

    changed = old_manifest != (plan_path.read_text(encoding="utf-8"))
    quarterdeck = _write_quarterdeck(plan, target_dir)
    return PlanCreateResult(
        plan=plan,
        target_dir=target_dir,
        quarterdeck_dir=quarterdeck,
        changed=changed,
        authored_files=tuple(sorted(authored)),
        warnings=tuple(warnings),
        execution_id=exec_id,
    )
