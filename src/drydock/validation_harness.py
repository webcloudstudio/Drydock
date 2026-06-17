"""Internal validation harness for benchmark-style Drydock verification.

This module powers the repo-local ``validation/`` scaffold. It is intentionally
not exposed as a public ``drydock`` command yet.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from drydock.errors import SpecificationError

REQUIRED_SECTIONS = (
    "Goal",
    "Input Contract",
    "Build Steps",
    "Required Artifacts",
    "Assertions",
    "Scoring",
    "Gap Rules",
    "Notes",
)

SECTION_RE = re.compile(r"^## (?P<name>[^\n]+)\n", re.MULTILINE)
CASE_RE = re.compile(r"^# VALIDATION CASE:\s*(?P<slug>[a-z0-9-]+)\s*$", re.MULTILINE)
ASSERTION_ID_RE = re.compile(r"^[A-Z0-9-]+$")
RESULT_STATUS = {"pass": 1.0, "partial": 0.5, "fail": 0.0}
DEFAULT_MINIMUM_SCORE = 85
VALID_GAP_CLASSES = frozenset(
    {
        "missing-artifact",
        "wrong-output",
        "behavior-mismatch",
        "missing-test",
        "missing-evidence",
        "runtime-failure",
        "contract-drift",
        "shortcut-or-fabrication",
    }
)
_BANDS: tuple[tuple[int, str], ...] = (
    (90, "SEAWORTHY"),
    (75, "SEA_TRIALS"),
    (60, "TAKING_WATER"),
    (0, "DRY_DOCK"),
)


@dataclass(frozen=True)
class CaseAssertion:
    id: str
    type: str
    weight: int
    subject: str
    expectation: str
    evidence: str


@dataclass(frozen=True)
class CaseSpec:
    slug: str
    path: Path
    goal: str
    input_contract: str
    build_steps: list[str]
    required_artifacts: list[str]
    assertions: list[CaseAssertion]
    minimum_score: int
    gap_rules: dict[str, str]
    notes: str


@dataclass(frozen=True)
class ScoredAssertion:
    id: str
    status: str
    weight: int
    score: float
    subject: str
    expectation: str
    evidence: str
    detail: str
    gaps: list[str]


@dataclass(frozen=True)
class ScoredCase:
    slug: str
    spec_path: str
    result_path: str
    score: int
    minimum_score: int
    passed: bool
    band: str
    build_exit_code: int
    verify_exit_code: int
    runner_status: str
    gaps: list[str]
    missing_artifacts: list[str]
    assertions: list[ScoredAssertion]

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "spec_path": self.spec_path,
            "result_path": self.result_path,
            "score": self.score,
            "minimum_score": self.minimum_score,
            "passed": self.passed,
            "band": self.band,
            "build_exit_code": self.build_exit_code,
            "verify_exit_code": self.verify_exit_code,
            "runner_status": self.runner_status,
            "gaps": self.gaps,
            "missing_artifacts": self.missing_artifacts,
            "assertions": [asdict(assertion) for assertion in self.assertions],
        }


def _band_for(score: int) -> str:
    return next(name for threshold, name in _BANDS if score >= threshold)


def _sections(text: str) -> dict[str, str]:
    matches = list(SECTION_RE.finditer(text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group("name").strip()] = text[start:end].strip()
    return sections


def _table_rows(block: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in block.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or cells[0] in {"ID", "----"}:
            continue
        if all(set(cell) <= {"-"} for cell in cells):
            continue
        rows.append(cells)
    return rows


def parse_case_spec(path: Path) -> CaseSpec:
    text = path.read_text(encoding="utf-8")
    case_match = CASE_RE.search(text)
    if not case_match:
        raise SpecificationError(f"validation case is missing H1 slug: {path}")

    sections = _sections(text)
    missing = [name for name in REQUIRED_SECTIONS if name not in sections]
    if missing:
        raise SpecificationError(
            f"validation case missing required sections {missing!r}: {path}"
        )

    build_steps = [
        line[2:].strip()
        for line in sections["Build Steps"].splitlines()
        if line.strip().startswith("- ")
    ]
    required_artifacts = [
        line[2:].strip()
        for line in sections["Required Artifacts"].splitlines()
        if line.strip().startswith("- ")
    ]

    assertions: list[CaseAssertion] = []
    for row in _table_rows(sections["Assertions"]):
        if len(row) != 6:
            raise SpecificationError(f"validation assertion row must have 6 columns: {path}")
        identifier, assertion_type, weight_text, subject, expectation, evidence = row
        if not ASSERTION_ID_RE.match(identifier):
            raise SpecificationError(f"invalid validation assertion id {identifier!r}: {path}")
        try:
            weight = int(weight_text)
        except ValueError as exc:
            raise SpecificationError(f"invalid assertion weight {weight_text!r}: {path}") from exc
        assertions.append(
            CaseAssertion(
                id=identifier,
                type=assertion_type,
                weight=weight,
                subject=subject,
                expectation=expectation,
                evidence=evidence,
            )
        )
    if not assertions:
        raise SpecificationError(f"validation case has no assertions: {path}")

    scoring_text = sections["Scoring"]
    minimum_score = DEFAULT_MINIMUM_SCORE
    minimum_match = re.search(r"Minimum score:\s*(\d+)", scoring_text, re.IGNORECASE)
    if minimum_match:
        minimum_score = int(minimum_match.group(1))

    gap_rules: dict[str, str] = {}
    for line in sections["Gap Rules"].splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        body = line[2:]
        if ":" not in body:
            continue
        name, description = body.split(":", 1)
        gap_rules[name.strip()] = description.strip()

    unknown_gaps = sorted(set(gap_rules) - VALID_GAP_CLASSES)
    if unknown_gaps:
        raise SpecificationError(f"unknown validation gap classes {unknown_gaps!r}: {path}")

    return CaseSpec(
        slug=case_match.group("slug"),
        path=path,
        goal=sections["Goal"].strip(),
        input_contract=sections["Input Contract"].strip(),
        build_steps=build_steps,
        required_artifacts=required_artifacts,
        assertions=assertions,
        minimum_score=minimum_score,
        gap_rules=gap_rules,
        notes=sections["Notes"].strip(),
    )


def validate_result_payload(payload: dict[str, Any], *, path: Path | None = None) -> None:
    label = str(path) if path is not None else "<payload>"
    required = {
        "schema",
        "case",
        "status",
        "build_exit_code",
        "verify_exit_code",
        "artifacts_present",
        "artifacts_missing",
        "checks",
        "raw_paths",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise SpecificationError(f"validation result missing keys {missing!r}: {label}")
    if payload["schema"] != 1:
        raise SpecificationError(f"unsupported validation schema {payload['schema']!r}: {label}")
    if payload["status"] not in {"pass", "partial", "fail"}:
        raise SpecificationError(f"invalid validation status {payload['status']!r}: {label}")
    if not isinstance(payload["checks"], list):
        raise SpecificationError(f"validation checks must be a list: {label}")
    for entry in payload["checks"]:
        if not isinstance(entry, dict):
            raise SpecificationError(f"validation check entry must be an object: {label}")
        for key in ("id", "status", "evidence"):
            if key not in entry:
                raise SpecificationError(f"validation check missing {key!r}: {label}")
        if entry["status"] not in RESULT_STATUS:
            raise SpecificationError(f"invalid check status {entry['status']!r}: {label}")
        gaps = entry.get("gaps", [])
        if not isinstance(gaps, list):
            raise SpecificationError(f"validation check gaps must be a list: {label}")
        unknown = sorted(set(gaps) - VALID_GAP_CLASSES)
        if unknown:
            raise SpecificationError(f"unknown validation gaps {unknown!r}: {label}")


def load_result_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_result_payload(payload, path=path)
    return payload


def _default_gap(assertion: CaseAssertion, status: str) -> list[str]:
    if status == "pass":
        return []
    if assertion.type == "artifact":
        return ["missing-artifact"]
    if assertion.type == "output":
        return ["wrong-output"]
    if assertion.type == "behavior":
        return ["behavior-mismatch"]
    if assertion.type == "test":
        return ["missing-test"]
    return ["contract-drift"]


def score_case(spec: CaseSpec, payload: dict[str, Any], *, result_path: Path | None = None) -> ScoredCase:
    if payload.get("case") != spec.slug:
        raise SpecificationError(
            f"validation result case {payload.get('case')!r} does not match spec {spec.slug!r}"
        )
    by_id = {entry["id"]: entry for entry in payload["checks"]}

    earned = 0.0
    possible = 0
    scored_assertions: list[ScoredAssertion] = []
    gaps: set[str] = set()

    for assertion in spec.assertions:
        possible += assertion.weight
        entry = by_id.get(assertion.id)
        if entry is None:
            status = "fail"
            detail = "check missing from result payload"
            evidence = "no evidence emitted"
            assertion_gaps = ["missing-evidence"]
        else:
            status = entry["status"]
            detail = str(entry.get("detail", "")).strip() or str(entry["evidence"]).strip()
            evidence = str(entry["evidence"]).strip()
            assertion_gaps = list(entry.get("gaps", [])) or _default_gap(assertion, status)
        earned += assertion.weight * RESULT_STATUS[status]
        gaps.update(assertion_gaps)
        scored_assertions.append(
            ScoredAssertion(
                id=assertion.id,
                status=status,
                weight=assertion.weight,
                score=RESULT_STATUS[status],
                subject=assertion.subject,
                expectation=assertion.expectation,
                evidence=evidence,
                detail=detail,
                gaps=assertion_gaps,
            )
        )

    missing_artifacts = list(payload.get("artifacts_missing", []))
    if missing_artifacts:
        gaps.add("missing-artifact")

    build_exit_code = int(payload.get("build_exit_code", 0))
    verify_exit_code = int(payload.get("verify_exit_code", 0))
    if build_exit_code != 0 or verify_exit_code != 0 or payload.get("status") == "fail":
        gaps.add("runtime-failure")

    score = round((earned * 100.0 / possible) if possible else 0.0)
    passed = score >= spec.minimum_score and "runtime-failure" not in gaps
    return ScoredCase(
        slug=spec.slug,
        spec_path=str(spec.path),
        result_path=str(result_path) if result_path is not None else "",
        score=score,
        minimum_score=spec.minimum_score,
        passed=passed,
        band=_band_for(score),
        build_exit_code=build_exit_code,
        verify_exit_code=verify_exit_code,
        runner_status=str(payload.get("status", "fail")),
        gaps=sorted(gaps),
        missing_artifacts=missing_artifacts,
        assertions=scored_assertions,
    )


def render_case_markdown(scored: ScoredCase) -> str:
    lines = [
        f"# Validation Scorecard: {scored.slug}",
        "",
        f"- Score: {scored.score}/{100}",
        f"- Minimum passing score: {scored.minimum_score}",
        f"- Passed: {'yes' if scored.passed else 'no'}",
        f"- Band: {scored.band}",
        f"- Build exit code: {scored.build_exit_code}",
        f"- Verify exit code: {scored.verify_exit_code}",
        f"- Gaps: {', '.join(scored.gaps) if scored.gaps else 'none'}",
        "",
        "## Assertions",
        "",
        "| ID | Status | Weight | Detail | Gaps |",
        "|----|--------|--------|--------|------|",
    ]
    for assertion in scored.assertions:
        lines.append(
            f"| {assertion.id} | {assertion.status} | {assertion.weight} | "
            f"{assertion.detail or assertion.evidence} | {', '.join(assertion.gaps) or 'none'} |"
        )
    lines.append("")
    return "\n".join(lines)


def aggregate_results(cases: list[ScoredCase]) -> dict[str, Any]:
    if not cases:
        raise SpecificationError("no validation cases were scored")

    recurring: dict[str, int] = {}
    for case in cases:
        for gap in case.gaps:
            recurring[gap] = recurring.get(gap, 0) + 1

    average_score = round(sum(case.score for case in cases) / len(cases))
    all_passed = all(case.passed for case in cases)
    top_gap = ""
    if recurring:
        top_gap = sorted(recurring.items(), key=lambda item: (-item[1], item[0]))[0][0]

    return {
        "case_count": len(cases),
        "average_score": average_score,
        "band": _band_for(average_score),
        "all_passed": all_passed,
        "top_gap": top_gap,
        "recurring_gaps": dict(sorted(recurring.items(), key=lambda item: (-item[1], item[0]))),
        "cases": [case.to_dict() for case in sorted(cases, key=lambda item: item.slug)],
    }


def render_summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Validation Summary",
        "",
        f"- Cases: {summary['case_count']}",
        f"- Average score: {summary['average_score']}/100",
        f"- Band: {summary['band']}",
        f"- All passed: {'yes' if summary['all_passed'] else 'no'}",
        f"- Top recurring gap: {summary['top_gap'] or 'none'}",
        "",
        "## Cases",
        "",
        "| Case | Score | Passed | Band | Gaps |",
        "|------|-------|--------|------|------|",
    ]
    for case in summary["cases"]:
        lines.append(
            f"| {case['slug']} | {case['score']} | {'yes' if case['passed'] else 'no'} | "
            f"{case['band']} | {', '.join(case['gaps']) or 'none'} |"
        )
    lines.append("")
    if summary["recurring_gaps"]:
        lines.append("## Recurring Gaps")
        lines.append("")
        for gap, count in summary["recurring_gaps"].items():
            lines.append(f"- {gap}: {count}")
        lines.append("")
    return "\n".join(lines)
