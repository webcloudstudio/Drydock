"""Acceptance scoring: deterministic per-AC verification and the LLM release gate.

- ``drydock score ac`` runs each acceptance criterion's Programmatic Acceptance, applies proof
  integrity, and records a ``✓ PASS`` / ``✗ FAIL`` / ``— UNVERIFIED`` verdict per AC into
  ``SOUNDINGS.md`` with a timestamp. It is deterministic — no model call, no network — and is the
  sole writer of ``SOUNDINGS.md``: the trust-but-verify board the Commander scans instead of
  granting approvals.
- ``drydock score release`` judges the project-level criteria in ``SEA_TRIALS.md`` against the
  completed build. Deterministic proofs, measurements, and guardrails are settled mechanically and
  fed to the model, which judges the remaining ``evidence`` and ``llm`` criteria and scores the
  quality dimensions. It writes ``SCORECARD.md`` and ``evidence/score-release.json``.

Both reuse the build_score primitives so the deterministic verdicts agree across paths.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from drydock.acceptance import (
    AcceptanceObservation,
    all_programmatic_acceptance,
    observe_programmatic_acceptance,
    parse_programmatic_acceptance,
    programmatic_acceptance_for_step,
    run_programmatic_acceptance,
)
from drydock.build_plan import BuildPlan, parse_build_plan, stale_applied_specs
from drydock.build_score import (
    DIMENSIONS,
    VALID_VERDICTS,
    BuildScoreResult,
    CriterionResult,
    RunnerFn,
    TextCallback,
    _code_identity,
    _coverage_penalty,
    _evidence_fact,
    _measure,
    _parse_json,
    _render_scorecard,
    _sha,
)
from drydock.errors import SpecificationError
from drydock.llm import run_prompt
from drydock.metadata import get_build_dir
from drydock.prompt_assembly import PromptAssembly
from drydock.prompts import load_prompt
from drydock.proof_integrity import analyze_proof
from drydock.sea_trials import (
    DETERMINISTIC_VERIFICATION,
    format_wording_failures,
    load_sea_trials,
)
from drydock.source_roles import tampered_build_assets
from drydock.standard_artifacts import (
    VERIFIED_FAIL,
    VERIFIED_PASS,
    VERIFIED_UNVERIFIED,
    Sounding,
    render_soundings,
)

PASS = "PASS"
FAIL = "FAIL"
UNVERIFIED = "UNVERIFIED"

_VERIFIED_LABEL = {PASS: VERIFIED_PASS, FAIL: VERIFIED_FAIL, UNVERIFIED: VERIFIED_UNVERIFIED}


@dataclass(frozen=True)
class AcVerdict:
    criterion_id: str
    summary: str
    status: str  # PASS | FAIL | UNVERIFIED
    evidence: str
    source: str = ""
    # Owning plan blocks, resolved from the story that implements ``source``. Empty when the
    # Blueprint file is not claimed by any story in the Manifest.
    story: str = ""
    feature: str = ""


@dataclass(frozen=True)
class AcReport:
    target: str
    verdicts: tuple[AcVerdict, ...]
    soundings_path: Path
    verified_at: str
    # ``scope`` is the resolved block id when the run was narrowed to one feature/story with
    # ``--step``; ``None`` for a whole-target run. A scoped run reports only that block's
    # acceptance and does not rewrite the SOUNDINGS.md board (``wrote_soundings`` is False),
    # since the board is a full projection of every Blueprint assertion.
    scope: str | None = None
    scope_name: str = ""
    wrote_soundings: bool = True

    def exit_code(self) -> int:
        # A FAIL is a hard failure; UNVERIFIED is surfaced but does not fail the run, since not
        # every story carries an executable proof (spikes, pure UI). The board shows the gap.
        return 1 if any(v.status == FAIL for v in self.verdicts) else 0


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _observation_verdict(obs: AcceptanceObservation) -> tuple[str, str]:
    """Map a per-assertion observation to a board ``(status, evidence)`` pair.

    A passing proof that fails integrity analysis is demoted to ``UNVERIFIED`` (vacuous), so a
    green checkmark always reflects a proof that actually exercises behavior.
    """
    if not obs.passed:
        tail = obs.stderr.strip().splitlines()[-1] if obs.stderr.strip() else "FAIL"
        return FAIL, obs.error or tail
    if not obs.integrity_ok:
        reasons = "; ".join(obs.integrity_reasons)
        return UNVERIFIED, f"proof failed integrity: {reasons or 'no effective failure path'}"
    return PASS, ""


def _resolve_scope_block(plan: BuildPlan, step_id: str):
    """Resolve a ``--step`` selector to a block. An exact id match (case-insensitive) wins over a
    display-name match, so a story id never loses to a feature that shares its display name."""
    low = step_id.strip().lower()
    for block in plan.blocks:
        if block.block_id.lower() == low:
            return block
    for block in plan.blocks:
        if (block.name or "").lower() == low:
            return block
    valid = ", ".join(
        block.block_id for block in plan.blocks if block.block_type in {"feature", "story", "spike"}
    )
    raise SpecificationError(f"unknown --step '{step_id}'. Valid ids: {valid}")


def _scoped_checks(plan: BuildPlan, blueprint_dir: Path, block) -> tuple:
    """Every Blueprint assertion owned by ``block`` — its own if a story, its stories' if a
    feature — deduped by ``(source, check_id)``."""
    if block.block_type == "feature":
        stories = [
            child
            for child in plan.children(block.block_id)
            if child.block_type in {"story", "spike"}
        ]
    else:
        stories = [block]
    checks: list = []
    seen: set[tuple[str, str]] = set()
    for story in stories:
        for check in programmatic_acceptance_for_step(story, blueprint_dir):
            key = (check.source, check.check_id)
            if key in seen:
                continue
            seen.add(key)
            checks.append(check)
    return tuple(checks)


def _blueprint_owners(plan: BuildPlan) -> dict[str, tuple[str, str]]:
    """Map each implemented Blueprint file name to its ``(story_id, feature_id)`` owner.

    First claimant wins, matching the dedupe order of ``all_programmatic_acceptance``, so a file
    implemented by two stories is attributed to the same story the assertion came from.
    """
    owners: dict[str, tuple[str, str]] = {}
    for block in plan.blocks:
        if block.block_type not in {"story", "spike"}:
            continue
        for name in block.fields.get("implements", ()):
            if isinstance(name, str) and name not in owners:
                owners[name] = (block.block_id, block.parent or "")
    return owners


def verify_acs(target: str, target_dir: Path, *, step_id: str | None = None) -> AcReport:
    """Verify Blueprint acceptance assertions deterministically.

    One verdict per Blueprint Programmatic Acceptance assertion. A whole-target run (``step_id``
    is ``None``) rewrites ``SOUNDINGS.md`` in full from fresh results; the board is a pure
    projection of every current Blueprint assertion. A scoped run (``step_id`` names a feature or
    story) verifies only that block's assertions and leaves the board untouched.
    """
    manifest_path = target_dir / "MANIFEST.md"
    blueprint_dir = target_dir / "blueprint"
    plan = parse_build_plan(manifest_path)
    build_dir = get_build_dir(target, target_dir)
    if not build_dir.is_dir():
        raise SpecificationError(f"build directory not found: {build_dir}")

    verified_at = _now()
    scope_block = None
    if step_id is None:
        checks = all_programmatic_acceptance(plan, blueprint_dir)
    else:
        scope_block = _resolve_scope_block(plan, step_id)
        checks = _scoped_checks(plan, blueprint_dir, scope_block)
    observations = observe_programmatic_acceptance(
        checks, build_dir=build_dir, target_dir=target_dir, blueprint_dir=blueprint_dir
    )

    owners = _blueprint_owners(plan)
    verdicts: list[AcVerdict] = []
    rows: list[Sounding] = []
    for obs in observations:
        status, evidence = _observation_verdict(obs)
        stamp = verified_at if status != UNVERIFIED else ""
        story, feature = owners.get(obs.source, ("", ""))
        verdicts.append(
            AcVerdict(obs.check_id, obs.intent, status, evidence, obs.source, story, feature)
        )
        rows.append(
            Sounding(
                criterion_id=obs.check_id,
                blueprint=obs.source,
                summary=obs.intent,
                verified=_VERIFIED_LABEL[status],
                evidence=evidence,
                verified_at=stamp,
            )
        )

    soundings_path = target_dir / "SOUNDINGS.md"
    wrote_soundings = scope_block is None
    if wrote_soundings:
        soundings_path.parent.mkdir(parents=True, exist_ok=True)
        soundings_path.write_text(render_soundings(rows), encoding="utf-8", newline="\n")
    return AcReport(
        target,
        tuple(verdicts),
        soundings_path,
        verified_at,
        scope=scope_block.block_id if scope_block else None,
        scope_name=scope_block.name if scope_block else "",
        wrote_soundings=wrote_soundings,
    )


def score_release(
    target: str,
    target_dir: Path,
    *,
    runner: RunnerFn | None = None,
    on_text: TextCallback | None = None,
    model: str | None = None,
    llm_provider: str | None = None,
    log_dir: Path | None = None,
) -> BuildScoreResult:
    """LLM-assisted release gate: judge project Sea Trials against the built code.

    Reads ``SEA_TRIALS.md`` and judges every project-level criterion. Proofs, measurements, and
    guardrails are settled deterministically and fed to the model, which judges the remaining
    ``evidence`` and ``llm`` criteria and scores the seven quality dimensions. Writes
    ``SCORECARD.md`` and ``evidence/score-release.json``. The release verdict is COMPLETE only when
    no completion blocker remains.
    """
    sea_path = target_dir / "SEA_TRIALS.md"
    manifest_path = target_dir / "MANIFEST.md"
    blueprint_dir = target_dir / "blueprint"
    document = load_sea_trials(sea_path)
    plan = parse_build_plan(manifest_path)
    build_dir = get_build_dir(target, target_dir)
    if not build_dir.is_dir():
        raise SpecificationError(f"build directory not found: {build_dir}")

    blockers: list[str] = []
    warnings: list[str] = []
    # The release gate is the one hard EARS gate. Earlier stages tolerate a wording defect so a
    # copy-editing slip never halts the pipeline, but a criterion the project is judged against
    # must read unambiguously before the project can be declared delivered.
    if document.wording:
        blockers.append(format_wording_failures(document))
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

    # A staged test kit is a read-only input. At scoring time the artifact under judgment is
    # fixed, so a substituted asset is reported rather than repaired — repairing it would change
    # what is being scored.
    tampered = tampered_build_assets(target_dir, blueprint_dir, build_dir)
    if tampered:
        blockers.append("Staged build asset was modified: " + ", ".join(tampered))

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
        warnings.append("Programmatic acceptance is vacuous: " + ", ".join(vacuous_proofs))
    proof_backed = {criterion for check in checks for criterion in check.sea_trials}
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
    # A required guardrail verified by proof is traceable work like any other: something must
    # declare ``Sea Trials: <id>``. Without that link the guardrail can only ever be unproven,
    # so the gap is reported here as missing coverage rather than surfacing as a bare breach.
    traceable_required = {
        trial.criterion_id
        for trial in document.trials
        if trial.required
        and (
            trial.trial_type in {"technical", "behavioral"}
            or (trial.trial_type == "guardrail" and trial.verification == "proof")
        )
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
        "warnings": warnings,
    }
    prompt = load_prompt("score_release")
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
        command_name="score release",
        parameters={"target": target},
        log_dir=log_dir,
        target=target,
        on_text=on_text,
        prompt_assembly=assembly,
    )
    if not result.ok or not result.text.strip():
        raise SpecificationError("score release LLM execution failed or returned no output")
    payload = _parse_json(result.text)
    raw_dimensions = payload.get("dimensions")
    if not isinstance(raw_dimensions, dict) or set(raw_dimensions) != set(DIMENSIONS):
        raise SpecificationError("score release output must score exactly the seven dimensions")
    dimensions: dict[str, int] = {}
    for name in DIMENSIONS:
        value = raw_dimensions[name]
        if not isinstance(value, int) or not 0 <= value <= 100:
            raise SpecificationError(f"score release dimension {name} must be an integer 0..100")
        dimensions[name] = value
    dimensions["acceptance_criteria_coverage"] = _coverage_penalty(
        dimensions["acceptance_criteria_coverage"], document.trials, deterministic_ids
    )

    trial_by_id = {trial.criterion_id: trial for trial in document.trials}
    model_criteria: dict[str, dict] = {}
    for item in payload.get("criteria", []):
        if not isinstance(item, dict) or item.get("id") not in trial_by_id:
            raise SpecificationError("score release output contains an unknown criterion ID")
        criterion_id = str(item["id"])
        if criterion_id in model_criteria:
            raise SpecificationError(f"score release output duplicates criterion {criterion_id}")
        model_criteria[criterion_id] = item
    if set(model_criteria) != set(trial_by_id):
        raise SpecificationError("score release output must judge every Sea Trial exactly once")

    measurements_by_id = {item.criterion_id: item for item in measurements}
    evidence_by_id = {str(item["criterion_id"]): item for item in evidence_facts}
    criteria: list[CriterionResult] = []
    for criterion_id, trial in trial_by_id.items():
        item = model_criteria[criterion_id]
        verdict = str(item.get("verdict", "INCONCLUSIVE")).upper()
        if verdict not in VALID_VERDICTS:
            raise SpecificationError(f"score release {criterion_id} has invalid verdict {verdict}")
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
                (result_item, integ)
                for check, result_item, integ in zip(
                    checks, acceptance, proof_integrity, strict=True
                )
                if criterion_id in check.sea_trials
            ]
            valid = [result_item for result_item, integ in referencing if integ.ok]
            if not referencing:
                verdict = "INCONCLUSIVE"
                evidence = ("no code-bound proof references this criterion",)
            elif not valid:
                reasons = "; ".join(reason for _, integ in referencing for reason in integ.reasons)
                evidence = (
                    "warning: proof passed but failed integrity: "
                    + (reasons or "no effective failure path"),
                )
            else:
                verdict = "PASS" if all(entry.passed for entry in valid) else "FAIL"
                evidence = tuple(
                    f"{entry.source}:{entry.check_id}={'PASS' if entry.passed else 'FAIL'}"
                    for entry in valid
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
            # A guardrail is absolute. An unproven never is not held, so INCONCLUSIVE blocks too —
            # but it is reported as UNPROVEN, because no evidence showed the prohibition violated.
            if item.verdict == "FAIL":
                blockers.append(f"Guardrail {item.criterion_id} is BREACHED: {trial.criterion}")
            elif item.verdict != "PASS":
                detail = item.evidence[0] if item.evidence else "no evidence supplied"
                blockers.append(
                    f"Guardrail {item.criterion_id} is UNPROVEN ({detail}): {trial.criterion}"
                )
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
    evidence_path = target_dir / "evidence" / "score-release.json"
    scorecard_path = target_dir / "SCORECARD.md"
    record = {
        "schema_version": 2,
        "recorded_at": _now(),
        "target": target,
        "complete": complete,
        "technical_score": score,
        "dimensions": dimensions,
        "criteria": [asdict(item) for item in criteria],
        "blockers": blockers,
        "warnings": warnings,
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
            warnings=tuple(warnings),
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
        tuple(warnings),
        improvements,
        complete,
        scorecard_path,
        evidence_path,
        result.execution_id,
    )
