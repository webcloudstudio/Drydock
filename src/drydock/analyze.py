"""``drydock analyze`` — Scrum-team Blueprint analysis: quality signal, story list, artifacts.

Single LLM call producing all analyze outputs via delimited blocks. Writes deterministically;
tests inject a fake runner and never spend API credits.

Outputs: ANALYSIS.md (target root), SEA_TRIALS.md, COMPASS.md (if absent or unpopulated),
BLOCKERS.md (only when blockers exist), discovery-*.json questionnaires (one per open question),
commanders_chair.html (when lifecycle state advances to analyzed).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from drydock import technology_stack
from drydock.artifact_blocks import parse_artifact_blocks
from drydock.compass_sources import (
    clear_compass_import_pending,
    compass_import_pending,
    seed_compass_from_sources,
)
from drydock.errors import DrydockError, SpecificationError, clear_error_record
from drydock.exclude_files import (
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
from drydock.sea_trials import (
    commander_sea_trials,
    normalize_sea_trials_text,
    parse_sea_trials_text,
    project_questions,
)
from drydock.source_material import (
    SourceMaterialFile,
    discover_source_material,
    inventory_markdown,
    withheld_content_warning,
)

PROMPT_NAME = "analyze"

#: Projected from the SEA_TRIALS.md Questions section by this module; the LLM never emits it.
SEA_TRIALS_QUESTIONNAIRE = "discovery-sea-trials.json"

_SOURCES_SUBDIR = "sources"

_FEEDBACK_FILENAME = "ANALYZE_COMPASS.md"

_QUALITY_RE = re.compile(r"^Quality:\s*(\S+)", re.MULTILINE)
_SUMMARY_FIELD_RE = re.compile(r"^  (\w+):\s*(.+?)$", re.MULTILINE)
# A genuine BLOCKERS.md block carries at least one "## " blocker entry (see prompts/analyze.md).
_BLOCKER_ENTRY_RE = re.compile(r"^## \S", re.MULTILINE)
_BLOCKER_ID_RE = re.compile(r"^##\s+(?P<id>[A-Za-z0-9][A-Za-z0-9_-]*)\s*:", re.MULTILINE)
_BLOCKER_SECTION_RE = re.compile(
    r"^##\s+(?P<id>[A-Za-z0-9][A-Za-z0-9_-]*)\s*:\s*(?P<title>.*?)\s*$"
    r"\n?(?P<body>.*?)(?=^##\s|\Z)",
    re.MULTILINE | re.DOTALL,
)
_COMMANDER_RESOLUTION_RE = re.compile(
    r"^### Commander Resolution\s*$\n?(?P<answer>.*)\Z", re.MULTILINE | re.DOTALL
)
_RESOLVED_BLOCKERS_SECTION_RE = re.compile(
    r"^## Resolved Blockers\s*$.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL
)
_RESOLUTION_PLACEHOLDER = (
    "<!-- Enter the decision that resolves this blocker, then re-run Analyze. -->"
)
_OPEN_QUESTIONS_SECTION_RE = re.compile(
    r"^## Questions\s*$.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL
)
_TUNING_OPTIONS_SECTION_RE = re.compile(
    r"^### Tuning Options\s*$.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL
)
_SUMMARY_QUALITY_RE = re.compile(r"^Quality:\s*(\S+)\s*$", re.MULTILINE)
_SUMMARY_COUNT_RE = re.compile(r"^  (blockers|questions):\s*.+?$", re.MULTILINE)
_ANALYSIS_NOTES_HEADING_RE = re.compile(
    r"^## (?:Analysis notes|Notes)\s*$", re.MULTILINE | re.IGNORECASE
)
_QUESTIONNAIRE_DONE_STATES = {"done", "answered", "approved", "complete", "verified", "promoted"}
_SEA_TRIALS_BLOCKER_ID = "blocker-sea-trials"


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
    warnings: tuple[str, ...] = ()
    sea_trials_created: bool = True

    def exit_code(self) -> int:
        return 0 if self.ok else 1


@dataclass(frozen=True)
class BlockerRecord:
    blocker_id: str
    title: str
    full_text: str
    original_text: str
    resolution: str | None
    has_resolution_field: bool


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
    return [
        entry.path
        for entry in discover_source_material(blueprint_dir, excluded_filenames=excluded_filenames)
        if entry.path.suffix.lower() == ".md" and entry.text is not None
    ]


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


def _rigging_manifest() -> str:
    """Return the compact Rigging selection catalog injected into Analyze."""
    try:
        path = get_rigging_root() / "MANIFEST.md"
    except Exception:
        return ""
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


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


#: Header for the existing-questionnaire prompt block. Answered questionnaires are Commander
#: guidance carried across every later run: analyze consumes them as input and never rewrites
#: them, so re-running analyze cannot cost the Commander an answer.
EXISTING_QUESTIONNAIRE_HEADER = (
    "## Existing discovery questionnaires",
    "",
    "These live in the target QuarterDeck and are Commander-owned input to this run.",
    "Rules:",
    "- Do not emit a discovery block whose filename already appears here.",
    "- `answer`, `resolution`, and `additional_notes` values are Commander decisions and are",
    "  authoritative — apply them to the analysis and never re-raise or contradict them.",
    "- Generate new discovery-*.json blocks only for genuinely new open questions.",
    "",
)


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
    # The Rigging catalog (filenames, no content) is analyze scaffolding that reads
    # immediately before the imported sources it contextualizes.
    parts: list[str] = []
    catalog = technology_stack.rigging_names()
    if catalog:
        parts += [
            "## Rigging catalog (filenames only)",
            "",
            f"Available Rigging files for the Rigging column of {technology_stack.FILENAME}. "
            "Names only — never open these files.",
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
                list(EXISTING_QUESTIONNAIRE_HEADER),
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

    def sea_trials_parts() -> list:
        path_obj = blueprint_dir.parent / "SEA_TRIALS.md"
        if not path_obj.is_file():
            return []
        return _managed_doc_parts(
            filename="SEA_TRIALS.md",
            content=path_obj.read_text(encoding="utf-8"),
            content_role="prior project acceptance contract; preserve stable IDs",
            path=path_obj,
        )

    def typed_spec_parts() -> list:
        parts_list = []
        parts_list.append(
            lines_part(
                "Imported source file header", ["## Imported source files", ""], kind="section"
            )
        )
        source_material = discover_source_material(blueprint_dir)
        parts_list.append(
            lines_part(
                "Source material inventory",
                inventory_markdown(source_material).splitlines() + [""],
                kind="section",
            )
        )
        for entry in source_material:
            if entry.path.name in excluded_filenames:
                continue
            for index, chunk in enumerate(entry.prompt_chunks, start=1):
                suffix = (
                    f" (chunk {index}/{len(entry.prompt_chunks)})"
                    if len(entry.prompt_chunks) > 1
                    else ""
                )
                parts_list.extend(
                    contextual_fenced_parts(
                        entry.relative_path + suffix,
                        chunk,
                        filename=entry.relative_path,
                        fence=entry.fence,
                        role="source file",
                        path=entry.path,
                    )
                )
        return parts_list

    def rigging_manifest_parts() -> list:
        manifest = _rigging_manifest()
        if not manifest:
            return []
        return _managed_doc_parts(
            filename="MANIFEST.md",
            content=manifest,
            content_role="Rigging stack selection catalog",
            path=get_rigging_root() / "MANIFEST.md",
        )

    renderers: dict[str, Callable[[], list]] = {
        "COMPASS.md": compass_parts,
        "ANALYZE_COMPASS.md": feedback_parts,
        "BLOCKERS.md": blocker_parts,
        "SEA_TRIALS.md": sea_trials_parts,
        "EXISTING_SPIKES": discovery_parts,
        "RIGGING_MANIFEST": rigging_manifest_parts,
        "IMPORTED_SOURCES": typed_spec_parts,
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


def _parse_blocker_records(raw: str | None) -> list[BlockerRecord]:
    """Extract active blocker records and any Commander resolutions."""
    if not raw:
        return []
    records: list[BlockerRecord] = []
    for match in _BLOCKER_SECTION_RE.finditer(raw.strip()):
        body = match.group("body").strip()
        resolution_match = _COMMANDER_RESOLUTION_RE.search(body)
        resolution = None
        original = body
        has_resolution_field = resolution_match is not None
        if resolution_match is not None:
            original = body[: resolution_match.start()].strip()
            candidate = resolution_match.group("answer").strip()
            if candidate and candidate != _RESOLUTION_PLACEHOLDER:
                resolution = candidate
        records.append(
            BlockerRecord(
                blocker_id=match.group("id"),
                title=match.group("title").strip(),
                full_text=match.group(0).strip(),
                original_text=original,
                resolution=resolution,
                has_resolution_field=has_resolution_field,
            )
        )
    return records


def _ensure_blocker_resolution_fields(raw: str | None) -> str | None:
    """Add the Commander-owned resolution field to every active blocker."""
    if not raw:
        return raw

    def add_field(match: re.Match[str]) -> str:
        section = match.group(0).strip()
        if _COMMANDER_RESOLUTION_RE.search(match.group("body").strip()):
            return section
        return section + "\n\n### Commander Resolution\n\n" + _RESOLUTION_PLACEHOLDER

    return _BLOCKER_SECTION_RE.sub(add_field, raw).strip()


def _resolved_blocker_history(
    prior_analysis: str | None, previous_blockers: str | None, *, archived_on: str
) -> str:
    """Archive all prior blocker entries exactly once in ANALYSIS.md."""
    previous_records = _parse_blocker_records(previous_blockers)
    entries = _extract_resolved_blocker_history(prior_analysis)
    if not previous_records and previous_blockers:
        entry = "\n".join((
            "### Prior Blockers",
            "",
            f"Archived: {archived_on}",
            "",
            "```markdown",
            previous_blockers.strip(),
            "```",
        ))
        if not any(
            "```markdown\n" + previous_blockers.strip() + "\n```" in item for item in entries
        ):
            entries.append(entry)
    for record in previous_records:
        blocker_text = record.original_text or "(No additional blocker detail.)"
        resolution_text = record.resolution or "_Not provided._"
        entry = "\n".join((
            f"### {record.blocker_id}: {record.title}",
            "",
            f"Archived: {archived_on}",
            "",
            "#### Blocker",
            "",
            blocker_text,
            "",
            "#### Commander Resolution",
            "",
            resolution_text,
        ))
        archive_body = (
            "#### Blocker\n\n"
            + blocker_text
            + "\n\n#### Commander Resolution\n\n"
            + resolution_text
        )
        if not any(archive_body in item for item in entries):
            entries.append(entry)
    return "\n\n".join(entries)


def _extract_resolved_blocker_history(analysis_text: str | None) -> list[str]:
    if not analysis_text:
        return []
    match = _RESOLVED_BLOCKERS_SECTION_RE.search(analysis_text)
    if not match:
        return []
    body = match.group(0).split("\n", 1)
    content = body[1].strip() if len(body) == 2 else ""
    return [
        entry.strip()
        for entry in re.split(r"(?=^### )", content, flags=re.MULTILINE)
        if entry.strip()
    ]


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


def _attach_source_material_handoff(
    analysis_text: str, source_material: list[SourceMaterialFile], *, resolved_blockers: str = ""
) -> str:
    """Add deterministic source-material, blocker history, and planning-handoff sections."""
    text = re.sub(
        r"^## Source Inventory\s*$.*?(?=^## |\Z)",
        "",
        analysis_text,
        flags=re.MULTILINE | re.DOTALL,
    ).strip()
    text = _RESOLVED_BLOCKERS_SECTION_RE.sub("", text).strip()
    for heading in ("Relationship Model", "Planning Instructions"):
        if not re.search(rf"^## {re.escape(heading)}\s*$", text, re.MULTILINE):
            text += f"\n\n## {heading}\n\nNone identified."
    if not re.search(r"^## Commander Expectations\s*$", text, re.MULTILINE):
        text += (
            "\n\n## Commander Expectations\n\n"
            "- assert Commander intent is preserved by the planned product."
        )
    if not re.search(r"^## Crew\s*$", text, re.MULTILINE):
        text += (
            "\n\n## Crew\n\n"
            "| Crew | Charge |\n"
            "|---|---|\n"
            "| Commander | Defines intent and decides what done means. |\n"
            "| Team Lead | Confirms epic completeness and stakeholder expectations. |\n"
            "| Planning Crew | Authors atomic specifications and the ordered Manifest. |\n"
            "| Shipyard Crew | Builds the tickets without synchronous Commander access. |"
        )
    # Inventory is tool-derived evidence, not a model assertion. Place it before the
    # relationship and planning sections so QuarterDeck renders coverage prominently.
    inventory = inventory_markdown(source_material)
    if resolved_blockers:
        inventory += "\n\n## Resolved Blockers\n\n" + resolved_blockers
    relationship_heading = "## Relationship Model"
    return text.replace(relationship_heading, inventory + "\n\n" + relationship_heading, 1)


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
            question["input"] = "textarea"
        if name == "discovery-identity.json":
            proposed = str(question.get("proposed", "")).strip()
            if proposed and not str(question.get("answer", "")).strip():
                question["answer"] = proposed
        questions.append(question)
    normalized["questions"] = questions
    return normalized


def _ensure_sea_trials_blocker(blockers: str | None, reason: str) -> str:
    """Add the acceptance-contract gate when no usable Sea Trials contract exists.

    Reserved for the structural case: analyze returned no criteria, or the criteria cannot be
    parsed into a machine-usable contract. Notation never reaches here: a criterion written in
    plain English rather than EARS is recorded as ``Notation: other`` and is fully usable.
    """
    if blockers and _SEA_TRIALS_BLOCKER_ID in _BLOCKER_ID_RE.findall(blockers):
        return blockers
    sea_trials_blocker = (
        "## blocker-sea-trials: Define project acceptance criteria\n"
        f"{reason} Planning and final scoring have no acceptance contract to work against. "
        "Record the criteria this project must meet below, or correct the Blueprint inputs, "
        "then re-run analyze."
    )
    return (
        f"{blockers.rstrip()}\n\n{sea_trials_blocker}"
        if blockers
        else ("# Blockers: Project Acceptance\n\n" + sea_trials_blocker)
    )


def _parse_output(
    text: str,
) -> tuple[
    str, str | None, str | None, str | None, dict[str, dict], str, dict[str, str], str | None
]:
    """Return (analysis, sea_trials, compass_or_none, blockers_or_none, discoveries,
    quality, summary, technology_stack_or_none).

    ``summary`` contains parsed sub-fields: blockers, questions, stories, stack, features.
    Questionnaires (``discovery-*.json``), ``BLOCKERS.md``, and ``TECHNOLOGY_STACK.md`` are
    emitted dynamically, so none of them are required.
    Raises ValueError on missing required blocks or invalid JSON.
    """
    blocks = parse_artifact_blocks(
        text,
        label="Analyze",
        allowed_names={
            "ANALYSIS.md",
            "SEA_TRIALS.md",
            "BLOCKERS.md",
            "COMPASS.md",
            technology_stack.FILENAME,
        },
        allowed_prefixes=("discovery-",),
    )

    for required in ("ANALYSIS.md",):
        if required not in blocks:
            raise ValueError(f"LLM output missing === {required} === block")

    discoveries: dict[str, dict] = {}
    for name, content in blocks.items():
        if name.startswith("discovery-") and name.endswith(".json"):
            if name == SEA_TRIALS_QUESTIONNAIRE:
                raise ValueError(
                    f"{name} is written by Drydock from the SEA_TRIALS.md Questions section "
                    "and must not be emitted"
                )
            try:
                discoveries[name] = json.loads(content)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{name} block is not valid JSON: {exc}") from exc

    # Sea Trials are a project gate, not an Analyze execution failure. The caller validates this
    # optional model output and turns an absent or malformed contract into a QuarterDeck blocker.
    sea_trials_raw = blocks.get("SEA_TRIALS.md")
    sea_trials_text = normalize_sea_trials_text(sea_trials_raw) if sea_trials_raw else None

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
        sea_trials_text,
        compass_content,
        blockers_content,
        discoveries,
        quality,
        summary,
        blocks.get(technology_stack.FILENAME) or None,
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
    # Starting an earlier lifecycle step retires any current failure from a later one. If this
    # run produces a new recoverable failure, that command owns writing its replacement record.
    clear_error_record(target_dir)

    blueprint_dir = target_dir / "blueprint"
    if not blueprint_dir.is_dir():
        raise SpecificationError(f"Blueprint directory not found: {blueprint_dir}")

    questionnaires_dir = target_dir / "QuarterDeck" / "questionnaires"
    analysis_path = target_dir / "ANALYSIS.md"
    prior_analysis_text = (
        analysis_path.read_text(encoding="utf-8") if analysis_path.is_file() else None
    )
    sea_trials_path = target_dir / "SEA_TRIALS.md"
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
    if compass_pending and compass_content:
        from drydock.compass_guardrail import strip_guardrail

        compass_content = strip_guardrail(compass_content)

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
    excluded_filenames = load_excluded_filenames(target_dir)
    # Inventory proves coverage of every imported file. EXCLUDE_FILES controls only prompt
    # injection, never the immutable source-material record rendered into ANALYSIS.md.
    source_material = discover_source_material(blueprint_dir)

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
            compass_text,
            blockers_text_out,
            discoveries,
            quality,
            summary,
            technology_stack_text,
        ) = _parse_output(result.text)
    except (DrydockError, ValueError) as exc:
        return _fail(str(exc))

    # Sea Trials admission is structural only. A contract that cannot be parsed into machine-usable
    # criteria is a genuine Commander blocker. How a criterion is worded is not admission: EARS and
    # plain English are both accepted, recorded as `Notation: ears` or `Notation: other`, and
    # explained to the judge at scoring time.
    # Authorship is exclusive per run. A Commander file present means the model never writes
    # this artifact — not that its output is merged on top, which would need two writers and a
    # per-criterion precedence rule and would gain nothing. It also stops the model writing the
    # exam it is graded on, which is what makes one run comparable to the next.
    commander_trials = commander_sea_trials(target_dir)
    if commander_trials is not None:
        sea_trials_text = None

    sea_trials_blocker: str | None = None
    if commander_trials is not None:
        # The Commander's contract is the contract. Nothing to admit and nothing to blocker on.
        pass
    elif sea_trials_text is None:
        sea_trials_blocker = (
            "SEA_TRIALS.md was not created: analyze returned no acceptance criteria."
        )
    else:
        try:
            parse_sea_trials_text(sea_trials_text)
        except SpecificationError as exc:
            sea_trials_blocker = f"SEA_TRIALS.md was not created: {exc}"
            sea_trials_text = None

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
    if sea_trials_text is not None:
        sea_trials_path.write_text(sea_trials_text + "\n", encoding="utf-8", newline="\n")

    written_compass: Path | None = None
    if compass_text and (not compass_exists or compass_pending):
        from drydock.compass_guardrail import apply_guardrail

        compass_target.write_text(
            apply_guardrail(compass_text, target, target_dir), encoding="utf-8", newline="\n"
        )
        clear_compass_import_pending(target_dir)
        written_compass = compass_target

    # The section is Drydock-owned and is normalized mechanically even when Analyze preserves
    # the Commander's existing Compass body.
    if compass_target.is_file():
        from drydock.compass_guardrail import write_guardrail

        write_guardrail(compass_target, target, target_dir)

    discovery_paths: list[Path] = []
    for name, data in discoveries.items():
        discovery_path = questionnaires_dir / name
        if discovery_path.exists():
            continue  # never overwrite an existing questionnaire; answers must not be destroyed
        data = _normalize_discovery(name, data)
        discovery_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
        discovery_paths.append(discovery_path)

    if sea_trials_text is not None:
        sea_questions_path = project_questions(
            parse_sea_trials_text(sea_trials_text),
            questionnaires_dir / SEA_TRIALS_QUESTIONNAIRE,
        )
        if sea_questions_path is not None:
            discovery_paths.append(sea_questions_path)

    # TECHNOLOGY_STACK.md is proposed once and owned by the Commander thereafter. An existing
    # file is never overwritten, so re-analysis cannot discard hand-edited technology decisions.
    # A superseded discovery-stack answer migrates into rows on first pass.
    if technology_stack_text:
        technology_stack.ensure_technology_stack(
            target_dir, technology_stack.parse(technology_stack_text)
        )
    else:
        technology_stack.ensure_technology_stack(target_dir)

    if sea_trials_blocker:
        blockers_text_out = _ensure_sea_trials_blocker(blockers_text_out, sea_trials_blocker)
    blockers_text_out = _ensure_blocker_resolution_fields(blockers_text_out)
    resolved_blockers = _resolved_blocker_history(
        prior_analysis_text,
        blockers_text,
        archived_on=today,
    )

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
    analysis_text = _attach_source_material_handoff(
        analysis_text, source_material, resolved_blockers=resolved_blockers
    )
    analysis_path.write_text(analysis_text + "\n", encoding="utf-8", newline="\n")

    # Lifecycle state, sub-state, and date stamp — always written on success.
    stamp_last(target_dir, "analyzed")
    set_sub_state(target_dir, "complete")

    # Planning guidance becomes actionable as soon as Analysis exists. Initialize its
    # human-owned Compass now so QuarterDeck can surface it before plan creation.
    from drydock.planning_session import ensure_feedback_file as ensure_plan_compass

    ensure_plan_compass(target_dir)

    # Commanders Chair reflects the current analyzed state; delegate to shared builder.
    set_build_state(target_dir, "analyzed")
    from drydock.quarterdeck_state import refresh_commanders_chair as _refresh_chair

    commanders_chair_path = _refresh_chair(target_dir)

    return AnalyzeResult(
        target_dir=target_dir,
        analysis_path=analysis_path,
        sea_trials_path=sea_trials_path,
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
        warnings=tuple(
            item for item in (sea_trials_blocker, withheld_content_warning(source_material)) if item
        ),
        # True whenever the Target has a Sea Trials contract at the end of this run, whoever
        # authored it. A Commander file is not "missing Sea Trials".
        sea_trials_created=sea_trials_text is not None or commander_trials is not None,
    )
