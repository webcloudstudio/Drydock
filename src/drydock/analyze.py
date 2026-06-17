"""``drydock analyze`` — Scrum-team Blueprint analysis: quality signal, story list, artifacts.

Single LLM call producing all analyze outputs via delimited blocks. Writes deterministically;
tests inject a fake runner and never spend API credits.

Outputs: ANALYSIS.md (target root), SEA_TRIALS.md, SOUNDINGS.md, COMPASS.md (if absent or
unpopulated), BLOCKERS.md (only when blockers exist), spike-*.json questionnaires (one per open
question), captains_chair.html (when lifecycle state advances to analyzed).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from drydock.errors import SpecificationError
from drydock.llm import run_prompt
from drydock.metadata import set_build_state
from drydock.paths import get_rigging_root
from drydock.prompts import load_prompt, render_inputs

PROMPT_NAME = "analyze"

_SOURCES_SUBDIR = "sources"

_FEEDBACK_FILENAME = "ANALYSIS_FEEDBACK.md"
_FEEDBACK_DEFAULT = (
    "# Analysis Feedback\n\n"
    "These instructions are injected into every `drydock analyze` run for this target. "
    "Edit this file to steer the analysis. It persists across runs and is never overwritten "
    "by Drydock.\n\n"
    "Enter Direction for the Analysis Run\n"
)

_BLOCK_RE = re.compile(r"=== (.+?) ===\n(.*?)\n=== END \1 ===", re.DOTALL)
_QUALITY_RE = re.compile(r"^Quality:\s*(\S+)", re.MULTILINE)
_SUMMARY_FIELD_RE = re.compile(r"^  (\w+):\s*(.+?)$", re.MULTILINE)
# A genuine BLOCKERS.md block carries at least one "## " blocker entry (see prompts/analyze.md).
_BLOCKER_ENTRY_RE = re.compile(r"^## \S", re.MULTILINE)

_QUALITY_META: dict[str, tuple[str, str, str]] = {
    "Ready": ("ready", "✓", "All blockers resolved. Ready for plan create."),
    "Questions": ("questions", "⚠", "Open questions remain. Plan create can proceed."),
    "Blocked": ("blocked", "✗", "Unresolved blockers. Review before continuing."),
}


class CompletedRun(Protocol):
    @property
    def ok(self) -> bool: ...

    text: str
    execution_id: str


RunnerFn = Callable[..., CompletedRun]
TextCallback = Callable[[str], None]


@dataclass(frozen=True)
class AnalyzeResult:
    target_dir: Path
    analysis_path: Path
    sea_trials_path: Path
    soundings_path: Path
    compass_path: Path | None
    captains_chair_path: Path | None
    spike_paths: tuple[Path, ...]
    quality: str
    story_count: int
    question_count: int
    blocker_count: int
    screen_count: int
    stack: str
    execution_id: str | None
    ok: bool
    error: str | None = None
    blockers_path: Path | None = None

    def exit_code(self) -> int:
        return 0 if self.ok else 1


def _collect_blueprint_files(blueprint_dir: Path) -> list[Path]:
    """Return imported source files from blueprint/sources/ for analysis."""
    sources_dir = blueprint_dir / _SOURCES_SUBDIR
    if not sources_dir.is_dir():
        return []
    return sorted(sources_dir.rglob("*.md"))


def ensure_feedback_file(target_dir: Path) -> str:
    """Create ANALYSIS_FEEDBACK.md with the default prompt if absent; never overwrite.

    The feedback file is a persistent, human-owned standing directive re-injected into every
    ``drydock analyze`` run. Returns the file's current text.
    """
    path = target_dir / _FEEDBACK_FILENAME
    if not path.is_file():
        path.write_text(_FEEDBACK_DEFAULT, encoding="utf-8", newline="\n")
    return path.read_text(encoding="utf-8")


def _rigging_catalog_names() -> list[str]:
    """Return the stack-option filenames offered to the stack questionnaire.

    Names only — analyze never opens these files. Source: ``Rigging/BRA*.md`` plus
    ``Rigging/stack/*.md``, excluding ``README.md``.
    """
    try:
        root = get_rigging_root()
    except Exception:
        return []
    names = [p.name for p in root.glob("BRA*.md")]
    names += [p.name for p in (root / "stack").glob("*.md")]
    return sorted(name for name in names if name != "README.md")


_EMPTY_LINE = frozenset({"", "- None.", "- None"})


def _is_compass_unpopulated(path: Path) -> bool:
    """Return True if COMPASS.md exists but is an unfilled template."""
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    if "<!--" in text:
        return True
    # Collect content lines inside ## sections (skip H1 title and headers themselves)
    content_lines: list[str] = []
    in_section = False
    for line in text.splitlines():
        if line.startswith("## "):
            in_section = True
        elif line.startswith("# "):
            in_section = False
        elif in_section:
            content_lines.append(line.strip())
    if not content_lines:
        return True
    return all(line in _EMPTY_LINE for line in content_lines)


def _render_feedback(feedback_text: str | None) -> list[str]:
    # Standing directive — persistent human steering, re-injected on every run.
    if not (feedback_text and feedback_text.strip()):
        return []
    return [
        "## Analysis feedback (standing directive)",
        "",
        "Human direction for this analysis. Honor it; it persists across runs.",
        "",
        "```markdown",
        feedback_text.strip(),
        "```",
        "",
    ]


def _render_blockers(blockers_text: str | None) -> list[str]:
    # Prior blocker answers, present only after the Commander has answered them.
    if not blockers_text:
        return []
    return [
        "## Prior blocker answers (BLOCKERS.md)",
        "",
        "The Commander has answered the blocking questions from the prior analysis run.",
        "If the answers resolve the blockers, do not re-raise the same blockers.",
        "",
        "```markdown",
        blockers_text,
        "```",
        "",
    ]


def _render_typed_spec(blueprint_dir: Path) -> list[str]:
    # The Rigging catalog (stack-option filenames, no content) is analyze scaffolding that
    # reads immediately before the imported sources it contextualizes.
    parts: list[str] = []
    catalog = _rigging_catalog_names()
    if catalog:
        parts += [
            "## Rigging catalog (filenames only)",
            "",
            "Selectable stack options for spike-stack.json. Names only — never open these files.",
            "",
            *[f"- {name}" for name in catalog],
            "",
        ]
    parts += ["## Imported source files", ""]
    for path in _collect_blueprint_files(blueprint_dir):
        parts += [
            f"### {path.name}",
            "",
            "```markdown",
            path.read_text(encoding="utf-8"),
            "```",
            "",
        ]
    return parts


def _assemble_prompt(
    body: str,
    blueprint_dir: Path,
    today: str,
    *,
    compass_exists: bool,
    feedback_text: str | None = None,
    blockers_text: str | None = None,
    input_tokens: tuple[str, ...] | None = None,
) -> str:
    if input_tokens is None:
        input_tokens = load_prompt(PROMPT_NAME).input_tokens
    parts = [
        body,
        "",
        "## Analysis job",
        "",
        f"- BLUEPRINT_PATH: {blueprint_dir}",
        f"- DATE: {today}",
        f"- COMPASS_EXISTS: {'true' if compass_exists else 'false'}",
        "",
    ]
    # Injection order is the prompt's inputs: row. COMPASS.md is the COMPASS_EXISTS flag above
    # (no content section); TYPED_SPEC carries the Rigging catalog plus the imported sources.
    renderers: dict[str, Callable[[], list[str]]] = {
        "ANALYSIS_FEEDBACK.md": lambda: _render_feedback(feedback_text),
        "BLOCKERS.md": lambda: _render_blockers(blockers_text),
        "TYPED_SPEC": lambda: _render_typed_spec(blueprint_dir),
    }
    parts += render_inputs(input_tokens, renderers)
    return "\n".join(parts)


def _parse_blocks(text: str) -> dict[str, str]:
    """Return a dict of block-name → stripped content from === NAME === delimiters."""
    return {m.group(1): m.group(2).strip() for m in _BLOCK_RE.finditer(text)}


def _validate_blockers(raw: str | None) -> str | None:
    """Return blocker content only when it is a genuine, structured blocker list.

    The *existence* of ``BLOCKERS.md`` is the sole signal that halts ``plan create``; the
    deterministic writer — not model compliance — must therefore guarantee the file is never
    written empty or with placeholder text (e.g. the LLM emitting ``(omitted — no blockers)``
    inside the block instead of omitting it). Fail closed: anything lacking at least one ``## ``
    blocker entry is treated as "no blockers".
    """
    if not raw:
        return None
    stripped = raw.strip()
    if not _BLOCKER_ENTRY_RE.search(stripped):
        return None
    return stripped


def _parse_summary_fields(analysis_text: str) -> dict[str, str]:
    """Extract the indented sub-fields under '## Analysis Summary'."""
    fields: dict[str, str] = {}
    m = re.search(r"^## Analysis Summary\s*$(.*?)^## ", analysis_text, re.MULTILINE | re.DOTALL)
    section = m.group(1) if m else analysis_text
    for fm in _SUMMARY_FIELD_RE.finditer(section):
        fields[fm.group(1)] = fm.group(2).strip()
    return fields


def _parse_output(
    text: str,
) -> tuple[str, str, str, str | None, str | None, dict[str, dict], str, dict[str, str]]:
    """Return (analysis, sea_trials, soundings, compass_or_none, blockers_or_none, spikes,
    quality, summary).

    ``summary`` contains parsed sub-fields: blockers, questions, stories, stack, screens.
    Questionnaires (``spike-*.json``) and ``BLOCKERS.md`` are emitted dynamically — only when the
    analysis surfaces an open question or a blocker — so none of them are required.
    Raises ValueError on missing required blocks or invalid JSON.
    """
    blocks = _parse_blocks(text)

    for required in ("ANALYSIS.md", "SEA_TRIALS.md", "SOUNDINGS.md"):
        if required not in blocks:
            raise ValueError(f"LLM output missing === {required} === block")

    spikes: dict[str, dict] = {}
    for name, content in blocks.items():
        if name.startswith("spike-") and name.endswith(".json"):
            try:
                spikes[name] = json.loads(content)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{name} block is not valid JSON: {exc}") from exc

    analysis_text = blocks["ANALYSIS.md"]
    quality_match = _QUALITY_RE.search(analysis_text)
    quality = quality_match.group(1) if quality_match else "unknown"

    summary = _parse_summary_fields(analysis_text)
    compass_content = blocks.get("COMPASS.md") or None
    blockers_content = _validate_blockers(blocks.get("BLOCKERS.md"))

    return (
        analysis_text,
        blocks["SEA_TRIALS.md"],
        blocks["SOUNDINGS.md"],
        compass_content,
        blockers_content,
        spikes,
        quality,
        summary,
    )


def _fill_captains_chair(
    template: str,
    *,
    quality: str,
    story_count: int,
    question_count: int,
    blocker_count: int,
    screen_count: int,
    stack: str,
    next_step: str,
    project_name: str,
    generated_date: str,
) -> str:
    css_class, icon, desc = _QUALITY_META.get(quality, ("blocked", "?", quality))
    replacements = {
        "{{PROJECT_NAME}}": project_name,
        "{{GENERATED_DATE}}": generated_date,
        "{{QUALITY}}": quality,
        "{{QUALITY_CSS}}": css_class,
        "{{QUALITY_ICON}}": icon,
        "{{QUALITY_DESC}}": desc,
        "{{STORY_COUNT}}": str(story_count),
        "{{QUESTION_COUNT}}": str(question_count),
        "{{BLOCKER_COUNT}}": str(blocker_count),
        "{{SCREEN_COUNT}}": str(screen_count),
        "{{STACK}}": stack or "not declared",
        "{{NEXT_STEP}}": next_step,
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template


def _next_step_hint(quality: str, target: str) -> str:
    if quality == "Blocked":
        return f"Resolve blockers, then re-run: drydock analyze {target}"
    if quality == "Questions":
        return f"Review open questions, then run: drydock plan create {target}"
    return f"drydock plan create {target}"


def analyze(
    target: str,
    target_dir: Path,
    *,
    runner: RunnerFn | None = None,
    on_text: TextCallback | None = None,
) -> AnalyzeResult:
    """Analyze a Blueprint and write all analyze artifacts to the Target."""
    blueprint_dir = target_dir / "blueprint"
    if not blueprint_dir.is_dir():
        raise SpecificationError(f"Blueprint directory not found: {blueprint_dir}")

    questionnaires_dir = target_dir / "QuarterDeck" / "questionnaires"
    analysis_path = target_dir / "ANALYSIS.md"
    sea_trials_path = target_dir / "SEA_TRIALS.md"
    soundings_path = target_dir / "SOUNDINGS.md"
    compass_target = target_dir / "COMPASS.md"

    # COMPASS is (re)written when absent or when the existing file is an unpopulated template.
    compass_exists = compass_target.is_file() and not _is_compass_unpopulated(compass_target)

    # Inject prior blocker answers if the Commander has filled in BLOCKERS.md.
    blockers_md_path = target_dir / "BLOCKERS.md"
    blockers_text = (
        blockers_md_path.read_text(encoding="utf-8") if blockers_md_path.is_file() else None
    )

    # Standing-directive feedback file — created if absent, never overwritten, injected when the
    # user has edited it beyond the default placeholder.
    feedback_text = ensure_feedback_file(target_dir)
    feedback_for_prompt = (
        feedback_text if feedback_text.strip() != _FEEDBACK_DEFAULT.strip() else None
    )

    run = runner if runner is not None else run_prompt
    prompt = load_prompt(PROMPT_NAME)
    today = date.today().isoformat()
    assembled = _assemble_prompt(
        prompt.body,
        blueprint_dir,
        today,
        compass_exists=compass_exists,
        feedback_text=feedback_for_prompt,
        blockers_text=blockers_text,
        input_tokens=prompt.input_tokens,
    )

    result = run(
        assembled,
        target_dir,
        model=prompt.model,
        command_name="analyze",
        parameters={"target": target, "blueprint": str(blueprint_dir)},
        on_text=on_text,
    )

    exec_id = getattr(result, "execution_id", None)

    def _fail(msg: str) -> AnalyzeResult:
        return AnalyzeResult(
            target_dir=target_dir,
            analysis_path=analysis_path,
            sea_trials_path=sea_trials_path,
            soundings_path=soundings_path,
            compass_path=None,
            captains_chair_path=None,
            spike_paths=(),
            quality="unknown",
            story_count=0,
            question_count=0,
            blocker_count=0,
            screen_count=0,
            stack="",
            execution_id=exec_id,
            ok=False,
            error=msg,
            blockers_path=None,
        )

    if not result.ok or not result.text.strip():
        return _fail("LLM execution failed")

    try:
        (
            analysis_text,
            sea_trials_text,
            soundings_text,
            compass_text,
            blockers_text_out,
            spikes,
            quality,
            summary,
        ) = _parse_output(result.text)
    except ValueError as exc:
        return _fail(str(exc))

    def _safe_int(key: str) -> int:
        try:
            return int(summary.get(key, "0"))
        except (ValueError, TypeError):
            return 0

    story_count = _safe_int("stories")
    question_count = _safe_int("questions")
    blocker_count = _safe_int("blockers")
    screen_count = _safe_int("screens")
    stack = summary.get("stack", "not declared")

    questionnaires_dir.mkdir(parents=True, exist_ok=True)

    analysis_path.write_text(analysis_text + "\n", encoding="utf-8", newline="\n")
    sea_trials_path.write_text(sea_trials_text + "\n", encoding="utf-8", newline="\n")
    soundings_path.write_text(soundings_text + "\n", encoding="utf-8", newline="\n")

    written_compass: Path | None = None
    if compass_text and not compass_exists:
        compass_target.write_text(compass_text + "\n", encoding="utf-8", newline="\n")
        written_compass = compass_target

    spike_paths: list[Path] = []
    for name, data in spikes.items():
        spike_path = questionnaires_dir / name
        spike_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
        spike_paths.append(spike_path)

    # BLOCKERS.md — written only when _validate_blockers accepted a genuine, structured block.
    # Its presence is the flag that halts the pipeline; written when present, deleted otherwise
    # (resolved, empty, or placeholder). Never trust block-presence alone — fail closed.
    written_blockers: Path | None = None
    if blockers_text_out:
        blockers_md_path.write_text(blockers_text_out + "\n", encoding="utf-8", newline="\n")
        written_blockers = blockers_md_path
    elif blockers_md_path.is_file():
        blockers_md_path.unlink()

    # Lifecycle state and Captain's Chair — only when state advances to "analyzed".
    captains_chair_path: Path | None = None
    state_advanced = set_build_state(target_dir, "analyzed")
    if state_advanced:
        try:
            template_path = get_rigging_root() / "templates" / "captains_chair.html"
            if template_path.is_file():
                template = template_path.read_text(encoding="utf-8")
                filled = _fill_captains_chair(
                    template,
                    quality=quality,
                    story_count=story_count,
                    question_count=question_count,
                    blocker_count=blocker_count,
                    screen_count=screen_count,
                    stack=stack,
                    next_step=_next_step_hint(quality, target),
                    project_name=target,
                    generated_date=today,
                )
                chair_path = target_dir / "QuarterDeck" / "captains_chair.html"
                chair_path.parent.mkdir(parents=True, exist_ok=True)
                chair_path.write_text(filled, encoding="utf-8", newline="\n")
                captains_chair_path = chair_path
        except Exception:
            pass  # Captain's Chair failure must not abort a successful analysis

    return AnalyzeResult(
        target_dir=target_dir,
        analysis_path=analysis_path,
        sea_trials_path=sea_trials_path,
        soundings_path=soundings_path,
        compass_path=written_compass,
        captains_chair_path=captains_chair_path,
        spike_paths=tuple(sorted(spike_paths)),
        quality=quality,
        story_count=story_count,
        question_count=question_count,
        blocker_count=blocker_count,
        screen_count=screen_count,
        stack=stack,
        execution_id=exec_id,
        ok=True,
        blockers_path=written_blockers,
    )
