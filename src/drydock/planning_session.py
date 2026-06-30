"""``drydock plan create`` — LLM-driven authoring of the Blueprint and executable Manifest.

`plan create` implements the reviewed analysis. In one LLM call it rewrites the imported source
material into typed Blueprint specification files and the executable ``MANIFEST.md`` — all as
delimited ``=== NAME ===`` blocks. The Manifest is the single work graph: it carries build order,
grouping, and per-step prompt-assembly fields, so no separate build-ordering file is emitted.
The module parses the blocks, runs a deterministic integrity gate, and writes the files.

When a prior MANIFEST.md exists, a state-preserving merge runs after the new Manifest is written:
``applied_specs`` is restored verbatim, block states are carried forward for clean files (sha256
unchanged), dirty files (sha256 changed) are reset to ``pending``, and applied Blueprint files are
protected from overwrite. The model emits text; the module writes files. Tests inject a fake runner
and never spend API credits.
"""

from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256 as _sha256
from pathlib import Path
from typing import Protocol

from drydock.build import required_plan_auto_compact_sources
from drydock.build_plan import AppliedSpecRecord, BuildPlan, parse_build_plan, set_applied_specs
from drydock.errors import SpecificationError
from drydock.exclude_files import ensure_exclude_file, load_excluded_filenames
from drydock.llm import run_prompt
from drydock.manifest_edit import batch_set_block_fields
from drydock.metadata import increment_version, set_build_state, set_sub_state, stamp_last
from drydock.paths import get_prompts_root
from drydock.prompt_assembly import (
    PromptAssembly,
    contextual_fenced_parts,
    contextual_markdown_parts,
    lines_part,
    part,
    section_heading_part,
    system_preamble_part,
)
from drydock.prompt_context import prompt_source_header
from drydock.prompt_headers import prompt_header_for_file
from drydock.prompts import load_prompt
from drydock.rigging_compact import ensure_compact_files
from drydock.standard_artifacts import (
    ensure_standard_artifacts,
    render_console,
    sync_plan_soundings,
)

PROMPT_NAME = "plan_create"

_BLOCK_RE = re.compile(r"=== (.+?) ===\n(.*?)\n=== END \1 ===", re.DOTALL)
_WRITE_CALL_RE = re.compile(
    r'<invoke name="Write">\s*'
    r'<parameter name="file_path">(?P<path>.*?)</parameter>\s*'
    r'<parameter name="content">(?P<content>.*?)</parameter>\s*'
    r"</invoke>",
    re.DOTALL,
)
_QUALITY_RE = re.compile(r"^Quality:\s*(\S+)", re.MULTILINE)
_SHAPE_RE = re.compile(r"Project type:\s*`?([A-Za-z][\w-]*)`?", re.MULTILINE)
# Block names the LLM emits that are not authored Blueprint spec files.
_RESERVED_BLOCKS = frozenset({"MANIFEST.md", "PLAN_CREATE_BLOCKED.txt", "PLAN_CREATE_ERROR.txt"})
_NON_BLUEPRINT_ARTIFACTS = frozenset({"AGENTS.md"})

_CONTRACT_FILES = ("MANIFEST_CONTRACT.md", "BLUEPRINTS_CONTRACT.md")

# Hard cap on story count; plan create refuses to emit an over-decomposed plan.
_STORY_CAP = 100

_FEEDBACK_FILENAME = "PLAN_COMPASS.md"


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


def _execution_output_path(result: CompletedRun) -> str | None:
    artifacts = getattr(result, "artifacts", None)
    output_file = getattr(artifacts, "output_file", None)
    return str(output_file) if output_file else None


def _with_execution_evidence(message: str, result: CompletedRun) -> str:
    output_file = _execution_output_path(result)
    if output_file:
        return f"{message}\n  Execution output: {output_file}"
    return message


def _parse_strict_blocks(text: str, result: CompletedRun) -> dict[str, str]:
    """Parse the required artifact block protocol and reject malformed output."""
    blocks: dict[str, str] = {}
    cursor = 0
    for match in _BLOCK_RE.finditer(text):
        outside = text[cursor : match.start()]
        if outside.strip():
            raise SpecificationError(
                _with_execution_evidence(
                    "Plan generation failed: LLM output did not satisfy the artifact contract.\n"
                    "  Text appeared outside delimited artifact blocks.\n"
                    "  No Blueprint or Manifest artifacts were written.",
                    result,
                )
            )
        name = match.group(1).strip()
        if name in blocks:
            raise SpecificationError(
                _with_execution_evidence(
                    "Plan generation failed: LLM output did not satisfy the artifact contract.\n"
                    f"  Duplicate artifact block: {name}\n"
                    "  No Blueprint or Manifest artifacts were written.",
                    result,
                )
            )
        blocks[name] = match.group(2).strip()
        cursor = match.end()

    if text[cursor:].strip():
        raise SpecificationError(
            _with_execution_evidence(
                "Plan generation failed: LLM output did not satisfy the artifact contract.\n"
                "  Text appeared outside delimited artifact blocks.\n"
                "  No Blueprint or Manifest artifacts were written.",
                result,
            )
        )
    return blocks


def _parse_write_call_blocks(text: str, target_dir: Path, blueprint_dir: Path) -> dict[str, str]:
    """Recover artifacts from Claude's non-executed ``Write`` call transcript.

    Claude occasionally returns tool-call XML despite being invoked without tools.  The calls are
    not executed, but their content is a complete artifact set.  Accept only paths within the
    active Blueprint plus the target's two plan artifacts; ignore every other simulated write.
    """
    target_root = target_dir.resolve()
    blueprint_root = blueprint_dir.resolve()
    blocks: dict[str, str] = {}
    for match in _WRITE_CALL_RE.finditer(text):
        try:
            path = Path(match.group("path").strip()).expanduser().resolve()
        except OSError:
            continue
        content = match.group("content").strip()
        if path == target_root / "MANIFEST.md":
            name = "MANIFEST.md"
        elif path.is_relative_to(blueprint_root):
            name = path.relative_to(blueprint_root).as_posix()
        else:
            continue
        if name in blocks:
            raise SpecificationError(f"Duplicate simulated Write artifact: {name}")
        blocks[name] = content
    return blocks


def _read_if(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


# ── Replan state merge ─────────────────────────────────────────────────────────


def _file_sha256(path: Path) -> str:
    return _sha256(path.read_bytes()).hexdigest()


def _load_prior_plan_state(
    plan_path: Path,
) -> tuple[dict[str, AppliedSpecRecord], dict[str, tuple[str, str | None]]]:
    """Parse an existing MANIFEST.md and extract preservation state.

    Returns (applied_specs, {block_id → (state, finding)}).  Returns empty dicts
    when the manifest does not exist or cannot be parsed.  ``finding`` is non-None
    only for spike blocks that carry a non-empty finding text.
    """
    if not plan_path.is_file():
        return {}, {}
    try:
        prior = parse_build_plan(plan_path)
    except Exception:
        return {}, {}
    block_states: dict[str, tuple[str, str | None]] = {}
    for block in prior.blocks:
        finding: str | None = None
        if block.block_type == "spike":
            raw = block.fields.get("finding")
            if isinstance(raw, tuple):
                raw = ", ".join(str(r) for r in raw)
            finding = str(raw).strip() if raw else None
            if not finding:
                finding = None
        block_states[block.block_id] = (block.state, finding)
    return dict(prior.applied_specs), block_states


def _spec_is_dirty(
    spec_name: str,
    blueprint_dir: Path,
    applied_specs: dict[str, AppliedSpecRecord],
) -> bool:
    """Return True if the Blueprint file has changed since it was applied.

    A file with no applied_specs entry has never been applied — not dirty.
    A deleted file that was previously applied is dirty.
    """
    record = applied_specs.get(spec_name)
    if record is None:
        return False
    spec_path = blueprint_dir / spec_name
    if not spec_path.is_file():
        return True
    return _file_sha256(spec_path) != record.sha256


def _merge_prior_state(
    plan_path: Path,
    blueprint_dir: Path,
    prior_applied_specs: dict[str, AppliedSpecRecord],
    prior_block_states: dict[str, tuple[str, str | None]],
) -> None:
    """Carry forward execution state from a prior MANIFEST.md into the freshly written one.

    Rules applied in order:
    - ``applied_specs`` is restored verbatim — the graph database is never regenerated.
    - A block whose prior state is ``pending`` receives no update.
    - A block whose implements: files are all clean (sha256 unchanged) carries its prior
      state and, for spikes, its prior ``finding``.
    - A block with any dirty implements: file is left at ``pending``; the LLM will re-apply it.
    """
    if prior_applied_specs:
        set_applied_specs(plan_path, prior_applied_specs)

    if not prior_block_states:
        return

    new_plan = parse_build_plan(plan_path)
    updates: dict[str, dict[str, str]] = {}

    for block in new_plan.blocks:
        prior_state, prior_finding = prior_block_states.get(block.block_id, ("pending", None))

        if prior_state == "pending":
            if block.block_type == "spike" and prior_finding:
                updates[block.block_id] = {"finding": prior_finding}
            continue

        implements = block.fields.get("implements", ())
        if isinstance(implements, str):
            implements = (implements,)

        dirty = any(
            _spec_is_dirty(str(spec), blueprint_dir, prior_applied_specs)
            for spec in implements
            if spec
        )

        block_updates: dict[str, str] = {}
        if not dirty:
            block_updates["state"] = prior_state
        if block.block_type == "spike" and prior_finding:
            block_updates["finding"] = prior_finding

        if block_updates:
            updates[block.block_id] = block_updates

    batch_set_block_fields(plan_path, updates)


def _collect_sources(
    blueprint_dir: Path, *, excluded_filenames: frozenset[str] = frozenset()
) -> list[Path]:
    sources_dir = blueprint_dir / "sources"
    if not sources_dir.is_dir():
        return []
    return sorted(
        p for p in sources_dir.rglob("*.md") if p.is_file() and p.name not in excluded_filenames
    )


def _collect_changes(
    blueprint_dir: Path, *, excluded_filenames: frozenset[str] = frozenset()
) -> list[Path]:
    changes_dir = blueprint_dir / "changes"
    if not changes_dir.is_dir():
        return []
    return sorted(
        p for p in changes_dir.glob("*.md") if p.is_file() and p.name not in excluded_filenames
    )


def _collect_discoveries(target_dir: Path) -> list[Path]:
    qd = target_dir / "QuarterDeck" / "questionnaires"
    if not qd.is_dir():
        return []
    return sorted(qd.glob("discovery-*.json"))


def _answered_discovery(path: Path) -> dict | None:
    """Return the questionnaire with only its answered questions, or ``None`` if none are answered.

    A question is answered iff it carries non-empty ``answer`` text (written by QuarterDeck).
    Only answered fields feed ``plan create``; unanswered questions are excluded, and a
    questionnaire with no answers is skipped entirely.
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
    """Create PLAN_COMPASS.md with the default prompt if absent; never overwrite.

    A persistent, human-owned standing directive re-injected into every ``drydock plan create``
    run. Returns the file's current text.
    """
    path = target_dir / _FEEDBACK_FILENAME
    if not path.is_file():
        header = prompt_header_for_file(_FEEDBACK_FILENAME)
        path.write_text(
            (
                header.default_text
                if header and header.default_text is not None
                else "# Plan Compass\n"
            ),
            encoding="utf-8",
            newline="\n",
        )
    return path.read_text(encoding="utf-8")


# ── Prompt assembly ────────────────────────────────────────────────────────────────


def _fenced(label: str, body: str, *, lang: str = "markdown") -> list[str]:
    return [f"## {label}", "", f"```{lang}", body.rstrip("\n"), "```", ""]


def _fenced_if(path: Path, label: str) -> list[str]:
    text = _read_if(path)
    return _fenced(label, text) if text else []


def _render_answered_discoveries(target_dir: Path) -> list[str]:
    answered = [(p, _answered_discovery(p)) for p in _collect_discoveries(target_dir)]
    answered = [(p, data) for p, data in answered if data is not None]
    if not answered:
        return []
    parts = ["## Answered questionnaires (consume these decisions)", ""]
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
        label = path.relative_to(blueprint_dir).as_posix()
        parts += [
            f"### {prompt_source_header(label, path)}",
            "",
            "```markdown",
            path.read_text(encoding="utf-8").rstrip(),
            "```",
            "",
        ]
    return parts


def _managed_doc_parts(
    *,
    filename: str,
    content: str,
    content_role: str,
    path: Path,
) -> list:
    return list(
        contextual_markdown_parts(
            filename,
            content,
            filename=filename,
            role=content_role,
            path=path,
        )
    )


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
    return _assemble_prompt_assembly(
        body,
        target_dir,
        blueprint_dir,
        analysis_text,
        today,
        feedback_text=feedback_text,
        input_tokens=input_tokens,
        excluded_filenames=load_excluded_filenames(target_dir),
    ).rendered_text


def _assemble_prompt_assembly(
    body: str,
    target_dir: Path,
    blueprint_dir: Path,
    analysis_text: str,
    today: str,
    *,
    feedback_text: str | None = None,
    input_tokens: tuple[str, ...] | None = None,
    excluded_filenames: frozenset[str] = frozenset(),
) -> PromptAssembly:
    if input_tokens is None:
        input_tokens = load_prompt(PROMPT_NAME).input_tokens
    shape_match = _SHAPE_RE.search(analysis_text)
    quality_match = _QUALITY_RE.search(analysis_text)
    prompt_parts = [
        system_preamble_part(),
        section_heading_part("# Input Context"),
        lines_part(
            "Planning job",
            [
                "## Planning job",
                "",
                f"- TARGET: {target_dir.name}",
                f"- BLUEPRINT_PATH: {blueprint_dir}",
                f"- DATE: {today}",
                f"- SYSTEM_SHAPE: {shape_match.group(1) if shape_match else 'unknown'}",
                f"- ANALYSIS_QUALITY: {quality_match.group(1) if quality_match else 'unknown'}",
                "",
            ],
            kind="job",
        ),
    ]

    def compass_parts() -> list:
        path = target_dir / "COMPASS.md"
        text = _read_if(path)
        if not text:
            return []
        return _managed_doc_parts(
            filename="COMPASS.md",
            content=text,
            content_role="compass",
            path=path,
        )

    def plan_compass_parts() -> list:
        if not (feedback_text and feedback_text.strip()):
            return []
        return _managed_doc_parts(
            filename=_FEEDBACK_FILENAME,
            content=feedback_text.strip(),
            content_role="plan feedback",
            path=target_dir / _FEEDBACK_FILENAME,
        )

    def analysis_parts() -> list:
        return list(
            contextual_markdown_parts(
                "ANALYSIS.md",
                analysis_text,
                filename="ANALYSIS.md",
                role="planning basis",
                path=target_dir / "ANALYSIS.md",
            )
        )

    def soundings_parts() -> list:
        path = target_dir / "SOUNDINGS.md"
        text = _read_if(path)
        if not text:
            return []
        return list(
            contextual_markdown_parts(
                "SOUNDINGS.md",
                text,
                filename="SOUNDINGS.md",
                role="acceptance context",
                path=path,
            )
        )

    def questionnaire_parts() -> list:
        answered = [(p, _answered_discovery(p)) for p in _collect_discoveries(target_dir)]
        answered = [(p, data) for p, data in answered if data is not None]
        if not answered:
            return []
        parts_list = [
            lines_part(
                "Answered questionnaire header",
                ["## Answered questionnaires (consume these decisions)", ""],
                kind="section",
            )
        ]
        for path_obj, data in answered:
            parts_list.extend(
                contextual_fenced_parts(
                    path_obj.name,
                    json.dumps(data, indent=2),
                    filename=path_obj.name,
                    fence="json",
                    role="questionnaire",
                    path=path_obj,
                )
            )
        return parts_list

    def typed_spec_parts() -> list:
        parts_list = [
            lines_part(
                "Imported source file header", ["## Imported source files", ""], kind="section"
            )
        ]
        for path_obj in _collect_sources(blueprint_dir, excluded_filenames=excluded_filenames):
            label = path_obj.relative_to(blueprint_dir).as_posix()
            parts_list.extend(
                contextual_markdown_parts(
                    label,
                    path_obj.read_text(encoding="utf-8").rstrip(),
                    filename=path_obj.name,
                    role="source file",
                    path=path_obj,
                )
            )
        change_files = _collect_changes(blueprint_dir, excluded_filenames=excluded_filenames)
        if change_files:
            parts_list.append(
                lines_part(
                    "Change ticket header",
                    [
                        "## Change tickets",
                        "",
                        "These files amend existing Blueprint specs. Each ticket declares the",
                        "parent spec in its `Amends:` header. Stories generated for a change",
                        "ticket must inherit the full `depends:` chain of the parent spec's",
                        "stories.",
                        "",
                    ],
                    kind="section",
                )
            )
            for path_obj in change_files:
                label = f"changes/{path_obj.name}"
                parts_list.extend(
                    contextual_markdown_parts(
                        label,
                        path_obj.read_text(encoding="utf-8").rstrip(),
                        filename=label,
                        role="change ticket",
                        path=path_obj,
                    )
                )
        return parts_list

    def contract_parts(name: str) -> list:
        try:
            contract_path = get_prompts_root() / name
        except Exception:
            return []
        if not contract_path.is_file():
            return []
        return list(
            contextual_markdown_parts(
                name,
                contract_path.read_text(encoding="utf-8"),
                filename=name,
                role="contract",
                path=contract_path,
            )
        )

    renderers: dict[str, Callable[[], list]] = {
        "COMPASS.md": compass_parts,
        "PLAN_COMPASS.md": plan_compass_parts,
        "ANALYSIS.md": analysis_parts,
        "SOUNDINGS.md": soundings_parts,
        "QUESTIONNAIRES": questionnaire_parts,
        "TYPED_SPEC": typed_spec_parts,
    }
    for contract in _CONTRACT_FILES:
        renderers[contract] = lambda c=contract: contract_parts(c)
    for token in input_tokens:
        render = renderers.get(token)
        if render is None:
            continue
        prompt_parts.extend(render())
    prompt_parts.append(section_heading_part("# Agent Task"))
    prompt_parts.append(part("Prompt body", body + "\n\n", kind="prompt-body"))
    return PromptAssembly(parts=tuple(prompt_parts))


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


def _integrity_check(
    plan: BuildPlan, blueprint_dir: Path, *, available_specs: frozenset[str] = frozenset()
) -> list[str]:
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
            if name and name not in available_specs and not (blueprint_dir / name).is_file():
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


def _parse_plan_text(text: str) -> BuildPlan:
    """Parse Manifest text before target files are mutated."""
    with tempfile.TemporaryDirectory(prefix="drydock-plan-") as tmp:
        path = Path(tmp) / "MANIFEST.md"
        _write_text(path, text)
        return parse_build_plan(path)


def _validate_plan_output(
    blocks: dict[str, str], blueprint_dir: Path, result: CompletedRun
) -> tuple[BuildPlan, tuple[str, ...]]:
    """Validate one LLM response mode and return the parsed plan for success mode."""
    mode_blocks = {"MANIFEST.md", "PLAN_CREATE_BLOCKED.txt", "PLAN_CREATE_ERROR.txt"} & set(blocks)

    if "PLAN_CREATE_BLOCKED.txt" in blocks:
        if set(blocks) != {"PLAN_CREATE_BLOCKED.txt"}:
            raise SpecificationError(
                _with_execution_evidence(
                    "Plan generation failed: LLM output did not satisfy the artifact contract.\n"
                    "  BLOCKED MODE must emit only PLAN_CREATE_BLOCKED.txt.\n"
                    "  No Blueprint or Manifest artifacts were written.",
                    result,
                )
            )
        raise SpecificationError(
            "Planning cannot proceed. No Blueprint or Manifest artifacts were written.\n  "
            + blocks["PLAN_CREATE_BLOCKED.txt"].strip()
        )

    if "PLAN_CREATE_ERROR.txt" in blocks:
        if set(blocks) != {"PLAN_CREATE_ERROR.txt"}:
            raise SpecificationError(
                _with_execution_evidence(
                    "Plan generation failed: LLM output did not satisfy the artifact contract.\n"
                    "  ERROR MODE must emit only PLAN_CREATE_ERROR.txt.\n"
                    "  No Blueprint or Manifest artifacts were written.",
                    result,
                )
            )
        raise SpecificationError(
            "Plan generation failed: LLM reported that it could not produce a complete plan.\n"
            "  No Blueprint or Manifest artifacts were written.\n  "
            + blocks["PLAN_CREATE_ERROR.txt"].strip()
        )

    if not mode_blocks:
        raise SpecificationError(
            _with_execution_evidence(
                "Plan generation failed: LLM output missing === MANIFEST.md === block.\n"
                "  The response must contain only delimited artifact blocks.\n"
                "  No Blueprint or Manifest artifacts were written.",
                result,
            )
        )

    if mode_blocks != {"MANIFEST.md"}:
        raise SpecificationError(
            _with_execution_evidence(
                "Plan generation failed: LLM output mixed response modes.\n"
                "  SUCCESS MODE must not include PLAN_CREATE_BLOCKED.txt or PLAN_CREATE_ERROR.txt.\n"
                "  No Blueprint or Manifest artifacts were written.",
                result,
            )
        )

    plan = _parse_plan_text(blocks["MANIFEST.md"])

    emitted_specs = frozenset(name for name in blocks if name not in _RESERVED_BLOCKS)
    forbidden_artifacts = sorted(name for name in emitted_specs if name in _NON_BLUEPRINT_ARTIFACTS)
    if forbidden_artifacts:
        names = ", ".join(forbidden_artifacts)
        raise SpecificationError(
            _with_execution_evidence(
                "Plan generation failed: LLM output emitted non-Blueprint artifacts.\n"
                f"  Forbidden artifact(s): {names}\n"
                "  No Blueprint or Manifest artifacts were written.",
                result,
            )
        )
    missing_from_response: list[str] = []
    for block in plan.blocks:
        if block.block_type != "story":
            continue
        implements = block.fields.get("implements", ())
        targets = implements if isinstance(implements, tuple) else (implements,)
        for name in targets:
            if name in _NON_BLUEPRINT_ARTIFACTS:
                missing_from_response.append(
                    f"{block.block_id}: implements non-Blueprint file {name!r}"
                )
                continue
            if name and name not in emitted_specs and not (blueprint_dir / name).is_file():
                missing_from_response.append(
                    f"{block.block_id}: implements missing spec file {name!r}"
                )

    if missing_from_response:
        raise SpecificationError(
            _with_execution_evidence(
                "Plan generation failed: LLM output did not satisfy the artifact contract.\n  "
                + "\n  ".join(missing_from_response)
                + "\n  No Blueprint or Manifest artifacts were written.",
                result,
            )
        )

    warnings = tuple(_integrity_check(plan, blueprint_dir, available_specs=emitted_specs))
    return plan, warnings


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
        "Review the proposed decomposition, build order, and acceptance gates on the Kanban Board. "
        "The Planning Session shows the manifest build tree for execution review.\n",
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


def _normalize_manifest_contexts(plan_path: Path, blueprint_dir: Path) -> None:
    """Rewrite MANIFEST context fields to Drydock's deterministic compact policy."""
    plan = parse_build_plan(plan_path)
    updates: dict[str, dict[str, str | None]] = {}
    from drydock.build import normalize_context_names

    for block in plan.blocks:
        if block.block_type not in {"story", "spike"}:
            continue
        normalized = normalize_context_names(block, blueprint_dir)
        current = block.fields.get("context", ())
        current_tuple = current if isinstance(current, tuple) else ()
        if normalized == current_tuple:
            continue
        updates[block.block_id] = {
            "context": ", ".join(normalized) if normalized else None,
        }
    batch_set_block_fields(plan_path, updates)


# ── Entry point ─────────────────────────────────────────────────────────────────────


def create_plan(
    blueprint: str,
    target: str,
    target_directory: Path,
    *,
    runner: RunnerFn | None = None,
    on_text: TextCallback | None = None,
    model: str | None = None,
    llm_provider: str | None = None,
    log_dir: Path | None = None,
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
            f"`drydock analyze {target}` before `drydock plan {target}`."
        )
    quality_match = _QUALITY_RE.search(analysis_text)
    if quality_match and quality_match.group(1).lower() == "blocked":
        raise SpecificationError(
            "ANALYSIS.md quality is Blocked — resolve blockers and re-run analyze before planning."
        )

    plan_path = target_dir / "MANIFEST.md"
    prior_manifest = _read_if(plan_path)
    prior_applied_specs, prior_block_states = _load_prior_plan_state(plan_path)

    # Standing-directive feedback file — created if absent, never overwritten, injected when the
    # user has edited it beyond the default placeholder.
    feedback_text = ensure_feedback_file(target_dir)
    ensure_exclude_file(target_dir)
    default_feedback = prompt_header_for_file(_FEEDBACK_FILENAME)
    feedback_for_prompt = (
        feedback_text
        if feedback_text.strip()
        != (
            default_feedback.default_text.strip()
            if default_feedback and default_feedback.default_text
            else "# Plan Compass"
        )
        else None
    )

    run = runner if runner is not None else run_prompt
    prompt = load_prompt(PROMPT_NAME)
    today = datetime.now(timezone.utc).date().isoformat()  # noqa: UP017
    prompt_assembly = _assemble_prompt_assembly(
        prompt.body,
        target_dir,
        blueprint_dir,
        analysis_text,
        today,
        feedback_text=feedback_for_prompt,
        input_tokens=prompt.input_tokens,
        excluded_filenames=load_excluded_filenames(target_dir),
    )

    result = run(
        prompt_assembly.rendered_text,
        target_dir,
        llm=llm_provider,
        model=model or prompt.model,
        command_name="plan",
        parameters={"target": target, "blueprint": str(blueprint_dir)},
        log_dir=log_dir,
        target=target,
        on_text=on_text,
        prompt_assembly=prompt_assembly,
    )
    exec_id = getattr(result, "execution_id", None)
    if not result.ok or not result.text.strip():
        raise SpecificationError("Plan generation failed: plan LLM execution failed")

    blocks = _parse_strict_blocks(result.text, result)
    plan, warnings = _validate_plan_output(blocks, blueprint_dir, result)

    # Applied Blueprint files whose sha256 hasn't changed are protected: the LLM's
    # regenerated version is discarded so the file sha256 stays stable and the
    # merge can confirm the story is still clean (no re-run needed).
    _protected: frozenset[str] = frozenset(
        name
        for name in prior_applied_specs
        if not _spec_is_dirty(name, blueprint_dir, prior_applied_specs)
    )

    # 1. Author the typed Blueprint spec files (everything that is not a reserved block).
    authored: list[Path] = []
    for name, content in blocks.items():
        if name in _RESERVED_BLOCKS:
            continue
        dest = _safe_blueprint_path(blueprint_dir, name)
        if name in _protected:
            authored.append(dest)
            continue
        _write_text(dest, content)
        authored.append(dest)

    # 2. The executable plan. Write the LLM output, then merge prior block states and
    #    restore applied_specs so that closed/verified work and the graph database survive
    #    a replan. Dirty blocks (implements: sha256 changed) are left at pending.
    _write_text(plan_path, blocks["MANIFEST.md"])
    _merge_prior_state(plan_path, blueprint_dir, prior_applied_specs, prior_block_states)
    _normalize_manifest_contexts(plan_path, blueprint_dir)

    normalized_plan = parse_build_plan(plan_path)
    ensure_compact_files(
        blueprint_dir,
        sources=list(required_plan_auto_compact_sources(normalized_plan.blocks, blueprint_dir)),
        reason="created after plan",
        log_dir=log_dir,
        target=target,
        on_text=on_text,
        model=model,
        llm_provider=llm_provider,
    )

    # 4. Re-read the written Manifest so result paths reflect the target artifact.
    plan = parse_build_plan(plan_path)

    changed = prior_manifest != (plan_path.read_text(encoding="utf-8"))
    quarterdeck = _write_quarterdeck(plan, target_dir)

    increment_version(target_dir)
    set_build_state(target_dir, "planned")
    set_sub_state(target_dir, "approved")
    stamp_last(target_dir, "planned")

    from drydock.quarterdeck_state import refresh_commanders_chair as _refresh_chair

    _refresh_chair(target_dir)

    return PlanCreateResult(
        plan=plan,
        target_dir=target_dir,
        quarterdeck_dir=quarterdeck,
        changed=changed,
        authored_files=tuple(sorted(authored)),
        warnings=tuple(warnings),
        execution_id=exec_id,
    )
