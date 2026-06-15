"""``drydock analyze`` — Scrum-team Blueprint analysis: quality signal, story list, artifacts.

Single LLM call producing all analyze outputs via delimited blocks. Writes deterministically;
tests inject a fake runner and never spend API credits.

Outputs: ANALYSIS.md (target root), SEA_TRIALS.md, SOUNDINGS.md, COMPASS.md (if absent or
unpopulated), spike-intent.json, spike-stack.json, spike-gaps-ac.json, spike-guardrails.json,
variable spikes, captains_chair.html (when lifecycle state advances to analyzed).
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
from drydock.prompts import load_prompt

PROMPT_NAME = "analyze"

_SKIP_FILES = frozenset({
    "METADATA.md",
    "README.md",
    "IDEAS.md",
    "COMPASS.md",
    "ACCEPTANCE_CRITERIA.md",
})
_SKIP_PREFIX = "BUILD_"

_FIXED_SPIKES = (
    "spike-intent.json",
    "spike-stack.json",
    "spike-gaps-ac.json",
    "spike-guardrails.json",
)

_BLOCK_RE = re.compile(r"=== (.+?) ===\n(.*?)\n=== END \1 ===", re.DOTALL)
_QUALITY_RE = re.compile(r"^Quality:\s*(\S+)", re.MULTILINE)
_SUMMARY_FIELD_RE = re.compile(r"^  (\w+):\s*(.+?)$", re.MULTILINE)

_QUALITY_META: dict[str, tuple[str, str, str]] = {
    "Ready":     ("ready",     "✓", "All blockers resolved. Ready for plan create."),
    "Questions": ("questions", "⚠", "Open questions remain. Plan create can proceed."),
    "Blocked":   ("blocked",   "✗", "Unresolved blockers. Review before continuing."),
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

    def exit_code(self) -> int:
        return 0 if self.ok else 1


def _collect_blueprint_files(blueprint_dir: Path) -> list[Path]:
    """Return spec files for analysis, excluding meta/build files."""
    files = []
    for path in sorted(blueprint_dir.glob("*.md")):
        if path.name in _SKIP_FILES:
            continue
        if path.name.startswith(_SKIP_PREFIX):
            continue
        files.append(path)
    return files


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


def _assemble_prompt(
    body: str,
    blueprint_dir: Path,
    today: str,
    *,
    compass_exists: bool,
) -> str:
    files = _collect_blueprint_files(blueprint_dir)
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

    # Inject prior PO answers if BUILD_CONFIGURATION.md exists
    config_path = blueprint_dir / "BUILD_CONFIGURATION.md"
    if config_path.is_file():
        config_text = config_path.read_text(encoding="utf-8")
        parts += [
            "## Prior PO answers (BUILD_CONFIGURATION.md)",
            "",
            "Do not re-ask questions that are already answered here.",
            "",
            "```markdown",
            config_text,
            "```",
            "",
        ]

    # Inject Rigging stack catalog reference
    try:
        stack_readme = get_rigging_root() / "stack" / "README.md"
        if stack_readme.is_file():
            parts += [
                "## Rigging stack catalog",
                "",
                "Use these concrete technology names when populating spike-stack.json options.",
                "",
                "```markdown",
                stack_readme.read_text(encoding="utf-8"),
                "```",
                "",
            ]
    except Exception:
        pass

    parts += ["## Blueprint files", ""]
    for path in files:
        content = path.read_text(encoding="utf-8")
        parts.append(f"### {path.name}")
        parts.append("")
        parts.append("```markdown")
        parts.append(content)
        parts.append("```")
        parts.append("")
    return "\n".join(parts)


def _parse_blocks(text: str) -> dict[str, str]:
    """Return a dict of block-name → stripped content from === NAME === delimiters."""
    return {m.group(1): m.group(2).strip() for m in _BLOCK_RE.finditer(text)}


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
) -> tuple[str, str, str, str | None, dict[str, dict], str, dict[str, str]]:
    """Return (analysis, sea_trials, soundings, compass_or_none, spikes, quality, summary).

    ``summary`` contains parsed sub-fields: blockers, questions, stories, stack, screens.
    Raises ValueError on missing required blocks or invalid JSON.
    """
    blocks = _parse_blocks(text)

    for required in ("ANALYSIS.md", "SEA_TRIALS.md", "SOUNDINGS.md"):
        if required not in blocks:
            raise ValueError(f"LLM output missing === {required} === block")

    for spike_name in _FIXED_SPIKES:
        if spike_name not in blocks:
            raise ValueError(f"LLM output missing === {spike_name} === block")

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

    return (
        analysis_text,
        blocks["SEA_TRIALS.md"],
        blocks["SOUNDINGS.md"],
        compass_content,
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

    run = runner if runner is not None else run_prompt
    prompt = load_prompt(PROMPT_NAME)
    today = date.today().isoformat()
    assembled = _assemble_prompt(prompt.body, blueprint_dir, today, compass_exists=compass_exists)

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
        )

    if not result.ok or not result.text.strip():
        return _fail("LLM execution failed")

    try:
        analysis_text, sea_trials_text, soundings_text, compass_text, spikes, quality, summary = (
            _parse_output(result.text)
        )
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
    )
