"""Acceptance scoring: deterministic per-AC verification and the LLM release gate.

- ``drydock score ac`` runs each acceptance criterion's Programmatic Acceptance, applies proof
  integrity, and records a ``✓ PASS`` / ``✗ FAIL`` / ``— UNVERIFIED`` verdict per AC into
  ``SOUNDINGS.md`` with a timestamp. It is deterministic — no model call, no network — and is the
  sole writer of ``SOUNDINGS.md``: the trust-but-verify board the Commander scans instead of
  granting approvals.
- ``drydock score release`` judges the project-level criteria in ``SEA_TRIALS.md`` against the
  completed build. Deterministic proofs, measurements, and guardrails are settled mechanically;
  the model judges only the remaining ``evidence`` and ``llm`` criteria. The verdict is those
  criteria and nothing else. It writes ``SCORECARD.md`` and ``evidence/score-release.json``.

Both reuse the build_score primitives so the deterministic verdicts agree across paths.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from drydock.acceptance import (
    OUTCOME_FAIL,
    AcceptanceObservation,
    ProgrammaticAcceptance,
    all_programmatic_acceptance,
    observe_programmatic_acceptance,
    parse_programmatic_acceptance,
    programmatic_acceptance_for_step,
    read_prepassed_acceptance,
    run_programmatic_acceptance,
    tally_outcomes,
)
from drydock.acceptance_contract import GateResult, load_contract, run_gate
from drydock.acceptance_requirements import authorization_for, requirement_available
from drydock.build_plan import FINISHED_STATES, BuildPlan, parse_build_plan, stale_applied_specs
from drydock.build_score import (
    VALID_VERDICTS,
    BuildScoreResult,
    CriterionResult,
    RunnerFn,
    TextCallback,
    _code_identity,
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
    load_sea_trials,
)
from drydock.source_roles import tampered_build_assets
from drydock.standard_artifacts import (
    VERIFIED_FAIL,
    VERIFIED_PASS,
    VERIFIED_PREPASSED,
    VERIFIED_UNVERIFIED,
    Sounding,
    render_soundings,
)
from drydock.target_environment import provision_uv_environment

PASS = "PASS"
FAIL = "FAIL"
UNVERIFIED = "UNVERIFIED"
#: A criterion that ran green here but was *also* green at its block's baseline, before that
#: block's code existed. Reported as its own verdict rather than folded into PASS, because the two
#: are not the same claim: this one has not shown that the story's work is what satisfies it. It
#: is not a failure and does not affect the exit code — a criterion measuring a deliverable that
#: legitimately already existed looks identical, and only the author can tell which this is.
PREPASSED = "PREPASSED"

_VERIFIED_LABEL = {
    PASS: VERIFIED_PASS,
    FAIL: VERIFIED_FAIL,
    UNVERIFIED: VERIFIED_UNVERIFIED,
    PREPASSED: VERIFIED_PREPASSED,
}


@dataclass(frozen=True)
class AcVerdict:
    criterion_id: str
    summary: str
    status: str  # PASS | FAIL | UNVERIFIED | PREPASSED
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


def _provision_authorized_environment(
    checks: tuple[ProgrammaticAcceptance, ...],
    plan: BuildPlan,
    target_dir: Path,
    build_dir: Path,
) -> None:
    """Use the same authorization and uv provisioning contract as Build."""
    missing = []
    for check in checks:
        current_approval = False
        for requirement in check.requirements:
            if requirement_available(requirement, build_dir):
                continue
            authorization = authorization_for(
                requirement,
                target_dir=target_dir,
                build_dir=build_dir,
                current_manifest_approved=current_approval,
            )
            if not authorization.authorized:
                return
            missing.append(requirement)
    if any(requirement.kind == "python-package" for requirement in missing):
        provision_uv_environment(build_dir)


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
    _provision_authorized_environment(checks, plan, target_dir, build_dir)
    observations = observe_programmatic_acceptance(
        checks,
        build_dir=build_dir,
        target_dir=target_dir,
        blueprint_dir=blueprint_dir,
        strict_target=True,
    )

    owners = _blueprint_owners(plan)
    # Grading runs against a built tree, where a criterion satisfied by the product and one
    # satisfied by its absence look identical. Only the build's baseline separates them, so this
    # reports what the build recorded instead of re-deriving it from output.
    prepassed = read_prepassed_acceptance(target_dir / "evidence")
    verdicts: list[AcVerdict] = []
    rows: list[Sounding] = []
    for obs in observations:
        status, evidence = _observation_verdict(obs)
        if status == PASS and obs.check_id in prepassed:
            status = PREPASSED
            evidence = (
                "green at this block's baseline too, before its code existed — confirm the "
                "criterion exercises the story's work"
            )
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
    guardrails are settled deterministically; the model judges only the remaining ``evidence`` and
    ``llm`` criteria. Writes ``SCORECARD.md`` and ``evidence/score-release.json``.

    The gate is the criteria and nothing else: COMPLETE when every required Sea Trial passes and
    no guardrail is breached. It used to also average seven model-emitted 0..100 dimensions and
    block under 80, or under 60 on any one of them, which meant a project that satisfied every
    criterion its Commander wrote could still be refused by an opinion — and a different opinion
    on the next run. A release gate has to be reproducible, so the number is gone.
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
    # The governed full gate. When the Commander declares one in ACCEPTANCE.json, its classified
    # exit status is the product verdict and it blocks on its own — no model judgement, no proof
    # binding, no prose. This is the difference between a release gate that runs the acceptance
    # command and one that asks whether model-authored criteria happened to tag the right Sea
    # Trial id, which is what the proof path does when a criterion declares no Command.
    contract = load_contract(target_dir)
    full_gate: GateResult | None = None
    if contract.full:
        full_gate = run_gate("full", contract.full, build_dir=build_dir)
        if full_gate.blocks:
            blockers.append(f"Governed acceptance gate failed: {full_gate.rendered}")
        elif not full_gate.passed:
            blockers.append(f"Governed acceptance gate could not run: {full_gate.rendered}")
    executable = [block for block in plan.blocks if block.block_type in {"story", "spike"}]
    incomplete = [block.block_id for block in executable if block.state not in FINISHED_STATES]
    if incomplete:
        # Reported, not gating. The Manifest is the plan for meeting the contract, not the
        # contract: a story is a means. Blocking on its state made story acceptance a release
        # input through the back door — a criterion the model wrote and got wrong closed a
        # story ``closed/failed`` and failed a release whose every Sea Trial passed. What the
        # Manifest was standing in for — a contract satisfied by work nobody did — is covered
        # directly below, where a required Sea Trial without implementation or proof coverage
        # blocks. That tests the contract; this tested the plan.
        warnings.append("Manifest work is not closed/verified: " + ", ".join(incomplete))
    # Hygiene is reported, never gating. A gate may only block on a fault domain it can
    # distinguish, and none of these three can distinguish a defective product from tidy
    # bookkeeping. The case that settled it: a ReadingList run passed every Sea Trial and every
    # assertion, then failed the release because running the project's own test suite created
    # `instance/reading_list.sqlite3` and left the tree dirty. Drydock ran the tests, the tests
    # wrote a file, and Drydock refused the release because a file was there. Git state is
    # evidence about the workspace; it is not project acceptance.
    stale = stale_applied_specs(plan, blueprint_dir)
    if stale:
        warnings.append(
            "Applied Blueprint specifications are stale: " + ", ".join(s.rel_path for s in stale)
        )
    code_identity, dirty = _code_identity(build_dir)
    if not code_identity:
        warnings.append("Build directory has no usable Git code identity")
    if dirty:
        warnings.append("Build directory has uncommitted changes")
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
    _provision_authorized_environment(checks, plan, target_dir, build_dir)
    acceptance = run_programmatic_acceptance(
        checks,
        build_dir=build_dir,
        target_dir=target_dir,
        blueprint_dir=blueprint_dir,
        strict_target=True,
    )
    proof_integrity = tuple(analyze_proof(check.code) for check in checks)
    # Story acceptance is reported, never an input to the release decision. It already gates the
    # release by construction: a story whose assertions do not close does not build. The release
    # gate's single input is Sea Trials.
    outcomes = tally_outcomes(acceptance)
    failed_acceptance = [check.check_id for check in acceptance if check.outcome == OUTCOME_FAIL]
    if failed_acceptance:
        warnings.append("Programmatic acceptance failed: " + ", ".join(failed_acceptance))
    unverified_acceptance = [check.check_id for check in acceptance if check.unverified]
    if unverified_acceptance:
        warnings.append(
            "Programmatic acceptance was unverified (harness defect, not a build defect): "
            + ", ".join(unverified_acceptance)
        )
    vacuous_proofs = [
        check.check_id for check, integ in zip(checks, proof_integrity, strict=True) if not integ.ok
    ]
    if vacuous_proofs:
        warnings.append("Programmatic acceptance is vacuous: " + ", ".join(vacuous_proofs))
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
    # Guardrails are exempt: no story builds a prohibition, and nothing is obliged to declare
    # ``Sea Trials: <id>`` for one. A guardrail no proof reaches is reported UNPROVEN and carried
    # as a manual-verification attestation, not as a coverage failure.
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
        "story_acceptance": {
            **outcomes.to_dict(),
            "note": (
                "Reported, not gating, by any path. The release gate's only input is Sea "
                "Trials; Manifest state is the plan for meeting the contract, not the "
                "contract. UNVERIFIED assertions never reached the code under test and say "
                "nothing about the build."
            ),
        },
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

    attestations: list[str] = []
    for item in criteria:
        trial = trial_by_id[item.criterion_id]
        if trial.trial_type == "guardrail":
            # A guardrail is absolute, and Required does not apply. A breach is a demonstrated
            # failure and blocks the release. An unproven guardrail is not: no evidence showed
            # the prohibition violated, and many prohibitions worth writing admit no automated
            # proof at all. It qualifies the release with an attestation a human must settle.
            if item.verdict == "FAIL":
                blockers.append(f"Guardrail {item.criterion_id} is BREACHED: {trial.criterion}")
            elif item.verdict != "PASS":
                detail = item.evidence[0] if item.evidence else "no evidence supplied"
                attestations.append(
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
        "schema_version": 4,
        "recorded_at": _now(),
        "target": target,
        "complete": complete,
        "qualified": complete and bool(attestations),
        "governed_gate": full_gate.to_dict() if full_gate else None,
        "criteria": [asdict(item) for item in criteria],
        "blockers": blockers,
        "attestations": attestations,
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
        "story_acceptance": {
            **outcomes.to_dict(),
            "note": (
                "Reported, not gating, by any path. The release gate's only input is Sea "
                "Trials; Manifest state is the plan for meeting the contract, not the "
                "contract. UNVERIFIED assertions never reached the code under test and say "
                "nothing about the build."
            ),
        },
        "execution_id": result.execution_id,
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    scorecard_path.write_text(
        _render_scorecard(
            target=target,
            complete=complete,
            criteria=tuple(criteria),
            trials=trial_by_id,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
            improvements=improvements,
            code_identity=code_identity,
            attestations=tuple(attestations),
        ),
        encoding="utf-8",
        newline="\n",
    )
    return BuildScoreResult(
        target,
        tuple(criteria),
        tuple(blockers),
        tuple(warnings),
        improvements,
        complete,
        scorecard_path,
        evidence_path,
        result.execution_id,
        tuple(attestations),
    )
