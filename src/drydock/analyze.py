"""``drydock analyze`` — Scrum-team Blueprint analysis: quality signal, story list, artifacts.

Single LLM call producing all analyze outputs via delimited blocks. Writes deterministically;
tests inject a fake runner and never spend API credits.

Outputs: ANALYSIS.md (target root), SEA_TRIALS.md, SOUNDINGS.md, COMPASS.md (if absent or
unpopulated), BLOCKERS.md (only when blockers exist), discovery-*.json questionnaires (one per
open question), captains_chair.html (when lifecycle state advances to analyzed).
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
from drydock.metadata import (
    METADATA_NAME,
    set_build_state,
    set_field,
    set_sub_state,
    stamp_last,
)
from drydock.paths import get_rigging_root
from drydock.prompt_assembly import (
    PromptAssembly,
    fenced_markdown_part,
    fenced_text_part,
    lines_part,
    part,
)
from drydock.prompt_context import prompt_source_header
from drydock.prompt_headers import prompt_header_for_file
from drydock.prompts import load_prompt

PROMPT_NAME = "analyze"

_SOURCES_SUBDIR = "sources"

_FEEDBACK_FILENAME = "ANALYZE_COMPASS.md"

_BLOCK_RE = re.compile(r"=== (.+?) ===\n(.*?)\n=== END \1 ===", re.DOTALL)
_WRITE_INVOKE_RE = re.compile(
    r'<invoke name="(?:Write|mcp__claude-code__write_file)">\s*'
    r'<parameter name="(?:path|file_path)">(.*?)</parameter>\s*'
    r'<parameter name="content">(.*?)</parameter>\s*'
    r"</invoke>",
    re.DOTALL,
)
_QUALITY_RE = re.compile(r"^Quality:\s*(\S+)", re.MULTILINE)
_SUMMARY_FIELD_RE = re.compile(r"^  (\w+):\s*(.+?)$", re.MULTILINE)
# A genuine BLOCKERS.md block carries at least one "## " blocker entry (see prompts/analyze.md).
_BLOCKER_ENTRY_RE = re.compile(r"^## \S", re.MULTILINE)
_OPEN_QUESTIONS_SECTION_RE = re.compile(
    r"^## Open Questions\s*$.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL
)
_TUNING_OPTIONS_SECTION_RE = re.compile(
    r"^### Tuning Options\s*$.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL
)
_SUMMARY_QUALITY_RE = re.compile(r"^Quality:\s*(\S+)\s*$", re.MULTILINE)
_SUMMARY_COUNT_RE = re.compile(r"^  (blockers|questions):\s*.+?$", re.MULTILINE)
_QUESTIONNAIRE_DONE_STATES = {"done", "answered", "complete", "verified", "promoted"}

_QUALITY_META: dict[str, tuple[str, str, str]] = {
    "Ready": ("ready", "✓", "All blockers resolved. Ready for planning."),
    "Questions": ("questions", "⚠", "Open questions remain. Planning can proceed."),
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
    discovery_paths: tuple[Path, ...]
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
    """Create ANALYZE_COMPASS.md with the default prompt if absent; never overwrite.

    The feedback file is a persistent, human-owned standing directive re-injected into every
    ``drydock analyze`` run. Returns the file's current text.
    """
    path = target_dir / _FEEDBACK_FILENAME
    if not path.is_file():
        header = prompt_header_for_file(_FEEDBACK_FILENAME)
        path.write_text(
            (header.default_text if header and header.default_text is not None else "# Analyze Compass\n"),
            encoding="utf-8",
            newline="\n",
        )
    return path.read_text(encoding="utf-8")


def _feedback_body(feedback_text: str | None) -> str:
    """Return only meaningful Analyze Compass guidance, without the stock heading."""
    if not feedback_text:
        return ""
    body = re.sub(r"^\s*# Analyze Compass\s*", "", feedback_text, count=1).strip()
    return body


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


def _render_existing_discoveries(questionnaires_dir: Path) -> list[str]:
    """Inject existing discovery questionnaires into the analyze prompt.

    The LLM must not re-emit a questionnaire whose filename already exists, and must treat
    questions with non-empty ``answer`` fields as settled decisions.
    """
    if not questionnaires_dir.is_dir():
        return []
    paths = sorted(questionnaires_dir.glob("discovery-*.json"))
    if not paths:
        return []
    parts = [
        "## Existing discovery questionnaires",
        "",
        "These were created by prior analyze runs and live in the target QuarterDeck.",
        "Rules:",
        "- Do not emit a discovery block whose filename already appears here.",
        "- Questions with a non-empty `answer` field are settled — do not re-raise them.",
        "- Generate new discovery-*.json blocks only for genuinely new open questions.",
        "",
    ]
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        parts += [f"### {path.name}", "", "```json", json.dumps(data, indent=2), "```", ""]
    return parts


def _managed_doc_parts(
    *,
    filename: str,
    content: str,
    content_heading: str,
    content_role: str,
    path: Path,
) -> list:
    header = prompt_header_for_file(filename)
    if header is None:
        return [
            fenced_markdown_part(
                filename,
                content_heading,
                content,
                role=content_role,
                path=path,
            )
        ]
    return [
        fenced_text_part(
            f"{filename} help",
            f"## {header.label} header",
            header.help_text,
            role="prompt header",
            path=path,
        ),
        fenced_text_part(
            f"{filename} prompt",
            f"## {header.label} instructions",
            header.prompt_text,
            role="prompt instructions",
            path=path,
        ),
        fenced_markdown_part(
            filename,
            content_heading,
            content,
            role=content_role,
            path=path,
        ),
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
            "Selectable stack options for discovery-stack.json. Names only — never open these files.",
            "",
            *[f"- {name}" for name in catalog],
            "",
        ]
    parts += ["## Imported source files", ""]
    for path in _collect_blueprint_files(blueprint_dir):
        label = path.relative_to(blueprint_dir).as_posix()
        parts += [
            f"### {prompt_source_header(label, path)}",
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
    questionnaires_dir: Path | None = None,
    compass_exists: bool,
    feedback_text: str | None = None,
    blockers_text: str | None = None,
    input_tokens: tuple[str, ...] | None = None,
) -> str:
    return _assemble_prompt_assembly(
        body,
        blueprint_dir,
        today,
        questionnaires_dir=questionnaires_dir,
        compass_exists=compass_exists,
        feedback_text=feedback_text,
        blockers_text=blockers_text,
        input_tokens=input_tokens,
    ).rendered_text


def _assemble_prompt_assembly(
    body: str,
    blueprint_dir: Path,
    today: str,
    *,
    questionnaires_dir: Path | None = None,
    compass_exists: bool,
    feedback_text: str | None = None,
    blockers_text: str | None = None,
    input_tokens: tuple[str, ...] | None = None,
) -> PromptAssembly:
    if input_tokens is None:
        input_tokens = load_prompt(PROMPT_NAME).input_tokens
    prompt_parts = [
        lines_part(
            "Analysis job",
            [
                "## Analysis job",
                "",
                f"- BLUEPRINT_PATH: {blueprint_dir}",
                f"- DATE: {today}",
                f"- COMPASS_EXISTS: {'true' if compass_exists else 'false'}",
                "",
            ],
            kind="job",
        )
    ]

    def feedback_parts() -> list:
        if not (feedback_text and feedback_text.strip()):
            return []
        return _managed_doc_parts(
            filename=_FEEDBACK_FILENAME,
            content=feedback_text.strip(),
            content_heading="## Analyze Compass content",
            content_role="analyze feedback",
            path=blueprint_dir.parent / _FEEDBACK_FILENAME,
        )

    def blocker_parts() -> list:
        if not blockers_text:
            return []
        return _managed_doc_parts(
            filename="BLOCKERS.md",
            content=blockers_text,
            content_heading="## Prior blocker answers (BLOCKERS.md)",
            content_role="prior blocker answers",
            path=blueprint_dir.parent / "BLOCKERS.md",
        )

    def discovery_parts() -> list:
        if questionnaires_dir is None or not questionnaires_dir.is_dir():
            return []
        paths = sorted(questionnaires_dir.glob("discovery-*.json"))
        if not paths:
            return []
        parts_list = [
            lines_part(
                "Existing discovery questionnaire header",
                [
                    "## Existing discovery questionnaires",
                    "",
                    "These were created by prior analyze runs and live in the target QuarterDeck.",
                    "Rules:",
                    "- Do not emit a discovery block whose filename already appears here.",
                    "- Questions with a non-empty `answer` field are settled — do not re-raise them.",
                    "- Generate new discovery-*.json blocks only for genuinely new open questions.",
                    "",
                ],
                kind="section",
            )
        ]
        for path_obj in paths:
            try:
                data = json.loads(path_obj.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            parts_list.append(
                part(
                    path_obj.name,
                    "\n".join(
                        [
                            f"### {path_obj.name}",
                            "",
                            "```json",
                            json.dumps(data, indent=2),
                            "```",
                            "",
                        ]
                    ),
                    kind="file",
                    role="questionnaire",
                    path=path_obj,
                )
            )
        return parts_list

    def typed_spec_parts() -> list:
        parts_list = []
        catalog = _rigging_catalog_names()
        if catalog:
            parts_list.append(
                lines_part(
                    "Rigging catalog",
                    [
                        "## Rigging catalog (filenames only)",
                        "",
                        "Selectable stack options for discovery-stack.json. Names only — never open these files.",
                        "",
                        *[f"- {name}" for name in catalog],
                        "",
                    ],
                    kind="section",
                )
            )
        parts_list.append(lines_part("Imported source file header", ["## Imported source files", ""], kind="section"))
        for path_obj in _collect_blueprint_files(blueprint_dir):
            label = path_obj.relative_to(blueprint_dir).as_posix()
            parts_list.append(
                fenced_markdown_part(
                    label,
                    f"### {prompt_source_header(label, path_obj)}",
                    path_obj.read_text(encoding="utf-8"),
                    role="source file",
                    path=path_obj,
                )
            )
        return parts_list

    renderers: dict[str, Callable[[], list]] = {
        "ANALYZE_COMPASS.md": feedback_parts,
        "BLOCKERS.md": blocker_parts,
        "EXISTING_SPIKES": discovery_parts,
        "TYPED_SPEC": typed_spec_parts,
    }
    for token in input_tokens:
        render = renderers.get(token)
        if render is None:
            continue
        prompt_parts.extend(render())
    prompt_parts.append(part("Prompt body", "\n" + body, kind="prompt-body"))
    return PromptAssembly(parts=tuple(prompt_parts))


def _parse_blocks(text: str) -> dict[str, str]:
    """Return a dict of block-name → stripped content from model output.

    Preferred format is the documented ``=== NAME ===`` block contract. As a recovery path for
    Claude responses that ignore the contract and instead emit a ``Write`` tool transcript, accept
    ``<invoke name="Write">`` records and map them by basename only. Drydock still performs the
    actual file writes deterministically.
    """
    blocks = {m.group(1): m.group(2).strip() for m in _BLOCK_RE.finditer(text)}
    if blocks:
        return blocks

    recovered: dict[str, str] = {}
    for match in _WRITE_INVOKE_RE.finditer(text):
        name = Path(match.group(1).strip()).name
        content = match.group(2).strip()
        if name:
            recovered[name] = content
    return recovered


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


def _remove_open_questions_section(analysis_text: str) -> str:
    """Remove duplicated question content from ANALYSIS.md.

    Open questions are rendered as QuarterDeck questionnaire action items. Keeping the same list
    in ANALYSIS.md creates duplicate review tabs, so analysis output is normalized here before
    being persisted.
    """
    return _OPEN_QUESTIONS_SECTION_RE.sub("", analysis_text).strip()


def _remove_tuning_options_section(analysis_text: str) -> str:
    """Remove decomposition-option prose from ANALYSIS.md.

    Human-owned choices belong in questionnaires or standing directives, not in the analysis
    artifact itself.
    """
    return _TUNING_OPTIONS_SECTION_RE.sub("", analysis_text).strip()


def _normalize_analysis_summary(analysis_text: str, *, quality: str, blockers: int, questions: int) -> str:
    """Rewrite summary fields to match the artifacts Drydock actually wrote."""
    text = _SUMMARY_QUALITY_RE.sub(f"Quality: {quality}", analysis_text, count=1)

    def repl(match: re.Match[str]) -> str:
        field = match.group(1)
        if field == "blockers":
            return f"  blockers: {blockers}"
        return f"  questions: {questions}"

    return _SUMMARY_COUNT_RE.sub(repl, text)


def _count_open_discoveries(questionnaires_dir: Path) -> int:
    """Count visible open discovery questionnaires backed by files on disk."""
    if not questionnaires_dir.is_dir():
        return 0
    count = 0
    for path in questionnaires_dir.glob("discovery-*.json"):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("archived", False):
            continue
        if str(data.get("state", "open")) in _QUESTIONNAIRE_DONE_STATES:
            continue
        count += 1
    return count


def _parse_output(
    text: str,
) -> tuple[str, str, str, str | None, str | None, dict[str, dict], str, dict[str, str]]:
    """Return (analysis, sea_trials, soundings, compass_or_none, blockers_or_none, discoveries,
    quality, summary).

    ``summary`` contains parsed sub-fields: blockers, questions, stories, stack, screens.
    Questionnaires (``discovery-*.json``) and ``BLOCKERS.md`` are emitted dynamically — only when
    the analysis surfaces an open question or a blocker — so none of them are required.
    Raises ValueError on missing required blocks or invalid JSON.
    """
    blocks = _parse_blocks(text)

    for required in ("ANALYSIS.md", "SEA_TRIALS.md", "SOUNDINGS.md"):
        if required not in blocks:
            raise ValueError(f"LLM output missing === {required} === block")

    discoveries: dict[str, dict] = {}
    for name, content in blocks.items():
        if name.startswith("discovery-") and name.endswith(".json"):
            try:
                discoveries[name] = json.loads(content)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{name} block is not valid JSON: {exc}") from exc

    analysis_text = _remove_open_questions_section(blocks["ANALYSIS.md"])
    analysis_text = _remove_tuning_options_section(analysis_text)
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
        discoveries,
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
        return f"Review QuarterDeck action items, then run: drydock plan {target}"
    return f"drydock plan {target}"


def analyze(
    target: str,
    target_dir: Path,
    *,
    runner: RunnerFn | None = None,
    on_text: TextCallback | None = None,
    model: str | None = None,
    llm_provider: str | None = None,
    log_dir: Path | None = None,
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
    feedback_for_prompt = _feedback_body(feedback_text) or None

    run = runner if runner is not None else run_prompt
    prompt = load_prompt(PROMPT_NAME)
    today = date.today().isoformat()
    prompt_assembly = _assemble_prompt_assembly(
        prompt.body,
        blueprint_dir,
        today,
        questionnaires_dir=questionnaires_dir,
        compass_exists=compass_exists,
        feedback_text=feedback_for_prompt,
        blockers_text=blockers_text,
        input_tokens=prompt.input_tokens,
    )

    result = run(
        prompt_assembly.rendered_text,
        target_dir,
        llm=llm_provider,
        model=model,
        command_name="analyze",
        parameters={"target": target, "blueprint": str(blueprint_dir)},
        log_dir=log_dir,
        target=target,
        on_text=on_text,
        prompt_assembly=prompt_assembly,
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
            discovery_paths=(),
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
            discoveries,
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
    blocker_count = _safe_int("blockers")
    screen_count = _safe_int("screens")
    stack = summary.get("stack", "not declared")

    # Backfill stack into METADATA.md if the LLM identified it and the field is still blank.
    if stack and stack != "not declared":
        set_field(target_dir / METADATA_NAME, "stack", stack, overwrite=False)

    questionnaires_dir.mkdir(parents=True, exist_ok=True)

    analysis_path.write_text(analysis_text + "\n", encoding="utf-8", newline="\n")
    sea_trials_path.write_text(sea_trials_text + "\n", encoding="utf-8", newline="\n")
    soundings_path.write_text(soundings_text + "\n", encoding="utf-8", newline="\n")

    written_compass: Path | None = None
    if compass_text and not compass_exists:
        compass_target.write_text(compass_text + "\n", encoding="utf-8", newline="\n")
        written_compass = compass_target

    discovery_paths: list[Path] = []
    for name, data in discoveries.items():
        discovery_path = questionnaires_dir / name
        if discovery_path.exists():
            continue  # never overwrite an existing questionnaire; answers must not be destroyed
        discovery_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
        discovery_paths.append(discovery_path)

    # BLOCKERS.md — written only when _validate_blockers accepted a genuine, structured block.
    # Its presence is the flag that halts the pipeline; written when present, deleted otherwise
    # (resolved, empty, or placeholder). Never trust block-presence alone — fail closed.
    written_blockers: Path | None = None
    if blockers_text_out:
        blockers_md_path.write_text(blockers_text_out + "\n", encoding="utf-8", newline="\n")
        written_blockers = blockers_md_path
    elif blockers_md_path.is_file():
        blockers_md_path.unlink()

    question_count = _count_open_discoveries(questionnaires_dir)
    blocker_count = 1 if written_blockers else 0
    quality = "Blocked" if blocker_count else ("Questions" if question_count else "Ready")
    analysis_text = _normalize_analysis_summary(
        analysis_text,
        quality=quality,
        blockers=blocker_count,
        questions=question_count,
    )
    analysis_path.write_text(analysis_text + "\n", encoding="utf-8", newline="\n")

    # Lifecycle state, sub-state, and date stamp — always written on success.
    stamp_last(target_dir, "analyzed")
    set_sub_state(target_dir, "complete")

    # Captain's Chair — only when build_state advances to "analyzed".
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
        discovery_paths=tuple(sorted(discovery_paths)),
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
