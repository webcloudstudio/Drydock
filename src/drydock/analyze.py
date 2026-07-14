"""``drydock analyze`` — Scrum-team Blueprint analysis: quality signal, story list, artifacts.

Single LLM call producing all analyze outputs via delimited blocks. Writes deterministically;
tests inject a fake runner and never spend API credits.

Outputs: ANALYSIS.md (target root), SEA_TRIALS.md, SOUNDINGS.md, COMPASS.md (if absent or
unpopulated), BLOCKERS.md (only when blockers exist), discovery-*.json questionnaires (one per
open question), commanders_chair.html (when lifecycle state advances to analyzed).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from drydock.artifact_blocks import parse_artifact_blocks
from drydock.compass_sources import (
    clear_compass_import_pending,
    compass_import_pending,
    seed_compass_from_sources,
)
from drydock.errors import DrydockError, SpecificationError
from drydock.exclude_files import (
    append_suggested_exclusions,
    ensure_exclude_file,
    load_excluded_filenames,
)
from drydock.llm import run_prompt
from drydock.metadata import (
    METADATA_NAME,
    parse_metadata,
    set_build_state,
    set_field,
    set_sub_state,
    stamp_last,
)
from drydock.paths import get_rigging_root
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
from drydock.standard_artifacts import Sounding, render_soundings

PROMPT_NAME = "analyze"

_SOURCES_SUBDIR = "sources"

_FEEDBACK_FILENAME = "ANALYZE_COMPASS.md"

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
_ANALYSIS_NOTES_HEADING_RE = re.compile(
    r"^## (?:Analysis notes|Notes)\s*$", re.MULTILINE | re.IGNORECASE
)
_QUESTIONNAIRE_DONE_STATES = {"done", "answered", "complete", "verified", "promoted"}


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
    commanders_chair_path: Path | None
    discovery_paths: tuple[Path, ...]
    quality: str
    story_count: int
    feature_count: int
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


def _parse_blocks(text: str) -> dict[str, str]:
    """Parse strict analyze artifact blocks."""
    return parse_artifact_blocks(text, label="Analyze")


def _collect_blueprint_files(
    blueprint_dir: Path, *, excluded_filenames: frozenset[str] = frozenset()
) -> list[Path]:
    """Return imported source files from blueprint/sources/ for analysis."""
    sources_dir = blueprint_dir / _SOURCES_SUBDIR
    if not sources_dir.is_dir():
        return []
    return sorted(
        p for p in sources_dir.rglob("*.md") if p.is_file() and p.name not in excluded_filenames
    )


def ensure_feedback_file(target_dir: Path) -> str:
    """Create ANALYZE_COMPASS.md with the default prompt if absent; never overwrite.

    The feedback file is a persistent, human-owned standing directive re-injected into every
    ``drydock analyze`` run. Returns the file's current text.
    """
    path = target_dir / _FEEDBACK_FILENAME
    if not path.is_file():
        header = prompt_header_for_file(_FEEDBACK_FILENAME)
        path.write_text(
            (
                header.default_text
                if header and header.default_text is not None
                else "# Analyze Compass\n"
            ),
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


_DEFAULT_STACK_CATEGORY = "Technologies"
_STACK_CATEGORY_ORDER = ["Web Server", "Persistence", "AWS", "Technologies", "Branding"]
_CATEGORY_HEADER = re.compile(r"^\*\*Category:\*\*\s*(.+?)\s*$", re.MULTILINE)


def _stack_option_category(path: Path) -> str:
    """Read the ``**Category:**`` header from a Rigging file's header block.

    Only the first 20 lines are scanned — the header block sits at the top of every
    Rigging file. Files without the header fall into the default category.
    """
    try:
        head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:20])
    except OSError:
        return _DEFAULT_STACK_CATEGORY
    match = _CATEGORY_HEADER.search(head)
    return match.group(1) if match else _DEFAULT_STACK_CATEGORY


def _rigging_catalog() -> list[tuple[str, str]]:
    """Return ``(filename, category)`` pairs for the stack questionnaire options.

    Source: ``Rigging/BRA*.md`` plus ``Rigging/stack/*.md``, excluding ``README.md``
    and ``_compact`` variants. Categories come from each file's ``**Category:**``
    header; only the tooling opens these files, never the analyze LLM.
    """
    try:
        root = get_rigging_root()
    except Exception:
        return []
    paths = [p for p in root.glob("BRA*.md") if "_compact" not in p.name]
    paths += [p for p in (root / "stack").glob("*.md") if "_compact" not in p.name]
    return sorted((p.name, _stack_option_category(p)) for p in paths if p.name != "README.md")


def _rigging_catalog_names() -> list[str]:
    """Return the stack-option filenames offered to the stack questionnaire."""
    return [name for name, _ in _rigging_catalog()]


def _default_stack_questionnaire() -> dict:
    """Return the canonical stack questionnaire shell.

    Options and groups are filled by ``_normalize_discovery``; analyze writes this
    whenever the LLM did not emit a ``discovery-stack.json`` of its own.
    """
    return {
        "id": "discovery-stack",
        "title": "Discovery: Technology Stack",
        "purpose": "Select the stack guidance components that apply before planning.",
        "questions": [
            {
                "id": "stack_components",
                "label": "Stack Components",
                "prompt": (
                    "Select all Rigging stack guidance components that apply. "
                    "Leave blank when undecided."
                ),
                "input": "checkbox_grid",
                "options": [],
                "answer": "",
            }
        ],
        "state": "open",
    }


def _stack_option_groups(catalog: list[tuple[str, str]]) -> list[dict]:
    """Group catalog options by category for the stack questionnaire.

    Known categories render in ``_STACK_CATEGORY_ORDER``; unknown categories follow
    alphabetically. A trailing ``Other`` group carries the free-choice ``other`` option.
    """
    by_category: dict[str, list[str]] = {}
    for name, category in catalog:
        by_category.setdefault(category, []).append(name)
    ordered = [c for c in _STACK_CATEGORY_ORDER if c in by_category]
    ordered += sorted(c for c in by_category if c not in _STACK_CATEGORY_ORDER)
    groups = [{"label": c, "options": sorted(by_category[c])} for c in ordered]
    groups.append({"label": "Other", "options": ["other"]})
    return groups


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
        non_heading_content = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        return not non_heading_content
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


def _render_typed_spec(
    blueprint_dir: Path, *, excluded_filenames: frozenset[str] = frozenset()
) -> list[str]:
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
    for path in _collect_blueprint_files(blueprint_dir, excluded_filenames=excluded_filenames):
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
    compass_pending_format: bool = False,
    compass_content: str | None = None,
    feedback_text: str | None = None,
    blockers_text: str | None = None,
    input_tokens: tuple[str, ...] | None = None,
    identity: dict[str, str] | None = None,
) -> str:
    return _assemble_prompt_assembly(
        body,
        blueprint_dir,
        today,
        questionnaires_dir=questionnaires_dir,
        compass_exists=compass_exists,
        compass_pending_format=compass_pending_format,
        compass_content=compass_content,
        feedback_text=feedback_text,
        blockers_text=blockers_text,
        input_tokens=input_tokens,
        excluded_filenames=load_excluded_filenames(blueprint_dir.parent),
        identity=identity,
    ).rendered_text


def _assemble_prompt_assembly(
    body: str,
    blueprint_dir: Path,
    today: str,
    *,
    questionnaires_dir: Path | None = None,
    compass_exists: bool,
    compass_pending_format: bool = False,
    compass_content: str | None = None,
    feedback_text: str | None = None,
    blockers_text: str | None = None,
    input_tokens: tuple[str, ...] | None = None,
    excluded_filenames: frozenset[str] = frozenset(),
    identity: dict[str, str] | None = None,
) -> PromptAssembly:
    if input_tokens is None:
        input_tokens = load_prompt(PROMPT_NAME).input_tokens
    _id = identity or {}
    _display_name = _id.get("display_name", "").strip() or "(blank)"
    _short_desc = _id.get("short_description", "").strip() or "(blank)"
    prompt_parts = [
        system_preamble_part(),
        section_heading_part("# Input Context"),
        lines_part(
            "Analysis job",
            [
                "## Analysis job",
                "",
                f"- BLUEPRINT_PATH: {blueprint_dir}",
                f"- DATE: {today}",
                f"- COMPASS_EXISTS: {'true' if compass_exists else 'false'}",
                f"- COMPASS_PENDING_FORMAT: {'true' if compass_pending_format else 'false'}",
                f"- DISPLAY_NAME: {_display_name}",
                f"- SHORT_DESCRIPTION: {_short_desc}",
                "",
            ],
            kind="job",
        ),
    ]

    def feedback_parts() -> list:
        if not (feedback_text and feedback_text.strip()):
            return []
        return _managed_doc_parts(
            filename=_FEEDBACK_FILENAME,
            content=feedback_text.strip(),
            content_role="analyze feedback",
            path=blueprint_dir.parent / _FEEDBACK_FILENAME,
        )

    def compass_parts() -> list:
        if not (compass_pending_format and compass_content and compass_content.strip()):
            return []
        return _managed_doc_parts(
            filename="COMPASS.md",
            content=compass_content.strip(),
            content_role="imported compass pending normalization",
            path=blueprint_dir.parent / "COMPASS.md",
        )

    def blocker_parts() -> list:
        if not blockers_text:
            return []
        return _managed_doc_parts(
            filename="BLOCKERS.md",
            content=blockers_text,
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
        parts_list.append(
            lines_part(
                "Imported source file header", ["## Imported source files", ""], kind="section"
            )
        )
        for path_obj in _collect_blueprint_files(
            blueprint_dir, excluded_filenames=excluded_filenames
        ):
            label = path_obj.relative_to(blueprint_dir).as_posix()
            parts_list.extend(
                contextual_markdown_parts(
                    label,
                    path_obj.read_text(encoding="utf-8"),
                    filename=path_obj.name,
                    role="source file",
                    path=path_obj,
                )
            )
        return parts_list

    renderers: dict[str, Callable[[], list]] = {
        "COMPASS.md": compass_parts,
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
    prompt_parts.append(section_heading_part("# Agent Task"))
    prompt_parts.append(part("Prompt body", "\n" + body, kind="prompt-body"))
    return PromptAssembly(parts=tuple(prompt_parts))


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


def _normalize_analysis_summary(
    analysis_text: str, *, quality: str, blockers: int, questions: int
) -> str:
    """Rewrite summary fields to match the artifacts Drydock actually wrote."""
    text = _SUMMARY_QUALITY_RE.sub(f"Quality: {quality}", analysis_text, count=1)

    def repl(match: re.Match[str]) -> str:
        field = match.group(1)
        if field == "blockers":
            return f"  blockers: {blockers}"
        return f"  questions: {questions}"

    return _SUMMARY_COUNT_RE.sub(repl, text)


def _normalize_analysis_layout(analysis_text: str) -> str:
    """Move the generated summary out of the tab preamble and into Analysis Notes."""
    text = _ANALYSIS_NOTES_HEADING_RE.sub("## Analysis Notes", analysis_text.strip())
    match = re.match(
        r"(?s)\A(#[^\n]*(?:\n|$))(?P<intro>.*?)(?=^## |\Z)(?P<body>.*)\Z", text, re.MULTILINE
    )
    if not match:
        return text

    title = match.group(1).strip()
    intro = match.group("intro").strip()
    body = match.group("body").strip()
    if not intro:
        return "\n\n".join(part for part in (title, body) if part)

    notes_match = re.search(
        r"(?ms)^## Analysis Notes\s*$(?P<notes>.*?)(?=^## |\Z)",
        body,
    )
    if notes_match:
        notes = notes_match.group("notes").strip()
        replacement = "## Analysis Notes\n\n" + intro
        if notes:
            replacement += "\n\n" + notes
        body = body[: notes_match.start()] + replacement + body[notes_match.end() :]
    else:
        body = "\n\n".join(part for part in (body, "## Analysis Notes\n\n" + intro) if part)

    return "\n\n".join(part for part in (title, body.strip()) if part)


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


def _normalize_discovery(name: str, data: dict) -> dict:
    """Normalize generated discovery JSON before persisting it.

    The prompt is advisory; the persisted questionnaire is the contract consumed by
    QuarterDeck and plan creation.
    """
    normalized = dict(data)
    questions = []
    for raw_question in normalized.get("questions", []):
        question = dict(raw_question)
        # A choice input without options is unanswerable — degrade to free text.
        if question.get("input") in ("select", "multiselect", "checkbox_grid") and not question.get(
            "options"
        ):
            if name != "discovery-stack.json":  # stack options are filled below
                question["input"] = "textarea"
        if name == "discovery-identity.json":
            proposed = str(question.get("proposed", "")).strip()
            if proposed and not str(question.get("answer", "")).strip():
                question["answer"] = proposed
        if name == "discovery-stack.json":
            question["input"] = "checkbox_grid"
            catalog = _rigging_catalog()
            if catalog:
                # The option list is deterministic: the full Rigging catalog grouped by
                # category, regardless of what the LLM emitted. The LLM must not filter
                # the choices offered to the Commander.
                question["options"] = [name_ for name_, _ in catalog] + ["other"]
                question["groups"] = _stack_option_groups(catalog)
            else:
                options = question.get("options", [])
                if isinstance(options, list):
                    question["options"] = sorted(str(option) for option in options)
            question.setdefault("answer", "")
        questions.append(question)
    normalized["questions"] = questions
    return normalized


def _normalize_cell(value: str) -> str:
    return " ".join(value.split())


def _split_markdown_row(line: str) -> list[str]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [_normalize_cell(cell.replace(r"\|", "|")) for cell in re.split(r"(?<!\\)\|", text)]


def _soundings_from_analysis(analysis_text: str) -> str:
    rows: list[Sounding] = []
    lines = analysis_text.splitlines()
    for index, line in enumerate(lines):
        cells = _split_markdown_row(line) if "|" in line else []
        normalized = [cell.lower() for cell in cells]
        if normalized[:3] != ["id", "story", "high-level ac"]:
            continue
        cursor = index + 2
        while cursor < len(lines):
            row_line = lines[cursor]
            if not row_line.strip() or row_line.startswith("## "):
                break
            row = _split_markdown_row(row_line) if "|" in row_line else []
            if len(row) >= 3 and row[0] and row[2]:
                rows.append(Sounding(row[0], row[2], "NOT STARTED", ""))
            cursor += 1
    if not rows:
        rows.append(
            Sounding(
                "analysis-acceptance", "Acceptance criteria are identified.", "NOT STARTED", ""
            )
        )
    return render_soundings(rows)


def _parse_output(
    text: str,
) -> tuple[str, str, str, str | None, str | None, dict[str, dict], str, dict[str, str]]:
    """Return (analysis, sea_trials, soundings, compass_or_none, blockers_or_none, discoveries,
    quality, summary).

    ``summary`` contains parsed sub-fields: blockers, questions, stories, stack, features.
    Questionnaires (``discovery-*.json``) and ``BLOCKERS.md`` are emitted dynamically — only when
    the analysis surfaces an open question or a blocker — so none of them are required.
    Raises ValueError on missing required blocks or invalid JSON.
    """
    blocks = parse_artifact_blocks(
        text,
        label="Analyze",
        allowed_names={"ANALYSIS.md", "SEA_TRIALS.md", "SOUNDINGS.md", "BLOCKERS.md", "COMPASS.md"},
        allowed_prefixes=("discovery-",),
    )

    for required in ("ANALYSIS.md", "SEA_TRIALS.md"):
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
    analysis_text = _normalize_analysis_layout(analysis_text)
    compass_content = blocks.get("COMPASS.md") or None
    blockers_content = _validate_blockers(blocks.get("BLOCKERS.md"))

    return (
        analysis_text,
        blocks["SEA_TRIALS.md"],
        _soundings_from_analysis(analysis_text),
        compass_content,
        blockers_content,
        discoveries,
        quality,
        summary,
    )


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

    source_files = _collect_blueprint_files(blueprint_dir)
    seed_compass_from_sources(
        target_dir,
        source_files,
        overwrite_unpopulated=not compass_target.is_file()
        or _is_compass_unpopulated(compass_target),
    )

    # COMPASS is (re)written when absent or when the existing file is an unpopulated template.
    compass_pending = compass_import_pending(target_dir)
    compass_exists = compass_target.is_file() and not _is_compass_unpopulated(compass_target)
    compass_content = (
        compass_target.read_text(encoding="utf-8") if compass_target.is_file() else None
    )

    # Inject prior blocker answers if the Commander has filled in BLOCKERS.md.
    blockers_md_path = target_dir / "BLOCKERS.md"
    blockers_text = (
        blockers_md_path.read_text(encoding="utf-8") if blockers_md_path.is_file() else None
    )

    # Standing-directive feedback file — created if absent, never overwritten, injected when the
    # user has edited it beyond the default placeholder.
    feedback_text = ensure_feedback_file(target_dir)
    feedback_for_prompt = _feedback_body(feedback_text) or None
    ensure_exclude_file(target_dir)
    append_suggested_exclusions(target_dir, source_files)
    excluded_filenames = load_excluded_filenames(target_dir)

    run = runner if runner is not None else run_prompt
    prompt = load_prompt(PROMPT_NAME)
    today = date.today().isoformat()
    metadata_fields = parse_metadata(target_dir / METADATA_NAME)
    identity = {
        "display_name": metadata_fields.get("display_name", ""),
        "short_description": metadata_fields.get("short_description", ""),
    }
    prompt_assembly = _assemble_prompt_assembly(
        prompt.body,
        blueprint_dir,
        today,
        questionnaires_dir=questionnaires_dir,
        compass_exists=compass_exists,
        compass_pending_format=compass_pending,
        compass_content=compass_content,
        feedback_text=feedback_for_prompt,
        blockers_text=blockers_text,
        input_tokens=prompt.input_tokens,
        excluded_filenames=excluded_filenames,
        identity=identity,
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
            commanders_chair_path=None,
            discovery_paths=(),
            quality="unknown",
            story_count=0,
            feature_count=0,
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
    except (DrydockError, ValueError) as exc:
        return _fail(str(exc))

    if compass_pending and not compass_text:
        return _fail("Imported COMPASS.md was not normalized by analyze output")

    def _safe_int(key: str) -> int:
        try:
            return int(summary.get(key, "0"))
        except (ValueError, TypeError):
            return 0

    story_count = _safe_int("stories")
    feature_count = _safe_int("features")
    blocker_count = _safe_int("blockers")
    screen_count = feature_count or _safe_int("screens")
    stack = summary.get("stack", "not declared")

    # Backfill stack into METADATA.md only when the LLM committed to a concrete value.
    # Prose like "not declared (Python / Node.js / Go...)" must not be written.
    if stack and not stack.startswith("not declared") and " " not in stack.strip():
        set_field(target_dir / METADATA_NAME, "stack", stack, overwrite=False)

    # Backfill display_name and short_description from proposed summary values when blank.
    _NOT_PROPOSED = frozenset({"not proposed", "not declared", "unknown"})
    proposed_display_name = summary.get("display_name", "").strip()
    if proposed_display_name and proposed_display_name not in _NOT_PROPOSED:
        set_field(
            target_dir / METADATA_NAME, "display_name", proposed_display_name, overwrite=False
        )
    proposed_short_desc = summary.get("short_description", "").strip()
    if proposed_short_desc and proposed_short_desc not in _NOT_PROPOSED:
        set_field(
            target_dir / METADATA_NAME, "short_description", proposed_short_desc, overwrite=False
        )

    questionnaires_dir.mkdir(parents=True, exist_ok=True)

    analysis_path.write_text(analysis_text + "\n", encoding="utf-8", newline="\n")
    sea_trials_path.write_text(sea_trials_text + "\n", encoding="utf-8", newline="\n")
    soundings_path.write_text(soundings_text + "\n", encoding="utf-8", newline="\n")

    written_compass: Path | None = None
    if compass_text and (not compass_exists or compass_pending):
        compass_target.write_text(compass_text + "\n", encoding="utf-8", newline="\n")
        clear_compass_import_pending(target_dir)
        written_compass = compass_target

    discovery_paths: list[Path] = []
    for name, data in discoveries.items():
        discovery_path = questionnaires_dir / name
        if discovery_path.exists():
            continue  # never overwrite an existing questionnaire; answers must not be destroyed
        data = _normalize_discovery(name, data)
        discovery_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
        discovery_paths.append(discovery_path)

    # The stack questionnaire always exists after analyze — its content is deterministic
    # (the full Rigging catalog), so it never depends on the LLM choosing to emit it.
    stack_path = questionnaires_dir / "discovery-stack.json"
    if not stack_path.exists():
        stack_data = _normalize_discovery("discovery-stack.json", _default_stack_questionnaire())
        stack_path.write_text(
            json.dumps(stack_data, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        discovery_paths.append(stack_path)

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

    # Commanders Chair reflects the current analyzed state; delegate to shared builder.
    set_build_state(target_dir, "analyzed")
    from drydock.quarterdeck_state import refresh_commanders_chair as _refresh_chair

    commanders_chair_path = _refresh_chair(target_dir)

    return AnalyzeResult(
        target_dir=target_dir,
        analysis_path=analysis_path,
        sea_trials_path=sea_trials_path,
        soundings_path=soundings_path,
        compass_path=written_compass,
        commanders_chair_path=commanders_chair_path,
        discovery_paths=tuple(sorted(discovery_paths)),
        quality=quality,
        story_count=story_count,
        feature_count=feature_count,
        question_count=question_count,
        blocker_count=blocker_count,
        screen_count=screen_count,
        stack=stack,
        execution_id=exec_id,
        ok=True,
        blockers_path=written_blockers,
    )
