"""Deterministic, LLM-free scoring: per-AC verification and the release gate.

Two capabilities sit beside the model-assisted ``drydock build score``:

- ``drydock score ac`` runs each acceptance criterion's Programmatic Acceptance, applies proof
  integrity, and records a ``✓ PASS`` / ``✗ FAIL`` / ``— UNVERIFIED`` verdict per AC into
  ``SOUNDINGS.md`` with a timestamp. It is the trust-but-verify board: the Commander scans
  checkmarks instead of granting approvals.
- ``drydock score release`` re-runs the deterministic subset of the completion gate — proofs,
  measurements, guardrails, Manifest completion, clean worktree — with no model call and no
  network. It is the CI-portable gate: same inputs, same exit code, every environment.

Both reuse the build_score primitives so the deterministic verdicts agree with the model path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from drydock.acceptance import (
    ProgrammaticAcceptance,
    parse_programmatic_acceptance,
    programmatic_acceptance_for_step,
    run_programmatic_acceptance,
)
from drydock.build_plan import parse_build_plan, stale_applied_specs
from drydock.build_score import _code_identity, _measure
from drydock.errors import SpecificationError
from drydock.metadata import get_build_dir
from drydock.proof_integrity import analyze_proof
from drydock.sea_trials import load_sea_trials
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


@dataclass(frozen=True)
class AcReport:
    target: str
    verdicts: tuple[AcVerdict, ...]
    soundings_path: Path
    verified_at: str

    def exit_code(self) -> int:
        # A FAIL is a hard failure; UNVERIFIED is surfaced but does not fail the run, since not
        # every story carries an executable proof (spikes, pure UI). The board shows the gap.
        return 1 if any(v.status == FAIL for v in self.verdicts) else 0


@dataclass(frozen=True)
class GateResult:
    target: str
    passed: bool
    blockers: tuple[str, ...]

    def exit_code(self) -> int:
        return 0 if self.passed else 1


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _story_verdict(
    checks: tuple[ProgrammaticAcceptance, ...],
    *,
    build_dir: Path,
    target_dir: Path,
    blueprint_dir: Path,
) -> tuple[str, str]:
    """Deterministic verdict for one story's proofs: PASS, FAIL, or UNVERIFIED with evidence."""
    if not checks:
        return UNVERIFIED, "no Programmatic Acceptance proves this story"
    integrity = [analyze_proof(check.code) for check in checks]
    valid = [check for check, integ in zip(checks, integrity, strict=True) if integ.ok]
    if not valid:
        reasons = "; ".join(reason for integ in integrity for reason in integ.reasons)
        return UNVERIFIED, f"proof failed integrity: {reasons or 'no effective failure path'}"
    results = run_programmatic_acceptance(
        tuple(valid), build_dir=build_dir, target_dir=target_dir, blueprint_dir=blueprint_dir
    )
    failed = [r for r in results if not r.passed]
    if failed:
        return FAIL, "; ".join(f"{r.check_id}={r.error or 'FAIL'}" for r in failed)
    return PASS, ", ".join(f"{r.source}:{r.check_id}" for r in results)


def verify_acs(target: str, target_dir: Path) -> AcReport:
    """Verify every acceptance criterion deterministically and write results to Soundings."""
    manifest_path = target_dir / "MANIFEST.md"
    blueprint_dir = target_dir / "blueprint"
    plan = parse_build_plan(manifest_path)
    build_dir = get_build_dir(target, target_dir)
    if not build_dir.is_dir():
        raise SpecificationError(f"build directory not found: {build_dir}")

    by_id = plan.by_id()
    verified_at = _now()

    # One verdict per parent story, cached so shared stories run their proofs once.
    story_cache: dict[str, tuple[str, str]] = {}

    def story_verdict(story_id: str) -> tuple[str, str]:
        if story_id not in story_cache:
            story = by_id.get(story_id)
            checks = (
                programmatic_acceptance_for_step(story, blueprint_dir) if story is not None else ()
            )
            story_cache[story_id] = _story_verdict(
                checks, build_dir=build_dir, target_dir=target_dir, blueprint_dir=blueprint_dir
            )
        return story_cache[story_id]

    verdicts: list[AcVerdict] = []
    rows: list[Sounding] = []
    for block in plan.blocks:
        if block.block_type != "ac":
            continue
        status, evidence = story_verdict(block.parent or "")
        verdicts.append(AcVerdict(block.block_id, block.name, status, evidence))
        stamp = verified_at if status != UNVERIFIED else ""
        rows.append(Sounding(block.block_id, block.name, _VERIFIED_LABEL[status], evidence, stamp))

    soundings_path = target_dir / "SOUNDINGS.md"
    soundings_path.write_text(render_soundings(rows), encoding="utf-8", newline="\n")
    return AcReport(target, tuple(verdicts), soundings_path, verified_at)


def deterministic_gate(target: str, target_dir: Path) -> GateResult:
    """Deterministic release gate: pass only when every mechanically-checkable gate holds.

    Verifies proofs (with integrity), measurements, guardrails, Manifest completion, and a clean
    worktree — no model call. Criteria that are inherently model- or human-judged (``llm``,
    ``evidence``, qualitative, outcome) are deferred to ``drydock build score`` and do not block,
    except guardrails: a guardrail that cannot be verified deterministically fails the gate,
    because a guardrail is absolute.
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

    executable = [b for b in plan.blocks if b.block_type in {"story", "spike"}]
    incomplete = [b.block_id for b in executable if b.state != "closed/verified"]
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

    # Proofs, keyed to the criteria they reference, with integrity applied.
    checks = tuple(
        check
        for path in sorted(blueprint_dir.glob("*.md"))
        for check in parse_programmatic_acceptance(path)
    )
    integrity = [analyze_proof(check.code) for check in checks]
    acceptance = run_programmatic_acceptance(
        checks, build_dir=build_dir, target_dir=target_dir, blueprint_dir=blueprint_dir
    )
    proof_pass: dict[str, bool] = {}  # criterion_id -> all referencing proofs passed
    proof_seen: set[str] = set()
    for check, integ, result in zip(checks, integrity, acceptance, strict=True):
        for criterion in check.sea_trials:
            proof_seen.add(criterion)
            proof_pass[criterion] = proof_pass.get(criterion, True) and result.passed

    for trial in document.trials:
        cid = trial.criterion_id
        guardrail = trial.trial_type == "guardrail"
        required = trial.required or guardrail
        if not required:
            continue
        if trial.verification == "measurement":
            measured = _measure(trial, target_dir=target_dir, build_dir=build_dir)
            if measured.status != PASS:
                label = "Guardrail" if guardrail else "Required Sea Trial"
                detail = measured.detail or measured.source
                blockers.append(f"{label} {cid} is {measured.status} ({detail})")
            continue
        if trial.verification == "proof":
            if cid not in proof_seen or cid not in proof_pass:
                label = "Guardrail" if guardrail else "Required Sea Trial"
                blockers.append(f"{label} {cid} has no code-bound proof")
            elif not proof_pass[cid]:
                label = "Guardrail" if guardrail else "Required Sea Trial"
                blockers.append(f"{label} {cid} FAILED its proof")
            continue
        # Reaches here only for evidence/llm verification. A guardrail is absolute, so one that
        # cannot be checked deterministically fails the gate; other criteria defer to build score.
        if guardrail:
            blockers.append(
                f"Guardrail {cid} cannot be verified deterministically ({trial.verification})"
            )

    return GateResult(target, not blockers, tuple(blockers))
