"""``drydock score drydock`` — adversarial self-assessment of Drydock's own process.

Drydock scores the software it builds with ``score ac`` and ``score release``. This command turns
the same discipline on Drydock itself: it assembles the authoritative specification, every prompt
contract, and the module and Rigging inventories, and asks the highest available model to attack
the methodology from its own declared intent.

The command is advisory and read-mostly. It changes no source, no prompt, and no specification. It
emits ranked feature files under ``docs/drydock_planning/`` that a coding model can implement, each
decomposed into Agile stories with TDD acceptance criteria.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from drydock.errors import DrydockError, SpecificationError
from drydock.llm import run_prompt
from drydock.paths import get_repo_root
from drydock.prompt_assembly import (
    PromptAssembly,
    fenced_markdown_part,
    fenced_text_part,
    lines_part,
    part,
    section_heading_part,
    system_preamble_part,
)
from drydock.prompts import load_prompt

PROMPT_NAME = "score_drydock"

# The adversarial pass is a deep, one-shot reasoning job over the whole methodology, so it always
# reaches for the strongest model rather than the configured build default. ``--model`` overrides.
HIGHEST_MODEL = "fable"

PLANNING_DIRNAME = "drydock_planning"


class CompletedRun(Protocol):
    @property
    def ok(self) -> bool: ...

    text: str
    execution_id: str
    stats: object | None


RunnerFn = Callable[..., CompletedRun]


@dataclass(frozen=True)
class Story:
    title: str
    statement: str
    acceptance_criteria: tuple[str, ...]
    tests: tuple[str, ...]


@dataclass(frozen=True)
class Feature:
    feature_id: str
    title: str
    area: str
    problem: str
    intent_reference: str
    evidence: str
    recommendation: str
    impact: int
    complexity: int
    project_types: tuple[str, ...]
    stories: tuple[Story, ...]
    definition_of_done: tuple[str, ...]
    implementation_plan: tuple[str, ...]
    specification_impact: str
    risks: tuple[str, ...]

    @property
    def leverage(self) -> float:
        """Impact per unit of complexity — the tiebreak used to order equal-impact features."""
        return self.impact / self.complexity


@dataclass(frozen=True)
class ProjectTypeGap:
    project_type: str
    gap: str
    evidence: str
    severity: str


@dataclass(frozen=True)
class DrydockAssessment:
    executive_assessment: str
    systemic_risks: tuple[str, ...]
    project_type_gaps: tuple[ProjectTypeGap, ...]
    features: tuple[Feature, ...]


@dataclass(frozen=True)
class ScoreDrydockResult:
    planning_dir: Path
    index_path: Path
    feature_paths: tuple[Path, ...]
    archive_path: Path | None
    execution_id: str | None
    review_model: str
    assessment: DrydockAssessment

    def exit_code(self) -> int:
        # Advisory command: producing the plan is the success condition. A methodology critique is
        # not a gate, so findings never fail the run.
        return 0


# ── payload validation ────────────────────────────────────────────────────────


def _text(value: object, field: str) -> str:
    text = str(value if value is not None else "").strip()
    if not text:
        raise DrydockError(f"score drydock output field {field!r} must be a non-empty string")
    return text


def _string_list(value: object, field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise DrydockError(f"score drydock output field {field!r} must be a list")
    items = tuple(str(item).strip() for item in value if str(item).strip())
    if not items and not allow_empty:
        raise DrydockError(f"score drydock output field {field!r} must be a non-empty list")
    return items


def _rank_value(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise DrydockError(f"score drydock output field {field!r} must be an integer 1..10")
    try:
        number = int(float(value))
    except (TypeError, ValueError) as exc:
        raise DrydockError(
            f"score drydock output field {field!r} must be an integer 1..10"
        ) from exc
    if not 1 <= number <= 10:
        raise DrydockError(
            f"score drydock output field {field!r} must be an integer 1..10: {value!r}"
        )
    return number


def _parse_story(payload: object, feature_id: str, index: int) -> Story:
    if not isinstance(payload, dict):
        raise DrydockError(f"score drydock feature {feature_id} story {index} must be an object")
    where = f"{feature_id}.stories[{index}]"
    return Story(
        title=_text(payload.get("title"), f"{where}.title"),
        statement=_text(payload.get("statement"), f"{where}.statement"),
        acceptance_criteria=_string_list(
            payload.get("acceptance_criteria"), f"{where}.acceptance_criteria"
        ),
        tests=_string_list(payload.get("tests"), f"{where}.tests"),
    )


def _parse_feature(payload: object, index: int) -> Feature:
    if not isinstance(payload, dict):
        raise DrydockError(f"score drydock features[{index}] must be an object")
    feature_id = _text(payload.get("id"), f"features[{index}].id")
    raw_stories = payload.get("stories")
    if not isinstance(raw_stories, list) or not raw_stories:
        raise DrydockError(f"score drydock feature {feature_id} must decompose into stories")
    area = str(payload.get("area", "")).strip() or "cross-cutting"
    return Feature(
        feature_id=feature_id,
        title=_text(payload.get("title"), f"{feature_id}.title"),
        area=area,
        problem=_text(payload.get("problem"), f"{feature_id}.problem"),
        intent_reference=_text(payload.get("intent_reference"), f"{feature_id}.intent_reference"),
        evidence=_text(payload.get("evidence"), f"{feature_id}.evidence"),
        recommendation=_text(payload.get("recommendation"), f"{feature_id}.recommendation"),
        impact=_rank_value(payload.get("impact"), f"{feature_id}.impact"),
        complexity=_rank_value(payload.get("complexity"), f"{feature_id}.complexity"),
        project_types=_string_list(
            payload.get("project_types"), f"{feature_id}.project_types", allow_empty=True
        ),
        stories=tuple(
            _parse_story(item, feature_id, position)
            for position, item in enumerate(raw_stories, start=1)
        ),
        definition_of_done=_string_list(
            payload.get("definition_of_done"), f"{feature_id}.definition_of_done"
        ),
        implementation_plan=_string_list(
            payload.get("implementation_plan"), f"{feature_id}.implementation_plan"
        ),
        specification_impact=str(payload.get("specification_impact", "none")).strip() or "none",
        risks=_string_list(payload.get("risks"), f"{feature_id}.risks", allow_empty=True),
    )


def _parse_gap(payload: object, index: int) -> ProjectTypeGap:
    if not isinstance(payload, dict):
        raise DrydockError(f"score drydock project_type_gaps[{index}] must be an object")
    where = f"project_type_gaps[{index}]"
    severity = str(payload.get("severity", "")).strip().lower() or "medium"
    return ProjectTypeGap(
        project_type=_text(payload.get("project_type"), f"{where}.project_type"),
        gap=_text(payload.get("gap"), f"{where}.gap"),
        evidence=str(payload.get("evidence", "")).strip(),
        severity=severity,
    )


def _strip_fence(text: str) -> str:
    """Tolerate a fenced JSON reply. The contract forbids the fence; the parse does not depend
    on the model honoring it."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    body = stripped.split("\n", 1)[1] if "\n" in stripped else ""
    return body.rsplit("```", 1)[0].strip()


def parse_assessment(text: str) -> DrydockAssessment:
    """Validate the model payload into a typed assessment. Ranked ordering is applied here so the
    written plan is deterministic regardless of the order the model emitted."""
    try:
        payload = json.loads(_strip_fence(text))
    except json.JSONDecodeError as exc:
        raise DrydockError(f"score drydock output is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise DrydockError("score drydock output must be a JSON object")

    raw_features = payload.get("features")
    if not isinstance(raw_features, list) or not raw_features:
        raise DrydockError("score drydock output must include a non-empty 'features' list")
    features = [_parse_feature(item, index) for index, item in enumerate(raw_features, start=1)]
    seen: set[str] = set()
    for feature in features:
        if feature.feature_id in seen:
            raise DrydockError(f"score drydock output duplicates feature id {feature.feature_id}")
        seen.add(feature.feature_id)

    raw_gaps = payload.get("project_type_gaps", [])
    if not isinstance(raw_gaps, list):
        raise DrydockError("score drydock output field 'project_type_gaps' must be a list")

    return DrydockAssessment(
        executive_assessment=_text(payload.get("executive_assessment"), "executive_assessment"),
        systemic_risks=_string_list(
            payload.get("systemic_risks", []), "systemic_risks", allow_empty=True
        ),
        project_type_gaps=tuple(
            _parse_gap(item, index) for index, item in enumerate(raw_gaps, start=1)
        ),
        features=tuple(rank_features(features)),
    )


def rank_features(features: list[Feature]) -> list[Feature]:
    """Highest impact first; among equal impact, the cheapest to deliver first."""
    return sorted(features, key=lambda f: (-f.impact, f.complexity, f.feature_id))


# ── prompt assembly ───────────────────────────────────────────────────────────


def _module_inventory(repo_root: Path) -> str:
    """One line per package module: filename and its first docstring line.

    The critique needs the shape of the implementation, not its source. A summary keeps the
    process surface visible without spending the context that reading every module would cost.
    """
    lines: list[str] = []
    for path in sorted((repo_root / "src" / "drydock").glob("*.py")):
        if path.name == "__init__.py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        match = re.match(r'\s*(?:"""|\'\'\')(.*)', text)
        summary = match.group(1).strip().rstrip("\"'") if match else ""
        lines.append(f"{path.name}: {summary}" if summary else path.name)
    return "\n".join(lines)


def _rigging_inventory(repo_root: Path) -> str:
    rigging = repo_root / "Rigging"
    if not rigging.is_dir():
        return "(no Rigging tree in this checkout)"
    return "\n".join(
        sorted(
            str(path.relative_to(rigging))
            for path in rigging.rglob("*.md")
            if path.is_file() and "_compact" not in path.name
        )
    )


def collect_prompt_files(repo_root: Path) -> tuple[Path, ...]:
    """Every current prompt contract. ``archive/`` is excluded: retired prompts describe behavior
    Drydock no longer has, and critiquing them would produce findings against dead surface."""
    prompts_dir = repo_root / "prompts"
    return tuple(sorted(path for path in prompts_dir.glob("*.md") if path.is_file()))


def assemble_prompt(repo_root: Path, body: str, *, today: str) -> PromptAssembly:
    specification = repo_root / "docs" / "Drydock_Specification.md"
    if not specification.is_file():
        raise SpecificationError(f"Drydock specification not found: {specification}")

    parts = [
        system_preamble_part(),
        section_heading_part("# Input Context"),
        lines_part(
            "Assessment job",
            [
                "## Assessment job",
                "",
                "- SUBJECT: Drydock itself — methodology, prompt contracts, and command process",
                f"- REPO_ROOT: {repo_root}",
                f"- DATE: {today}",
                f"- INTENT_AUTHORITY: {specification}",
                f"- OUTPUT_DIRECTORY: docs/{PLANNING_DIRNAME}/",
                "- MODE: advisory. Recommend changes; do not produce code.",
                "",
            ],
            kind="job",
        ),
        fenced_markdown_part(
            "Drydock_Specification.md",
            specification.read_text(encoding="utf-8"),
            role="intent authority",
            path=specification,
        ),
    ]
    for prompt_path in collect_prompt_files(repo_root):
        parts.append(
            fenced_markdown_part(
                prompt_path.name,
                prompt_path.read_text(encoding="utf-8"),
                role="prompt contract under review",
                path=prompt_path,
            )
        )
    parts.append(
        fenced_text_part(
            "Package module inventory",
            _module_inventory(repo_root),
            role="implementation surface",
        )
    )
    parts.append(
        fenced_text_part(
            "Rigging inventory",
            _rigging_inventory(repo_root),
            role="governed inputs",
        )
    )
    parts.append(section_heading_part("# Agent Task"))
    parts.append(part("Prompt body", body + "\n\n", kind="prompt-body"))
    return PromptAssembly(parts=tuple(parts))


# ── rendering ─────────────────────────────────────────────────────────────────


def slugify(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return slug[:60].strip("-") or "feature"


def feature_filename(feature: Feature, rank: int) -> str:
    return f"FEATURE-{rank:02d}-{slugify(feature.title)}.md"


def render_feature_markdown(
    feature: Feature, *, rank: int, generated_at: str, review_model: str
) -> str:
    lines = [
        "---",
        f"id: {feature.feature_id}",
        f"title: {feature.title}",
        f"area: {feature.area}",
        f"impact: {feature.impact}",
        f"complexity: {feature.complexity}",
        f"rank: {rank}",
        f"generated_at: {generated_at}",
        f"review_model: {review_model}",
        "source: drydock score drydock",
        "---",
        "",
        f"# FEATURE {feature.feature_id}: {feature.title}",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Area | {feature.area} |",
        f"| Impact | {feature.impact}/10 |",
        f"| Complexity | {feature.complexity}/10 |",
        f"| Rank | {rank} |",
        f"| Project Types | {', '.join(feature.project_types) or '—'} |",
        "",
        "## Problem",
        "",
        feature.problem,
        "",
        "## Intent",
        "",
        feature.intent_reference,
        "",
        "## Evidence",
        "",
        feature.evidence,
        "",
        "## Recommendation",
        "",
        feature.recommendation,
        "",
        "## Stories",
        "",
    ]
    for index, story in enumerate(feature.stories, start=1):
        lines.extend([
            f"### Story {index}: {story.title}",
            "",
            story.statement,
            "",
            "**Acceptance Criteria**",
            "",
        ])
        lines.extend(f"- {item}" for item in story.acceptance_criteria)
        lines.extend(["", "**Tests (RED first)**", ""])
        lines.extend(f"- {item}" for item in story.tests)
        lines.append("")
    lines.extend(["## Definition of Done", ""])
    lines.extend(f"- {item}" for item in feature.definition_of_done)
    lines.extend(["", "## Implementation Plan", ""])
    lines.extend(f"{index}. {step}" for index, step in enumerate(feature.implementation_plan, 1))
    lines.extend(["", "## Specification Impact", "", feature.specification_impact, ""])
    lines.extend(["## Risks", ""])
    lines.extend(f"- {item}" for item in feature.risks or ("None identified.",))
    lines.append("")
    return "\n".join(lines)


def render_index_markdown(
    assessment: DrydockAssessment,
    *,
    filenames: dict[str, str],
    generated_at: str,
    review_model: str,
) -> str:
    lines = [
        "---",
        "title: Drydock Adversarial Assessment",
        f"generated_at: {generated_at}",
        f"review_model: {review_model}",
        f"feature_count: {len(assessment.features)}",
        "source: drydock score drydock",
        "---",
        "",
        "# Drydock Adversarial Assessment",
        "",
        "## Executive Assessment",
        "",
        assessment.executive_assessment,
        "",
        "## Ranked Features",
        "",
        "| Rank | ID | Feature | Area | Impact | Complexity | File |",
        "|---:|---|---|---|---:|---:|---|",
    ]
    for rank, feature in enumerate(assessment.features, start=1):
        name = filenames[feature.feature_id]
        lines.append(
            f"| {rank} | {feature.feature_id} | {feature.title} | {feature.area} | "
            f"{feature.impact} | {feature.complexity} | [{name}]({name}) |"
        )
    lines.extend(["", "## Systemic Risks", ""])
    lines.extend(f"- {item}" for item in assessment.systemic_risks or ("None reported.",))
    lines.extend(["", "## Project Type Coverage Gaps", ""])
    if assessment.project_type_gaps:
        lines.extend([
            "| Project Type | Severity | Gap | Evidence |",
            "|---|---|---|---|",
        ])
        for gap in assessment.project_type_gaps:
            lines.append(
                f"| {gap.project_type} | {gap.severity} | {gap.gap} | {gap.evidence or '—'} |"
            )
    else:
        lines.append("- None reported.")
    lines.append("")
    return "\n".join(lines)


# ── output ────────────────────────────────────────────────────────────────────


def _archive_previous_plan(planning_dir: Path, *, generated_at: datetime) -> Path | None:
    """Move a prior run's Markdown aside instead of overwriting it.

    Successive assessments are a record of how the methodology changed, and a prior plan may carry
    the author's own annotations. Nothing generated here is ever deleted.
    """
    existing = sorted(path for path in planning_dir.glob("*.md") if path.is_file())
    if not existing:
        return None
    archive_dir = planning_dir / "archive" / generated_at.strftime("%Y%m%d-%H%M%S")
    archive_dir.mkdir(parents=True, exist_ok=True)
    for path in existing:
        shutil.move(str(path), str(archive_dir / path.name))
    return archive_dir


def write_assessment(
    assessment: DrydockAssessment,
    planning_dir: Path,
    *,
    generated_at: datetime,
    review_model: str,
) -> tuple[Path, tuple[Path, ...], Path | None]:
    stamp = generated_at.isoformat(timespec="seconds")
    planning_dir.mkdir(parents=True, exist_ok=True)
    archive_path = _archive_previous_plan(planning_dir, generated_at=generated_at)

    filenames: dict[str, str] = {}
    written: list[Path] = []
    for rank, feature in enumerate(assessment.features, start=1):
        name = feature_filename(feature, rank)
        filenames[feature.feature_id] = name
        path = planning_dir / name
        path.write_text(
            render_feature_markdown(
                feature, rank=rank, generated_at=stamp, review_model=review_model
            ),
            encoding="utf-8",
            newline="\n",
        )
        written.append(path)

    index_path = planning_dir / "INDEX.md"
    index_path.write_text(
        render_index_markdown(
            assessment,
            filenames=filenames,
            generated_at=stamp,
            review_model=review_model,
        ),
        encoding="utf-8",
        newline="\n",
    )
    return index_path, tuple(written), archive_path


def score_drydock(
    *,
    runner: RunnerFn | None = None,
    model: str | None = None,
    llm_provider: str | None = None,
    log_dir: Path | None = None,
    repo_root: Path | None = None,
    on_text: Callable[[str], None] | None = None,
) -> ScoreDrydockResult:
    """Run the adversarial self-assessment and write the ranked plan.

    ``model`` is an explicit override only. With no override the prompt's declared model wins, so
    the assessment always reaches for the strongest model rather than the configured build default.
    """
    root = repo_root or get_repo_root()
    prompt = load_prompt(PROMPT_NAME)
    generated_at = datetime.now().astimezone()
    assembly = assemble_prompt(root, prompt.body, today=generated_at.strftime("%Y-%m-%d"))
    run = runner if runner is not None else run_prompt
    result = run(
        assembly.rendered_text,
        root,
        llm=llm_provider,
        model=model or prompt.model or HIGHEST_MODEL,
        command_name="score drydock",
        parameters={"subject": "drydock"},
        log_dir=log_dir,
        on_text=on_text,
        prompt_assembly=assembly,
    )
    if not result.ok or not result.text.strip():
        raise SpecificationError("score drydock LLM execution failed or returned no output")

    assessment = parse_assessment(result.text)
    stats_model = getattr(getattr(result, "stats", None), "model", None)
    review_model = str(stats_model or model or prompt.model or HIGHEST_MODEL).strip() or "unknown"

    planning_dir = root / "docs" / PLANNING_DIRNAME
    index_path, feature_paths, archive_path = write_assessment(
        assessment, planning_dir, generated_at=generated_at, review_model=review_model
    )
    return ScoreDrydockResult(
        planning_dir=planning_dir,
        index_path=index_path,
        feature_paths=feature_paths,
        archive_path=archive_path,
        execution_id=getattr(result, "execution_id", None),
        review_model=review_model,
        assessment=assessment,
    )
