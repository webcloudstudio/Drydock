"""`drydock prompt review` — critique one prompt against spec, notes, and consumer contracts."""

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
from drydock.prompt_assembly import PromptAssembly, fenced_markdown_part, lines_part, part
from drydock.prompts import load_prompt

PROMPT_NAME = "prompt_review"

_CATEGORY_WEIGHTS: dict[str, float] = {
    "spec_alignment": 0.30,
    "input_realism": 0.20,
    "output_contract_safety": 0.20,
    "analytical_effectiveness": 0.20,
    "ambiguity_control": 0.10,
}
_CATEGORY_ORDER: tuple[str, ...] = tuple(_CATEGORY_WEIGHTS)
_RATING_BANDS: tuple[tuple[float, str], ...] = (
    (9.0, "Strong"),
    (7.5, "Workable"),
    (6.0, "Brittle"),
    (0.0, "Needs Rewrite"),
)


@dataclass(frozen=True)
class PromptReviewComponent:
    name: str
    command: str
    prompt_file: str
    notes_file: str
    spec_heading: str
    support_files: tuple[str, ...]


_COMPONENTS: dict[str, PromptReviewComponent] = {
    "analyze": PromptReviewComponent(
        name="analyze",
        command="drydock analyze",
        prompt_file="prompts/analyze.md",
        notes_file="docs/notes_analyze.md",
        spec_heading="### Analyze Your Specification",
        support_files=("src/drydock/analyze.py",),
    ),
    "plan": PromptReviewComponent(
        name="plan",
        command="drydock plan",
        prompt_file="prompts/plan_create.md",
        notes_file="docs/notes_plan.md",
        spec_heading="### Building and Reviewing the Build Plan / Manifest",
        support_files=("prompts/MANIFEST_CONTRACT.md", "prompts/BLUEPRINTS_CONTRACT.md"),
    ),
}


class CompletedRun(Protocol):
    @property
    def ok(self) -> bool: ...

    text: str
    execution_id: str
    stats: object | None


RunnerFn = Callable[..., CompletedRun]


@dataclass(frozen=True)
class PromptReview:
    component: str
    command: str
    overall_score: float
    rating_band: str
    scorecard: dict[str, float]
    executive_assessment: str
    general_recommendation: str
    best_plan: list[str]
    findings: list[dict[str, str]]
    strengths: list[str]
    open_questions: list[str]
    recommended_edits: list[str]
    review_method: list[str]


@dataclass(frozen=True)
class PromptReviewResult:
    component: str
    review_path: Path
    archive_path: Path | None
    execution_id: str | None
    review_model: str
    overall_score: float
    rating_band: str


def _sanitize_component(component: str) -> str:
    return component.strip().lower().replace("-", "_")


def resolve_component(name: str) -> PromptReviewComponent:
    component = _COMPONENTS.get(_sanitize_component(name))
    if component is None:
        available = ", ".join(sorted(_COMPONENTS))
        raise SpecificationError(
            f"unknown prompt-review component: {name!r}; expected one of: {available}"
        )
    return component


def _extract_markdown_section(text: str, heading: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != heading:
            continue
        level = len(line) - len(line.lstrip("#"))
        block: list[str] = [line]
        for later in lines[index + 1 :]:
            stripped = later.lstrip()
            if stripped.startswith("#"):
                later_level = len(later) - len(later.lstrip("#"))
                if later_level <= level:
                    break
            block.append(later)
        return "\n".join(block).strip()
    raise SpecificationError(f"spec section not found: {heading}")


def _read_required(path: Path, label: str) -> str:
    if not path.is_file():
        raise SpecificationError(f"{label} not found: {path}")
    return path.read_text(encoding="utf-8")


def _format_markdown_block(title: str, path: Path, text: str) -> str:
    return "\n".join(
        [
            f"## {title}",
            f"path: {path}",
            "",
            "```markdown",
            text.rstrip(),
            "```",
            "",
        ]
    )


def _assemble_prompt(component: PromptReviewComponent, repo_root: Path, body: str) -> str:
    return _assemble_prompt_assembly(component, repo_root, body).rendered_text


def _assemble_prompt_assembly(
    component: PromptReviewComponent, repo_root: Path, body: str
) -> PromptAssembly:
    prompt_path = repo_root / component.prompt_file
    notes_path = repo_root / component.notes_file
    spec_path = repo_root / "docs" / "Drydock_Specification.md"

    prompt_text = _read_required(prompt_path, "prompt file")
    notes_text = _read_required(notes_path, "notes file")
    spec_text = _extract_markdown_section(
        _read_required(spec_path, "specification"), component.spec_heading
    )

    parts = [
        part("Prompt body", body + "\n\n", kind="prompt-body"),
        lines_part(
            "Review job",
            [
                "## Review job",
                "",
                f"- COMPONENT: {component.name}",
                f"- COMMAND: {component.command}",
                f"- PROMPT_FILE: {prompt_path}",
                f"- NOTES_FILE: {notes_path}",
                f"- SPEC_SECTION: {component.spec_heading}",
                "",
            ],
            kind="job",
        ),
        fenced_markdown_part(
            "Prompt Under Review",
            f"## Prompt Under Review\npath: {prompt_path}",
            prompt_text,
            role="prompt under review",
            path=prompt_path,
        ),
        fenced_markdown_part(
            "Working Notes",
            f"## Working Notes\npath: {notes_path}",
            notes_text,
            role="notes",
            path=notes_path,
        ),
        fenced_markdown_part(
            "Authoritative Spec Slice",
            f"## Authoritative Spec Slice\npath: {spec_path}",
            spec_text,
            role="spec slice",
            path=spec_path,
        ),
    ]

    for relative_path in component.support_files:
        support_path = repo_root / relative_path
        support_text = _read_required(support_path, "support file")
        parts.append(
            fenced_markdown_part(
                "Consumer Contract",
                f"## Consumer Contract\npath: {support_path}",
                support_text,
                role="consumer contract",
                path=support_path,
            )
        )

    return PromptAssembly(parts=tuple(parts))


def _coerce_score(value: object, category: str) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError) as exc:
        raise DrydockError(f"review score for {category!r} is not numeric: {value!r}") from exc
    if not (0.0 <= score <= 10.0):
        raise DrydockError(f"review score for {category!r} must be between 0 and 10: {score!r}")
    return round(score, 1)


def _ensure_string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise DrydockError(f"review field {field!r} must be a non-empty list")
    items = [str(item).strip() for item in value if str(item).strip()]
    if not items:
        raise DrydockError(f"review field {field!r} must contain non-empty strings")
    return items


def _ensure_findings(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise DrydockError("review field 'findings' must be a non-empty list")
    findings: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise DrydockError("each finding must be an object")
        finding = {
            "severity": str(item.get("severity", "")).strip(),
            "title": str(item.get("title", "")).strip(),
            "evidence": str(item.get("evidence", "")).strip(),
            "impact": str(item.get("impact", "")).strip(),
        }
        if not all(finding.values()):
            raise DrydockError("each finding must include severity, title, evidence, and impact")
        findings.append(finding)
    return findings


def _ensure_text(value: object, field: str) -> str:
    text = str(value).strip()
    if not text:
        raise DrydockError(f"review field {field!r} must be a non-empty string")
    return text


def _rating_band(score: float) -> str:
    for threshold, name in _RATING_BANDS:
        if score >= threshold:
            return name
    return _RATING_BANDS[-1][1]


def _compute_overall(scorecard: dict[str, float]) -> float:
    total = sum(_CATEGORY_WEIGHTS[name] * scorecard[name] for name in _CATEGORY_ORDER)
    return round(total, 1)


def parse_review_payload(text: str, *, component: PromptReviewComponent) -> PromptReview:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DrydockError(f"prompt review output is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise DrydockError("prompt review output must be a JSON object")

    scorecard_raw = payload.get("scorecard")
    if not isinstance(scorecard_raw, dict):
        raise DrydockError("prompt review output must include a 'scorecard' object")
    scorecard = {
        category: _coerce_score(scorecard_raw.get(category), category)
        for category in _CATEGORY_ORDER
    }

    overall = _compute_overall(scorecard)
    return PromptReview(
        component=component.name,
        command=component.command,
        overall_score=overall,
        rating_band=_rating_band(overall),
        scorecard=scorecard,
        executive_assessment=_ensure_text(
            payload.get("executive_assessment"), "executive_assessment"
        ),
        general_recommendation=_ensure_text(
            payload.get("general_recommendation"), "general_recommendation"
        ),
        best_plan=_ensure_string_list(payload.get("best_plan"), "best_plan"),
        findings=_ensure_findings(payload.get("findings")),
        strengths=_ensure_string_list(payload.get("strengths"), "strengths"),
        open_questions=[
            str(item).strip() for item in payload.get("open_questions", []) if str(item).strip()
        ],
        recommended_edits=_ensure_string_list(
            payload.get("recommended_edits"), "recommended_edits"
        ),
        review_method=_ensure_string_list(payload.get("review_method"), "review_method"),
    )


def _format_score(score: float) -> str:
    return f"{score:.1f}/10"


def render_review_markdown(
    review: PromptReview,
    *,
    component: PromptReviewComponent,
    reviewed_at: str,
    review_model: str,
) -> str:
    lines = [
        "---",
        f"component: {component.name}",
        f"command: {component.command}",
        f"prompt_file: {component.prompt_file}",
        f"notes_file: {component.notes_file}",
        "spec_source: docs/Drydock_Specification.md",
        f"reviewed_at: {reviewed_at}",
        f"review_model: {review_model}",
        f"overall_score: {_format_score(review.overall_score)}",
        f"rating_band: {review.rating_band}",
        "scorecard:",
    ]
    for category in _CATEGORY_ORDER:
        lines.append(f"  {category}: {_format_score(review.scorecard[category])}")
    lines.extend(
        [
            "status: current",
            "archive_of: null",
            "---",
            "",
            f"# Prompt Review: {component.name}",
            "",
            "## Executive Assessment",
            review.executive_assessment,
            "",
            "## General Recommendation",
            review.general_recommendation,
            "",
            "## Best Plan",
        ]
    )
    lines.extend([f"{index}. {item}" for index, item in enumerate(review.best_plan, start=1)])
    lines.extend(["", "## Findings"])
    for index, finding in enumerate(review.findings, start=1):
        lines.extend(
            [
                f"{index}. [{finding['severity']}] {finding['title']}",
                f"Evidence: {finding['evidence']}",
                f"Impact: {finding['impact']}",
            ]
        )
    lines.extend(["", "## Strengths"])
    lines.extend([f"- {item}" for item in review.strengths])
    lines.extend(["", "## Open Questions"])
    if review.open_questions:
        lines.extend([f"- {item}" for item in review.open_questions])
    else:
        lines.append("- None.")
    lines.extend(["", "## Recommended Edits"])
    lines.extend([f"- {item}" for item in review.recommended_edits])
    lines.extend(["", "## Review Method"])
    lines.extend([f"- {item}" for item in review.review_method])
    lines.append("")
    return "\n".join(lines)


def _archive_previous_review(
    current_path: Path,
    archive_dir: Path,
    *,
    reviewed_at: datetime,
    review_model: str,
) -> Path | None:
    if not current_path.is_file():
        return None
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = reviewed_at.strftime("%Y%m%d-%H%M%S")
    safe_model = re.sub(r"[^A-Za-z0-9._-]+", "-", review_model).strip("-") or "unknown"
    archive_path = archive_dir / f"{current_path.stem}--{stamp}--{safe_model}.md"
    shutil.copy2(current_path, archive_path)
    return archive_path


def review_prompt(
    component_name: str,
    *,
    runner: RunnerFn | None = None,
    model: str | None = None,
    llm_provider: str | None = None,
    log_dir: Path | None = None,
) -> PromptReviewResult:
    component = resolve_component(component_name)
    repo_root = get_repo_root()
    prompt = load_prompt(PROMPT_NAME)
    prompt_assembly = _assemble_prompt_assembly(component, repo_root, prompt.body)
    run = runner if runner is not None else run_prompt
    result = run(
        prompt_assembly.rendered_text,
        repo_root,
        llm=llm_provider,
        model=model or prompt.model,
        command_name="prompt-review",
        parameters={"component": component.name, "command": component.command},
        log_dir=log_dir,
        prompt_assembly=prompt_assembly,
    )
    if not result.ok or not result.text.strip():
        raise SpecificationError("prompt review execution failed")

    review = parse_review_payload(result.text, component=component)

    stats_model = getattr(getattr(result, "stats", None), "model", None)
    review_model = str(stats_model or prompt.model or "unknown").strip() or "unknown"
    reviewed_at_dt = datetime.now().astimezone()
    reviewed_at = reviewed_at_dt.isoformat(timespec="seconds")

    reviews_dir = repo_root / "docs" / "prompt_reviews"
    review_path = reviews_dir / f"{component.name}.md"
    archive_path = _archive_previous_review(
        review_path,
        reviews_dir / "archive",
        reviewed_at=reviewed_at_dt,
        review_model=review_model,
    )
    reviews_dir.mkdir(parents=True, exist_ok=True)
    review_path.write_text(
        render_review_markdown(
            review,
            component=component,
            reviewed_at=reviewed_at,
            review_model=review_model,
        ),
        encoding="utf-8",
        newline="\n",
    )

    return PromptReviewResult(
        component=component.name,
        review_path=review_path,
        archive_path=archive_path,
        execution_id=getattr(result, "execution_id", None),
        review_model=review_model,
        overall_score=review.overall_score,
        rating_band=review.rating_band,
    )
