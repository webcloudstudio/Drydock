"""``drydock plan create`` — LLM-driven authoring of the Blueprint and executable Manifest.

`plan create` implements the reviewed analysis. In one LLM call it rewrites the imported source
material into typed Blueprint specification files, emits the single ``BUILD_PLAN_COMPASS.md``
build-ordering file, and the executable ``MANIFEST.md`` — all as delimited ``=== NAME ===`` blocks.
The module parses the blocks, runs a deterministic integrity gate, and writes the files. Each run is
a single-directional clean regenerate: prior block states are not merged. The model emits text; the
module writes files. Tests inject a fake runner and never spend API credits.
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
from drydock.prompts import load_prompt, render_inputs
from drydock.standard_artifacts import (
    ensure_standard_artifacts,
    render_console,
    sync_plan_soundings,
)

PROMPT_NAME = "plan_create"

_BLOCK_RE = re.compile(r"=== (.+?) ===\n(.*?)\n=== END \1 ===", re.DOTALL)
_QUALITY_RE = re.compile(r"^Quality:\s*(\S+)", re.MULTILINE)
_SHAPE_RE = re.compile(r"Project type:\s*`?([A-Za-z][\w-]*)`?", re.MULTILINE)
# Block names the LLM emits that are not authored Blueprint spec files.
_RESERVED_BLOCKS = frozenset({"MANIFEST.md", "BUILD_PLAN_COMPASS.md", "PLAN_CREATE_BLOCKED.txt"})

_CONTRACT_FILES = ("MANIFEST_CONTRACT.md", "BLUEPRINTS_CONTRACT.md")

# Hard cap on story count; plan create refuses to emit an over-decomposed plan.
_STORY_CAP = 100

_FEEDBACK_FILENAME = "MANIFEST_COMPASS.md"
_FEEDBACK_DEFAULT = (
    "# Manifest Compass\n\n"
    "These instructions are injected into every `drydock plan create` run for this target. "
    "Edit this file to steer plan creation. It persists across runs and is never overwritten "
    "by Drydock.\n\n"
    "Enter Direction for the Manifest Run\n"
)


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


def _answered_spike(path: Path) -> dict | None:
    """Return the spike with only its answered questions, or ``None`` if none are answered.

    A question is answered iff it carries non-empty ``answer`` text (written by QuarterDeck).
    Only answered fields feed ``plan create``; unanswered questions are excluded, and a spike with
    no answers is skipped entirely.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    answered = [q for q in data.get("questions", []) if str(q.get("answer", "")).strip()]
    if not answered:
        return None
    return {**{k: v for k, v in data.items() if k != "questions"}, "questions": answered}


def ensure_feedback_file(target_dir: Path) -> str:
    """Create MANIFEST_COMPASS.md with the default prompt if absent; never overwrite.

    A persistent, human-owned standing directive re-injected into every ``drydock plan create``
    run. Returns the file's current text.
    """
    path = target_dir / _FEEDBACK_FILENAME
    if not path.is_file():
        path.write_text(_FEEDBACK_DEFAULT, encoding="utf-8", newline="\n")
    return path.read_text(encoding="utf-8")


# ── Prompt assembly ────────────────────────────────────────────────────────────────


def _fenced(label: str, body: str, *, lang: str = "markdown") -> list[str]:
    return [f"## {label}", "", f"```{lang}", body.rstrip("\n"), "```", ""]


def _fenced_if(path: Path, label: str) -> list[str]:
    text = _read_if(path)
    return _fenced(label, text) if text else []


def _render_feedback(feedback_text: str | None) -> list[str]:
    # Standing directive — persistent human steering, re-injected on every run.
    if not (feedback_text and feedback_text.strip()):
        return []
    return [
        "## Manifest feedback (standing directive)",
        "",
        "Human direction for plan creation. Honor it; it persists across runs.",
        "",
        "```markdown",
        feedback_text.strip(),
        "```",
        "",
    ]


def _render_answered_spikes(target_dir: Path) -> list[str]:
    answered = [(p, _answered_spike(p)) for p in _collect_spikes(target_dir)]
    answered = [(p, data) for p, data in answered if data is not None]
    if not answered:
        return []
    parts = ["## Answered spikes (consume these decisions)", ""]
    for path, data in answered:
        parts += ["### " + path.name, "", "```json", json.dumps(data, indent=2), "```", ""]
    return parts


def _render_contract(name: str) -> list[str]:
    try:
        contract_path = get_prompts_root() / name
    except Exception:
        return []
    if not contract_path.is_file():
        return []
    return _fenced(name, contract_path.read_text(encoding="utf-8"))


def _render_sources(blueprint_dir: Path) -> list[str]:
    parts = ["## Imported source files", ""]
    for path in _collect_sources(blueprint_dir):
        parts += [
            f"### {path.relative_to(blueprint_dir).as_posix()}",
            "",
            "```markdown",
            path.read_text(encoding="utf-8").rstrip(),
            "```",
            "",
        ]
    return parts


def _assemble_prompt(
    body: str,
    target_dir: Path,
    blueprint_dir: Path,
    analysis_text: str,
    today: str,
    *,
    feedback_text: str | None = None,
    input_tokens: tuple[str, ...] | None = None,
) -> str:
    if input_tokens is None:
        input_tokens = load_prompt(PROMPT_NAME).input_tokens
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
    # Injection order is the prompt's inputs: row. BLOCKERS.md has no renderer: it is the
    # refuse-if-present gate for plan create, so it never exists when assembly runs.
    renderers: dict[str, Callable[[], list[str]]] = {
        "COMPASS.md": lambda: _fenced_if(target_dir / "COMPASS.md", "COMPASS.md"),
        "MANIFEST_COMPASS.md": lambda: _render_feedback(feedback_text),
        "ANALYSIS.md": lambda: _fenced("ANALYSIS.md (the reviewed plan)", analysis_text),
        "SOUNDINGS.md": lambda: _fenced_if(target_dir / "SOUNDINGS.md", "SOUNDINGS.md"),
        "QUESTIONNAIRES": lambda: _render_answered_spikes(target_dir),
        "TYPED_SPEC": lambda: _render_sources(blueprint_dir),
    }
    for contract in _CONTRACT_FILES:
        renderers[contract] = lambda c=contract: _render_contract(c)
    parts += render_inputs(input_tokens, renderers)
    return "\n".join(parts)


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

    story_count = 0
    for block in plan.blocks:
        if block.block_type != "story":
            continue
        story_count += 1
        implements = block.fields.get("implements", ())
        targets = implements if isinstance(implements, tuple) else (implements,)
        for name in targets:
            if name and not (blueprint_dir / name).is_file():
                fatal.append(f"{block.block_id}: implements missing spec file {name!r}")
        # Every story must carry at least one acceptance gate — hard emission gate.
        has_ac = any(b.block_type == "ac" and b.parent == block.block_id for b in plan.blocks)
        if not has_ac:
            fatal.append(f"{block.block_id}: story has no acceptance check")

    # Reject an over-decomposed plan.
    if story_count > _STORY_CAP:
        fatal.append(f"story count {story_count} exceeds the ~{_STORY_CAP}-story cap")

    if fatal:
        raise SpecificationError("Plan integrity check failed:\n  " + "\n  ".join(fatal))
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
    prior_manifest = _read_if(plan_path)  # read only to report `changed`; not injected, not merged

    # Standing-directive feedback file — created if absent, never overwritten, injected when the
    # user has edited it beyond the default placeholder.
    feedback_text = ensure_feedback_file(target_dir)
    feedback_for_prompt = (
        feedback_text if feedback_text.strip() != _FEEDBACK_DEFAULT.strip() else None
    )

    run = runner if runner is not None else run_prompt
    prompt = load_prompt(PROMPT_NAME)
    today = datetime.now(timezone.utc).date().isoformat()  # noqa: UP017
    assembled = _assemble_prompt(
        prompt.body,
        target_dir,
        blueprint_dir,
        analysis_text,
        today,
        feedback_text=feedback_for_prompt,
        input_tokens=prompt.input_tokens,
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
            artifacts = getattr(result, "artifacts", None)
            output_file = getattr(artifacts, "output_file", None)
            evidence = f"\n  Execution output: {output_file}" if output_file else ""
            raise SpecificationError(
                f"plan create output missing === {required} === block. "
                "The LLM response must contain only delimited artifact blocks."
                f"{evidence}"
            )

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

    # 3. The executable plan. Single-directional regenerate: prior states are not merged —
    #    a new plan is authored fresh every run (LLM output is non-deterministic).
    _write_text(plan_path, blocks["MANIFEST.md"])

    # 4. Structural validation + deterministic integrity gate.
    plan = parse_build_plan(plan_path)
    warnings = _integrity_check(plan, blueprint_dir)

    changed = prior_manifest != (plan_path.read_text(encoding="utf-8"))
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
