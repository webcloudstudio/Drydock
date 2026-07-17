"""Evidence-bound technical scoring and project acceptance completion gate."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from drydock.acceptance import parse_programmatic_acceptance, run_programmatic_acceptance
from drydock.build_plan import parse_build_plan, stale_applied_specs
from drydock.errors import SpecificationError
from drydock.llm import run_prompt
from drydock.metadata import get_build_dir
from drydock.prompt_assembly import PromptAssembly
from drydock.prompts import load_prompt
from drydock.proof_integrity import analyze_proof
from drydock.sea_trials import (
    ASSERTION_TYPES,
    DETERMINISTIC_VERIFICATION,
    SeaTrial,
    load_sea_trials,
)

DIMENSIONS = (
    "specification_completeness",
    "implementation_coverage",
    "test_coverage",
    "documentation_coverage",
    "blueprint_drift",
    "build_quality",
    "acceptance_criteria_coverage",
)
VALID_VERDICTS = frozenset({"PASS", "FAIL", "INCONCLUSIVE"})
MEASUREMENT_TIMEOUT = 60


def _coverage_penalty(
    value: int, trials: tuple[SeaTrial, ...], deterministic_ids: frozenset[str]
) -> int:
    """Discount acceptance coverage by the share of required assertions judged only by the model.

    A required technical, behavioral, or guardrail criterion is expected to be provable, so a
    contract resting on model opinion cannot score as one resting on proof or measurement.
    Qualitative and outcome criteria are exempt: judgment is their only honest method.

    ``deterministic_ids`` names the criteria that carry genuine deterministic backing — a
    passing measurement contract or a proof that survives integrity analysis. A criterion whose
    only proof is vacuous is not in the set, so it is scored as if judged by the model.
    """
    graded = [trial for trial in trials if trial.required and trial.trial_type in ASSERTION_TYPES]
    if not graded:
        return value
    deterministic = sum(1 for trial in graded if trial.criterion_id in deterministic_ids)
    return round(value * (0.5 + 0.5 * deterministic / len(graded)))


class CompletedRun(Protocol):
    ok: bool
    text: str
    execution_id: str


RunnerFn = Callable[..., CompletedRun]
TextCallback = Callable[[str], None]


@dataclass(frozen=True)
class MeasurementResult:
    criterion_id: str
    status: str
    value: float | None = None
    unit: str = ""
    source: str = ""
    return_code: int | None = None
    detail: str = ""


@dataclass(frozen=True)
class CriterionResult:
    criterion_id: str
    verdict: str
    rationale: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class BuildScoreResult:
    target: str
    score: int
    dimensions: dict[str, int]
    criteria: tuple[CriterionResult, ...]
    blockers: tuple[str, ...]
    improvements: tuple[str, ...]
    complete: bool
    scorecard_path: Path
    evidence_path: Path
    execution_id: str

    def exit_code(self) -> int:
        return 0 if self.complete else 1


@dataclass(frozen=True)
class ScoreEvidenceState:
    state: str
    reasons: tuple[str, ...] = ()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(path: Path, *args: str) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), *args], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return result.returncode, (result.stdout or result.stderr).strip()


def _code_identity(build_dir: Path) -> tuple[str, bool]:
    rc, head = _git(build_dir, "rev-parse", "HEAD")
    if rc != 0:
        return "", True
    status_rc, status = _git(build_dir, "status", "--porcelain")
    return head, status_rc != 0 or bool(status)


def score_evidence_state(target: str, target_dir: Path) -> ScoreEvidenceState:
    """Return whether persisted build-score evidence still identifies current inputs and code."""
    evidence_path = target_dir / "evidence" / "build-score.json"
    if not evidence_path.is_file():
        return ScoreEvidenceState("none")
    try:
        record = json.loads(evidence_path.read_text(encoding="utf-8"))
        identities = record["identities"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return ScoreEvidenceState("stale", ("score evidence is invalid",))
    reasons: list[str] = []
    for label, path in (
        ("Sea Trials", target_dir / "SEA_TRIALS.md"),
        ("Manifest", target_dir / "MANIFEST.md"),
    ):
        key = label.lower().replace(" ", "_")
        if not path.is_file() or identities.get(key) != _sha(path):
            reasons.append(f"{label} changed")
    blueprint_dir = target_dir / "blueprint"
    current_blueprint = {path.name: _sha(path) for path in sorted(blueprint_dir.glob("*.md"))}
    if identities.get("blueprint") != current_blueprint:
        reasons.append("Blueprint changed")
    build_dir = get_build_dir(target, target_dir)
    code_identity, dirty = _code_identity(build_dir)
    if identities.get("code") != code_identity or dirty:
        reasons.append("build code changed")
    return ScoreEvidenceState("stale" if reasons else "current", tuple(reasons))


def _compare(value: float, operator: str, target: float) -> bool:
    return {
        "<": value < target,
        "<=": value <= target,
        "==": value == target,
        ">=": value >= target,
        ">": value > target,
    }.get(operator, False)


def _measurement_payload(text: str) -> tuple[float, str]:
    payload = json.loads(text)
    if not isinstance(payload, dict) or not isinstance(payload.get("value"), (int, float)):
        raise ValueError("measurement JSON must contain numeric value")
    return float(payload["value"]), str(payload.get("unit", ""))


def _measure(trial: SeaTrial, *, target_dir: Path, build_dir: Path) -> MeasurementResult:
    if trial.verification != "measurement":
        return MeasurementResult(trial.criterion_id, "not-applicable")
    text = ""
    source = ""
    return_code: int | None = None
    if trial.command:
        source = json.dumps(list(trial.command))
        try:
            result = subprocess.run(
                list(trial.command),
                cwd=build_dir,
                capture_output=True,
                text=True,
                timeout=MEASUREMENT_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return MeasurementResult(
                trial.criterion_id, "INCONCLUSIVE", source=source, detail=str(exc)
            )
        return_code = result.returncode
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip() or "measurement command failed"
            return MeasurementResult(
                trial.criterion_id,
                "INCONCLUSIVE",
                source=source,
                return_code=result.returncode,
                detail=detail,
            )
        text = result.stdout.strip()
    elif trial.evidence:
        candidate = (target_dir / trial.evidence).resolve()
        root = target_dir.resolve()
        if candidate != root and root not in candidate.parents:
            return MeasurementResult(
                trial.criterion_id, "INCONCLUSIVE", detail="evidence path escapes target"
            )
        source = trial.evidence
        if not candidate.is_file():
            return MeasurementResult(
                trial.criterion_id, "INCONCLUSIVE", source=source, detail="evidence file missing"
            )
        text = candidate.read_text(encoding="utf-8").strip()
    else:
        return MeasurementResult(
            trial.criterion_id, "INCONCLUSIVE", detail="measurement command or evidence missing"
        )
    try:
        value, unit = _measurement_payload(text)
    except (json.JSONDecodeError, ValueError) as exc:
        return MeasurementResult(
            trial.criterion_id,
            "INCONCLUSIVE",
            source=source,
            return_code=return_code,
            detail=str(exc),
        )
    if trial.unit and unit and trial.unit != unit:
        return MeasurementResult(
            trial.criterion_id,
            "INCONCLUSIVE",
            value=value,
            unit=unit,
            source=source,
            detail=f"unit mismatch: expected {trial.unit}, got {unit}",
        )
    if trial.target is None or trial.operator not in {"<", "<=", "==", ">=", ">"}:
        return MeasurementResult(
            trial.criterion_id,
            "INCONCLUSIVE",
            value=value,
            unit=unit,
            source=source,
            detail="target or comparison operator missing",
        )
    return MeasurementResult(
        trial.criterion_id,
        "PASS" if _compare(value, trial.operator, trial.target) else "FAIL",
        value=value,
        unit=unit or trial.unit,
        source=source,
        return_code=return_code,
    )


def _evidence_fact(trial: SeaTrial, target_dir: Path) -> dict[str, object] | None:
    if trial.verification != "evidence" or not trial.evidence:
        return None
    candidate = (target_dir / trial.evidence).resolve()
    root = target_dir.resolve()
    if candidate != root and root not in candidate.parents:
        return {"criterion_id": trial.criterion_id, "error": "evidence path escapes target"}
    if not candidate.is_file():
        return {"criterion_id": trial.criterion_id, "error": "evidence file missing"}
    content = candidate.read_text(encoding="utf-8", errors="replace")
    return {
        "criterion_id": trial.criterion_id,
        "path": trial.evidence,
        "sha256": _sha(candidate),
        "content": content[:20000],
        "truncated": len(content) > 20000,
    }


def _parse_json(text: str) -> dict:
    body = text.strip()
    fence = re.search(r"```(?:json)?\s*\n(.*?)\n```", body, re.DOTALL)
    if fence:
        body = fence.group(1).strip()
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end < start:
        raise SpecificationError("build score model output contained no JSON object")
    try:
        payload = json.loads(body[start : end + 1])
    except json.JSONDecodeError as exc:
        raise SpecificationError(f"build score model output is invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SpecificationError("build score model output must be a JSON object")
    return payload


def _render_scorecard(
    *,
    target: str,
    complete: bool,
    score: int,
    dimensions: dict[str, int],
    criteria: tuple[CriterionResult, ...],
    trials: dict[str, SeaTrial],
    blockers: tuple[str, ...],
    improvements: tuple[str, ...],
    code_identity: str,
) -> str:
    lines = [
        f"# Build Scorecard: {target}",
        "",
        f"- Completion gate: {'COMPLETE' if complete else 'INCOMPLETE'}",
        f"- Technical score: {score}/100",
        f"- Code identity: {code_identity or '-'}",
        "",
        "## Technical quality",
        "",
        "| Dimension | Score | Gate |",
        "|---|---:|---|",
    ]
    lines.extend(
        f"| {name.replace('_', ' ').title()} | {value} | {'PASS' if value >= 60 else 'FAIL'} |"
        for name, value in dimensions.items()
    )
    lines.extend([
        "",
        "## Project acceptance",
        "",
        "| ID | Type | Criterion | Required | Verdict | Evidence |",
        "|---|---|---|---|---|---|",
    ])
    for result in criteria:
        trial = trials[result.criterion_id]
        evidence = "; ".join(result.evidence) or result.rationale
        guardrail = trial.trial_type == "guardrail"
        # A guardrail is absolute: it is held or breached, and Required does not apply to it.
        verdict = (
            ("HELD" if result.verdict == "PASS" else "BREACHED") if guardrail else result.verdict
        )
        required = "absolute" if guardrail else ("yes" if trial.required else "no")
        lines.append(
            f"| {result.criterion_id} | {trial.trial_type} | {trial.criterion.replace('|', '/')} | "
            f"{required} | {verdict} | {evidence.replace('|', '/')} |"
        )
    lines.extend(["", "## Completion blockers", ""])
    lines.extend(f"- {item}" for item in blockers or ("None.",))
    lines.extend(["", "## Ranked improvements", ""])
    lines.extend(f"{index}. {item}" for index, item in enumerate(improvements, 1))
    if not improvements:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def score_target(
    target: str,
    target_dir: Path,
    *,
    runner: RunnerFn | None = None,
    on_text: TextCallback | None = None,
    model: str | None = None,
    llm_provider: str | None = None,
    log_dir: Path | None = None,
) -> BuildScoreResult:
    """Score the current built Target and return its aggregate completion verdict."""
    sea_path = target_dir / "SEA_TRIALS.md"
    manifest_path = target_dir / "MANIFEST.md"
    blueprint_dir = target_dir / "blueprint"
    document = load_sea_trials(sea_path)
    plan = parse_build_plan(manifest_path)
    build_dir = get_build_dir(target, target_dir)
    if not build_dir.is_dir():
        raise SpecificationError(f"build directory not found: {build_dir}")

    blockers: list[str] = []
    executable = [block for block in plan.blocks if block.block_type in {"story", "spike"}]
    incomplete = [block.block_id for block in executable if block.state != "closed/verified"]
    if incomplete:
        blockers.append("Manifest work is not closed/verified: " + ", ".join(incomplete))
    stale = stale_applied_specs(plan, blueprint_dir)
    if stale:
        blockers.append(
            "Applied Blueprint specifications are stale: " + ", ".join(s.rel_path for s in stale)
        )
    code_identity, dirty = _code_identity(build_dir)
    if not code_identity:
        blockers.append("Build directory has no usable Git code identity")
    if dirty:
        blockers.append("Build directory has uncommitted changes")
    if document.questions:
        blockers.append("Sea Trials has unresolved QUESTIONS")

    checks = tuple(
        check
        for path in sorted(blueprint_dir.glob("*.md"))
        for check in parse_programmatic_acceptance(path)
    )
    acceptance = run_programmatic_acceptance(
        checks, build_dir=build_dir, target_dir=target_dir, blueprint_dir=blueprint_dir
    )
    proof_integrity = tuple(analyze_proof(check.code) for check in checks)
    failed_acceptance = [check.check_id for check in acceptance if not check.passed]
    if failed_acceptance:
        blockers.append("Programmatic acceptance failed: " + ", ".join(failed_acceptance))
    vacuous_proofs = [
        check.check_id for check, integ in zip(checks, proof_integrity, strict=True) if not integ.ok
    ]
    if vacuous_proofs:
        blockers.append("Programmatic acceptance is vacuous: " + ", ".join(vacuous_proofs))
    # A criterion carries deterministic backing only when a measurement contract or an
    # integrity-valid proof stands behind it; a vacuous proof is scored as model judgment.
    proof_backed = {
        criterion
        for check, integ in zip(checks, proof_integrity, strict=True)
        if integ.ok
        for criterion in check.sea_trials
    }
    deterministic_ids = frozenset(
        trial.criterion_id
        for trial in document.trials
        if trial.verification in DETERMINISTIC_VERIFICATION
        and (trial.verification != "proof" or trial.criterion_id in proof_backed)
    )

    known_trial_ids = {trial.criterion_id for trial in document.trials}
    manifest_refs = {
        value
        for block in executable
        for value in block.fields.get("accepts", ())
        if isinstance(value, str)
    }
    proof_refs = {value for check in checks for value in check.sea_trials}
    unknown_refs = sorted((manifest_refs | proof_refs) - known_trial_ids)
    if unknown_refs:
        blockers.append("Unknown Sea Trial references: " + ", ".join(unknown_refs))
    traceable_required = {
        trial.criterion_id
        for trial in document.trials
        if trial.required and trial.trial_type in {"technical", "behavioral"}
    }
    uncovered = sorted(traceable_required - (manifest_refs | proof_refs))
    if uncovered:
        blockers.append(
            "Required Sea Trials lack implementation/proof coverage: " + ", ".join(uncovered)
        )

    measurements = tuple(
        _measure(trial, target_dir=target_dir, build_dir=build_dir) for trial in document.trials
    )
    evidence_facts = tuple(
        fact for trial in document.trials if (fact := _evidence_fact(trial, target_dir)) is not None
    )
    facts = {
        "target": target,
        "manifest": {
            "total_executable": len(executable),
            "verified": len(executable) - len(incomplete),
            "incomplete": incomplete,
        },
        "code": {"identity": code_identity, "dirty": dirty},
        "blueprint": {
            "files": [path.name for path in sorted(blueprint_dir.glob("*.md"))],
            "stale": [item.rel_path for item in stale],
        },
        "programmatic_acceptance": [asdict(item) for item in acceptance],
        "traceability": {
            "manifest_references": sorted(manifest_refs),
            "proof_references": sorted(proof_refs),
            "uncovered_required": uncovered,
            "unknown_references": unknown_refs,
        },
        "measurements": [asdict(item) for item in measurements],
        "evidence_files": evidence_facts,
        "sea_trials": [asdict(item) for item in document.trials],
        "deterministic_blockers": blockers,
    }
    prompt = load_prompt("build_score")
    rendered = (
        prompt.body + "\n\n## Evidence facts\n\n```json\n" + json.dumps(facts, indent=2) + "\n```\n"
    )
    assembly = PromptAssembly.single_prompt(rendered)
    run = runner if runner is not None else run_prompt
    result = run(
        rendered,
        target_dir,
        llm=llm_provider,
        model=model or prompt.model,
        command_name="build score",
        parameters={"target": target},
        log_dir=log_dir,
        target=target,
        on_text=on_text,
        prompt_assembly=assembly,
    )
    if not result.ok or not result.text.strip():
        raise SpecificationError("build score LLM execution failed or returned no output")
    payload = _parse_json(result.text)
    raw_dimensions = payload.get("dimensions")
    if not isinstance(raw_dimensions, dict) or set(raw_dimensions) != set(DIMENSIONS):
        raise SpecificationError("build score output must score exactly the seven dimensions")
    dimensions: dict[str, int] = {}
    for name in DIMENSIONS:
        value = raw_dimensions[name]
        if not isinstance(value, int) or not 0 <= value <= 100:
            raise SpecificationError(f"build score dimension {name} must be an integer 0..100")
        dimensions[name] = value
    dimensions["acceptance_criteria_coverage"] = _coverage_penalty(
        dimensions["acceptance_criteria_coverage"], document.trials, deterministic_ids
    )

    trial_by_id = {trial.criterion_id: trial for trial in document.trials}
    model_criteria: dict[str, dict] = {}
    for item in payload.get("criteria", []):
        if not isinstance(item, dict) or item.get("id") not in trial_by_id:
            raise SpecificationError("build score output contains an unknown criterion ID")
        criterion_id = str(item["id"])
        if criterion_id in model_criteria:
            raise SpecificationError(f"build score output duplicates criterion {criterion_id}")
        model_criteria[criterion_id] = item
    if set(model_criteria) != set(trial_by_id):
        raise SpecificationError("build score output must judge every Sea Trial exactly once")

    measurements_by_id = {item.criterion_id: item for item in measurements}
    evidence_by_id = {str(item["criterion_id"]): item for item in evidence_facts}
    criteria: list[CriterionResult] = []
    for criterion_id, trial in trial_by_id.items():
        item = model_criteria[criterion_id]
        verdict = str(item.get("verdict", "INCONCLUSIVE")).upper()
        if verdict not in VALID_VERDICTS:
            raise SpecificationError(f"build score {criterion_id} has invalid verdict {verdict}")
        rationale = str(item.get("rationale", "")).strip()
        raw_evidence = item.get("evidence", [])
        evidence = (
            tuple(str(value) for value in raw_evidence) if isinstance(raw_evidence, list) else ()
        )
        measured = measurements_by_id[criterion_id]
        if trial.verification == "measurement":
            verdict = measured.status if measured.status in VALID_VERDICTS else "INCONCLUSIVE"
            evidence = tuple(filter(None, (measured.source, measured.detail)))
        if trial.verification == "proof":
            referencing = [
                (result, integ)
                for check, result, integ in zip(checks, acceptance, proof_integrity, strict=True)
                if criterion_id in check.sea_trials
            ]
            valid = [result for result, integ in referencing if integ.ok]
            if not referencing:
                verdict = "INCONCLUSIVE"
                evidence = ("no code-bound proof references this criterion",)
            elif not valid:
                # Every referencing proof is vacuous: treat the criterion as unproven.
                reasons = "; ".join(reason for _, integ in referencing for reason in integ.reasons)
                verdict = "INCONCLUSIVE"
                evidence = (f"proof failed integrity: {reasons or 'no effective failure path'}",)
            else:
                verdict = "PASS" if all(item.passed for item in valid) else "FAIL"
                evidence = tuple(
                    f"{item.source}:{item.check_id}={'PASS' if item.passed else 'FAIL'}"
                    for item in valid
                )
        if trial.verification == "evidence" and "error" in evidence_by_id.get(criterion_id, {}):
            verdict = "INCONCLUSIVE"
            evidence = (str(evidence_by_id[criterion_id]["error"]),)
        criteria.append(CriterionResult(criterion_id, verdict, rationale, evidence))

    score = round(sum(dimensions.values()) / len(DIMENSIONS))
    if score < 80:
        blockers.append(f"Technical score {score} is below 80")
    low_dimensions = [name for name, value in dimensions.items() if value < 60]
    if low_dimensions:
        blockers.append("Technical dimensions below 60: " + ", ".join(low_dimensions))
    for item in criteria:
        trial = trial_by_id[item.criterion_id]
        if trial.trial_type == "guardrail":
            # A guardrail is absolute. An unproven never is not held, so INCONCLUSIVE breaches
            # too, and Required does not apply.
            if item.verdict != "PASS":
                blockers.append(f"Guardrail {item.criterion_id} is BREACHED: {trial.criterion}")
            continue
        if trial.required and item.verdict != "PASS":
            blockers.append(f"Required Sea Trial {item.criterion_id} is {item.verdict}")

    criterion_improvements = [
        f"Resolve {item.criterion_id} ({item.verdict}): {trial_by_id[item.criterion_id].criterion}"
        for item in criteria
        if item.verdict != "PASS"
    ]
    raw_improvements = payload.get("improvements", [])
    proposed = criterion_improvements + [
        str(item).strip() for item in raw_improvements if str(item).strip()
    ]
    improvements = tuple(dict.fromkeys(proposed))
    complete = not blockers
    evidence_path = target_dir / "evidence" / "build-score.json"
    scorecard_path = target_dir / "SCORECARD.md"
    record = {
        "schema_version": 2,
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "target": target,
        "complete": complete,
        "technical_score": score,
        "dimensions": dimensions,
        "criteria": [asdict(item) for item in criteria],
        "blockers": blockers,
        "improvements": improvements,
        "identities": {
            "code": code_identity,
            "sea_trials": _sha(sea_path),
            "manifest": _sha(manifest_path),
            "blueprint": {path.name: _sha(path) for path in sorted(blueprint_dir.glob("*.md"))},
        },
        "measurements": [asdict(item) for item in measurements],
        "evidence_files": evidence_facts,
        "programmatic_acceptance": [asdict(item) for item in acceptance],
        "execution_id": result.execution_id,
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    scorecard_path.write_text(
        _render_scorecard(
            target=target,
            complete=complete,
            score=score,
            dimensions=dimensions,
            criteria=tuple(criteria),
            trials=trial_by_id,
            blockers=tuple(blockers),
            improvements=improvements,
            code_identity=code_identity,
        ),
        encoding="utf-8",
        newline="\n",
    )
    return BuildScoreResult(
        target,
        score,
        dimensions,
        tuple(criteria),
        tuple(blockers),
        improvements,
        complete,
        scorecard_path,
        evidence_path,
        result.execution_id,
    )
