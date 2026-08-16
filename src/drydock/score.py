"""Acceptance scoring: deterministic per-AC verification and the LLM release gate.

- ``drydock score ac`` runs each acceptance criterion's Programmatic Acceptance, applies proof
  integrity, and records a ``✓ PASS`` / ``✗ FAIL`` / ``— UNVERIFIED`` verdict per AC into
  ``SOUNDINGS.md`` with a timestamp. It is deterministic — no model call, no network — and is the
  sole writer of ``SOUNDINGS.md``: the trust-but-verify board the Commander scans instead of
  granting approvals.
- ``drydock score release`` judges the project-level criteria in ``SEA_TRIALS.md`` by observing
  the finished tree at grading time: it runs the governed gate and every command a trial names,
  reads the files trials point at, and hands the grader a tree it may read and probe. Nothing
  recorded during the build is evidence. The verdict is ``PASSED``, ``FAILED``, or ``ERROR``, and
  it writes ``SCORECARD.md`` and ``evidence/score-release.json``.

Both reuse the build_score primitives so the deterministic verdicts agree across paths.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

from drydock.acceptance import (
    AcceptanceObservation,
    ProgrammaticAcceptance,
    all_programmatic_acceptance,
    assertion_summary,
    failure_detail,
    observe_programmatic_acceptance,
    programmatic_acceptance_for_step,
    read_prepassed_acceptance,
)
from drydock.acceptance_contract import GateResult, load_contract, run_gate
from drydock.acceptance_requirements import authorization_for, requirement_available
from drydock.build_plan import BuildPlan, parse_build_plan
from drydock.build_score import (
    MEASUREMENT_TIMEOUT,
    CriterionResult,
    MeasurementResult,
    RunnerFn,
    TextCallback,
    _code_identity,
    _compare_measurement,
    _evidence_fact,
    _measurement_payload,
    _parse_json,
    _sha,
)
from drydock.errors import SpecificationError
from drydock.gate_policy import (
    MANUAL,
    MET,
    NOT_MET,
    PASSED,
    TRIAL_VERDICTS,
    GateOutcome,
    RunFacts,
    TrialFacts,
    fold,
)
from drydock.llm import run_prompt
from drydock.metadata import get_build_dir
from drydock.prompt_assembly import PromptAssembly
from drydock.prompts import load_prompt
from drydock.sea_trials import (
    SeaTrial,
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


def emit_failure(
    headline: str, details: Sequence[str] = (), *, stream: IO[str] | None = None
) -> None:
    """Name on stderr why a scoring command is exiting nonzero.

    A nonzero exit is an error, and an error states its cause on the error stream. The graded
    report on stdout is the full record; this is the part a caller that captured only stderr —
    a build script, a UAT harness, a CI step — must still be told. An empty stderr beside a
    nonzero exit tells that caller nothing, which is the defect this exists to prevent.
    """
    handle = stream if stream is not None else sys.stderr
    print(f"error: {headline}", file=handle)
    for line in details:
        print(f"  {line}", file=handle)


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
    # The bounded failure block — assertion, exit code, and the tail of what the check itself
    # reported. ``evidence`` is one line because SOUNDINGS.md is a table; this is what a reader
    # needs to act, and it is printed under the criterion rather than hidden in a log file.
    detail: tuple[str, ...] = ()


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


def ac_failure_lines(report: AcReport) -> tuple[str, ...]:
    """Name every criterion that failed, with its owner and the reason it failed."""
    lines: list[str] = []
    for verdict in report.verdicts:
        if verdict.status != FAIL:
            continue
        owner = "/".join(part for part in (verdict.feature, verdict.story) if part)
        location = "  ".join(part for part in (owner, verdict.source) if part)
        lines.append(f"{verdict.criterion_id}  {location}".rstrip())
        reason = list(verdict.detail) or (verdict.evidence or "").strip().splitlines()
        # The detail block is already bounded at the point it is built — assertion, location,
        # exit, criterion source, observed output, stderr tail. Truncating it again here cut it
        # off mid-block: a reader who captured only stderr got a ``check stderr:`` heading with
        # nothing under it, which is worse than no heading at all.
        lines.extend(f"  {line}" for line in reason)
    return tuple(lines)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _observation_verdict(
    obs: AcceptanceObservation, code: str = ""
) -> tuple[str, str, tuple[str, ...]]:
    """Map a per-assertion observation to a board ``(status, evidence, detail)`` triple.

    A passing proof that fails integrity analysis is demoted to ``UNVERIFIED`` (vacuous), so a
    green checkmark always reflects a proof that actually exercises behavior.

    A failure reports the assertion that failed and the tail of what the check observed, not the
    last line of a traceback. The last line of ``assert result.returncode == 0`` is the word
    ``AssertionError``, which names no defect and reads as an internal fault; the check's own
    reported output — ``10 passed, 1 failed`` — is the diagnosis, and it is on stdout.
    """
    if obs.skipped:
        summary = assertion_summary(obs.stderr, obs.error, override=obs.error)
        detail = failure_detail(
            stderr=obs.stderr,
            stdout=obs.stdout,
            return_code=obs.return_code,
            error=obs.error,
            override=obs.error,
            code=code,
        )
        return UNVERIFIED, summary, tuple(detail)
    if not obs.passed:
        summary = assertion_summary(obs.stderr, obs.error, override=obs.error)
        detail = failure_detail(
            stderr=obs.stderr,
            stdout=obs.stdout,
            return_code=obs.return_code,
            error=obs.error,
            override=obs.error,
            code=code,
        )
        return FAIL, summary, tuple(detail)
    if not obs.integrity_ok:
        reasons = "; ".join(obs.integrity_reasons)
        return UNVERIFIED, f"proof failed integrity: {reasons or 'no effective failure path'}", ()
    return PASS, "", ()


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
    # The criterion's own source, so a failure report can quote the code that raised rather than
    # naming a line number in a file the reader has to go find.
    code_by_id = {check.check_id: check.code for check in checks}
    verdicts: list[AcVerdict] = []
    rows: list[Sounding] = []
    for obs in observations:
        status, evidence, detail = _observation_verdict(obs, code_by_id.get(obs.check_id, ""))
        if status == PASS and obs.check_id in prepassed:
            status = PREPASSED
            detail = ()
            evidence = (
                "green at this block's baseline too, before its code existed — confirm the "
                "criterion exercises the story's work"
            )
        stamp = verified_at if status != UNVERIFIED else ""
        story, feature = owners.get(obs.source, ("", ""))
        verdicts.append(
            AcVerdict(
                obs.check_id, obs.intent, status, evidence, obs.source, story, feature, detail
            )
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


#: Where the grader may write an ephemeral probe. It sits inside the build tree so a probe
#: imports and calls the product exactly as the product runs, it is named so a reader can see at
#: a glance what left it, and Drydock removes it after grading whether or not the grader tidied
#: up. The guaranteed release is composed here, not typed by the model.
PROBE_DIR = ".drydock-probe"


@dataclass(frozen=True)
class TrialObservation:
    """What Drydock itself observed for one Sea Trial, at grading time.

    ``pinned`` is ``MET``, ``NOT MET``, or empty. A pinned verdict is a fact the grader may not
    argue with; an empty one leaves the criterion to the grader's judgement over the same
    evidence.
    """

    criterion_id: str
    kind: str
    source: str = ""
    return_code: int | None = None
    pinned: str = ""
    detail: str = ""
    output: str = ""


@dataclass(frozen=True)
class ReleaseResult:
    """The release verdict, its criteria, and where it was written."""

    target: str
    verdict: str
    statement: str
    criteria: tuple[CriterionResult, ...]
    blockers: tuple[str, ...]
    attestations: tuple[str, ...]
    warnings: tuple[str, ...]
    improvements: tuple[str, ...]
    scorecard_path: Path
    evidence_path: Path
    execution_id: str

    @property
    def complete(self) -> bool:
        """Whether every criterion was met. MANUAL attests and never withholds completion."""
        return self.verdict == PASSED

    def exit_code(self) -> int:
        return 0 if self.verdict == PASSED else 1


def _command_observation(trial: SeaTrial, build_dir: Path) -> TrialObservation:
    """Run the command a trial names, now, against the final tree.

    A trial that names a command is settled by that command's own exit status unless it also
    declares a threshold, in which case the number is compared. A command Drydock could not
    execute pins nothing: that is a statement about the machine, not about the product.
    """
    source = json.dumps(list(trial.command))
    try:
        completed = subprocess.run(
            list(trial.command),
            cwd=build_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=MEASUREMENT_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return TrialObservation(
            trial.criterion_id, "command", source, detail=f"command could not run: {exc}"
        )
    output = completed.stdout.strip()
    tail = "\n".join((output or completed.stderr.strip()).splitlines()[-20:])
    if trial.target is not None or trial.operator:
        measured = _measured_value(trial, output, source, completed.returncode)
        pinned = {"PASS": MET, "FAIL": NOT_MET}.get(measured.status, "")
        return TrialObservation(
            trial.criterion_id,
            "measurement",
            source,
            return_code=completed.returncode,
            pinned=pinned,
            detail=measured.detail or f"{measured.value} {measured.unit}".strip(),
            output=tail,
        )
    passed = completed.returncode == 0
    return TrialObservation(
        trial.criterion_id,
        "command",
        source,
        return_code=completed.returncode,
        pinned=MET if passed else NOT_MET,
        detail=f"{source} exited {completed.returncode}",
        output=tail,
    )


def _measured_value(trial: SeaTrial, text: str, source: str, return_code: int) -> MeasurementResult:
    """Compare a trial's declared threshold against the command's own output."""
    if trial.extract:
        match = re.search(trial.extract, text, re.MULTILINE)
        if match is None:
            return MeasurementResult(
                trial.criterion_id,
                "INCONCLUSIVE",
                source=source,
                return_code=return_code,
                detail=f"Extract pattern did not match the measurement output: {text[:200]!r}",
            )
        try:
            return _compare_measurement(
                trial, float(match.group(1)), trial.unit, source, return_code
            )
        except (TypeError, ValueError):
            return MeasurementResult(
                trial.criterion_id,
                "INCONCLUSIVE",
                source=source,
                return_code=return_code,
                detail=f"Extract captured a non-numeric value: {match.group(1)!r}",
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
    return _compare_measurement(trial, value, unit, source, return_code)


def _observe_trials(
    trials: tuple[SeaTrial, ...], *, target_dir: Path, build_dir: Path
) -> tuple[TrialObservation, ...]:
    """Observe every trial Drydock can settle for itself, at grading time.

    ``Verification:`` selects nothing here. What a trial *names* is what gets observed: a command
    is run, a file is read, and a criterion naming neither is left to the grader, which may probe
    the tree for itself.
    """
    observations: list[TrialObservation] = []
    for trial in trials:
        if trial.command:
            observations.append(_command_observation(trial, build_dir))
            continue
        if trial.evidence:
            fact = _evidence_fact(trial, target_dir)
            if fact is None:
                continue
            observations.append(
                TrialObservation(
                    trial.criterion_id,
                    "evidence",
                    trial.evidence,
                    detail=str(fact.get("error", "")),
                    output=str(fact.get("content", ""))[:4000],
                )
            )
    return tuple(observations)


def _render_release_scorecard(
    outcome: GateOutcome,
    trials: dict[str, SeaTrial],
    criteria,
    *,
    code_identity: str,
    improvements: tuple[str, ...],
) -> str:
    """Render SCORECARD.md as the verdict listing plus its provenance."""
    lines = [
        f"# Release Scorecard: {outcome.target}",
        "",
        f"- Verdict: {outcome.verdict}",
        f"- Code identity: {code_identity or '-'}",
        "",
        "## Project acceptance",
        "",
        "| ID | Type | Criterion | Verdict | Observed |",
        "|---|---|---|---|---|",
    ]
    for item in criteria:
        trial = trials[item.criterion_id]
        observed = "; ".join(item.evidence) or item.rationale
        lines.append(
            f"| {item.criterion_id} | {trial.trial_type} | {trial.criterion.replace('|', '/')} | "
            f"{item.verdict} | {observed.replace('|', '/')} |"
        )
    lines.extend(["", "## Failures", ""])
    failures = [
        f"{item.criterion_id}: {trials[item.criterion_id].criterion}"
        for item in criteria
        if item.verdict == NOT_MET
    ]
    failures.extend(outcome.demonstrated_failures)
    lines.extend(f"- {item}" for item in failures or ("None.",))
    lines.extend(["", "## Manual verification required", ""])
    manual = [
        f"{item.criterion_id}: {trials[item.criterion_id].criterion}"
        for item in criteria
        if item.verdict == MANUAL
    ]
    lines.extend(f"- {item}" for item in manual or ("None.",))
    lines.extend(["", "## Could not judge", ""])
    lines.extend(f"- {item}" for item in outcome.kit_faults or ("None.",))
    lines.extend(["", "## Advisory warnings", ""])
    lines.extend(f"- {item}" for item in outcome.reported or ("None.",))
    lines.extend(["", "## Ranked improvements", ""])
    lines.extend(f"{index}. {item}" for index, item in enumerate(improvements, 1))
    if not improvements:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def _trial_verdict(raw: object, criterion_id: str) -> str:
    verdict = str(raw or "").strip().upper().replace("_", " ")
    if verdict not in TRIAL_VERDICTS:
        raise SpecificationError(
            f"score release {criterion_id} has invalid verdict {verdict!r}; expected one of "
            + ", ".join(TRIAL_VERDICTS)
        )
    return verdict


def score_release(
    target: str,
    target_dir: Path,
    *,
    runner: RunnerFn | None = None,
    on_text: TextCallback | None = None,
    model: str | None = None,
    llm_provider: str | None = None,
    log_dir: Path | None = None,
) -> ReleaseResult:
    """Judge the finished project against its Sea Trials by observing it, now.

    Score observes; it does not read reports. A verdict about a finished project cannot be
    assembled from observations of intermediate states — an assertion that passed at block 3 is a
    statement about the tree as it stood at block 3, and block 7 can have broken it. So every
    record the build left behind (assertion outcomes, block states, gate outcomes, the Manifest)
    is history, and none of it reaches this verdict. What reaches it is what Drydock can observe
    at grading time: the governed gate is executed rather than inherited, every command a trial
    names is run against the final tree, files are read, and the grader is handed that tree with
    tools so it can read the source and write an ephemeral probe for behavior no command covers.

    Sea Trials are referenced by nothing. Proof tags, ``accepts:`` coverage, and ``Verification:``
    as a mechanism selector are all gone: they bound a criterion to a test that had already run,
    which moved the model's judgement to a tag typed hours earlier in a different artifact with no
    evidence attached — and then refused five criteria the grader had positively found met.

    Writes ``SCORECARD.md`` and ``evidence/score-release.json``. The verdict is ``PASSED``,
    ``FAILED``, or ``ERROR``.
    """
    sea_path = target_dir / "SEA_TRIALS.md"
    blueprint_dir = target_dir / "blueprint"
    document = load_sea_trials(sea_path)
    build_dir = get_build_dir(target, target_dir)
    if not build_dir.is_dir():
        raise SpecificationError(f"build directory not found: {build_dir}")

    kit_faults: list[str] = []
    demonstrated: list[str] = []
    reported: list[str] = []

    # Step 1 — can Drydock judge at all? A substituted staged asset means the thing being scored
    # is not the thing that was built, so no verdict about the product is available.
    tampered = tampered_build_assets(target_dir, blueprint_dir, build_dir)
    if tampered:
        kit_faults.append("Staged build asset was modified: " + ", ".join(tampered))

    # Step 2 — gather evidence by observing, never by inheriting. The governed gate is a command,
    # so score runs it. The build layer runs the same command for repair signal; neither run is
    # the other's evidence.
    contract = load_contract(target_dir)
    full_gate: GateResult | None = None
    if contract.full:
        full_gate = run_gate("full", contract.full, build_dir=build_dir)
        if full_gate.blocks:
            demonstrated.append(f"Governed acceptance gate failed: {full_gate.rendered}")
        elif not full_gate.passed:
            kit_faults.append(f"Governed acceptance gate could not run: {full_gate.rendered}")

    observations = _observe_trials(document.trials, target_dir=target_dir, build_dir=build_dir)

    # Hygiene is provenance, never a verdict input: a gate may only block on a fault domain it can
    # distinguish, and git state cannot tell a defective product from a test run that wrote a file.
    code_identity, dirty = _code_identity(build_dir)
    if not code_identity:
        reported.append("Build directory has no usable Git code identity")
    if dirty:
        reported.append("Build directory has uncommitted changes")
    if document.questions:
        reported.append("Sea Trials has unresolved QUESTIONS")

    facts = {
        "target": target,
        "build_directory": str(build_dir),
        "probe_directory": PROBE_DIR,
        "code": {"identity": code_identity, "dirty": dirty},
        "governed_gate": full_gate.to_dict() if full_gate else None,
        "observations": [asdict(item) for item in observations],
        "sea_trials": [asdict(item) for item in document.trials],
        "reported": reported,
    }
    prompt = load_prompt("score_release")
    rendered = (
        prompt.body + "\n\n## Evidence facts\n\n```json\n" + json.dumps(facts, indent=2) + "\n```\n"
    )
    assembly = PromptAssembly.single_prompt(rendered)
    run = runner if runner is not None else run_prompt
    probe_root = build_dir / PROBE_DIR
    try:
        probe_root.mkdir(parents=True, exist_ok=True)
        result = run(
            rendered,
            build_dir,
            llm=llm_provider,
            model=model or prompt.model,
            command_name="score release",
            parameters={"target": target},
            log_dir=log_dir,
            target=target,
            on_text=on_text,
            prompt_assembly=assembly,
            allow_tools=True,
        )
    finally:
        # The probe is ephemeral by construction. Whatever the grader wrote, and whether or not it
        # returned at all, the tree it was judging is left as it was found.
        shutil.rmtree(probe_root, ignore_errors=True)
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

    pinned = {item.criterion_id: item for item in observations if item.pinned}
    rationales: dict[str, str] = {}
    trial_facts: list[TrialFacts] = []
    for criterion_id, trial in trial_by_id.items():
        item = model_criteria[criterion_id]
        graded = _trial_verdict(item.get("verdict"), criterion_id)
        rationales[criterion_id] = str(item.get("rationale", "")).strip()
        raw_evidence = item.get("evidence", [])
        citations = (
            tuple(str(value) for value in raw_evidence) if isinstance(raw_evidence, list) else ()
        )
        observed = pinned.get(criterion_id)
        if observed is not None:
            citations = (observed.detail,) + citations
        trial_facts.append(
            TrialFacts(
                criterion_id=criterion_id,
                graded=graded,
                citations=citations,
                demonstrated_failure=(
                    observed.detail if observed is not None and observed.pinned == NOT_MET else ""
                ),
                governed_pass=observed is not None and observed.pinned == MET,
                guardrail=trial.trial_type == "guardrail",
                criterion=trial.criterion,
            )
        )

    outcome = fold(
        RunFacts(
            target=target,
            trials=tuple(trial_facts),
            kit_faults=tuple(kit_faults),
            demonstrated_failures=tuple(demonstrated),
            reported=tuple(reported),
        )
    )
    criteria = tuple(
        CriterionResult(
            item.criterion_id,
            item.verdict,
            rationales.get(item.criterion_id, "") or item.basis,
            item.citations or (item.basis,),
        )
        for item in outcome.trials
    )
    blockers = tuple(
        f"{item.criterion_id} is NOT MET: {trial_by_id[item.criterion_id].criterion}"
        for item in outcome.trials
        if item.verdict == NOT_MET
    ) + tuple(outcome.demonstrated_failures)
    attestations = tuple(
        f"{item.criterion_id} needs manual verification: {trial_by_id[item.criterion_id].criterion}"
        for item in outcome.trials
        if item.verdict == MANUAL
    )

    criterion_improvements = [
        f"Resolve {item.criterion_id} ({item.verdict}): {trial_by_id[item.criterion_id].criterion}"
        for item in outcome.trials
        if item.verdict != MET
    ]
    raw_improvements = payload.get("improvements", [])
    improvements = tuple(
        dict.fromkeys(
            criterion_improvements
            + [str(item).strip() for item in raw_improvements if str(item).strip()]
        )
    )
    evidence_path = target_dir / "evidence" / "score-release.json"
    scorecard_path = target_dir / "SCORECARD.md"
    record = {
        "schema_version": 5,
        "recorded_at": _now(),
        "target": target,
        "verdict": outcome.verdict,
        "verdict_line": outcome.statement.splitlines()[0],
        "statement": outcome.statement,
        "complete": outcome.verdict == PASSED,
        "governed_gate": full_gate.to_dict() if full_gate else None,
        "criteria": [asdict(item) for item in criteria],
        "guardrail_ids": [
            trial.criterion_id for trial in document.trials if trial.trial_type == "guardrail"
        ],
        "observations": [asdict(item) for item in observations],
        "blockers": list(blockers),
        "attestations": list(attestations),
        "kit_faults": list(outcome.kit_faults),
        "warnings": list(outcome.reported),
        "improvements": list(improvements),
        "identities": {
            "code": code_identity,
            "sea_trials": _sha(sea_path),
            "blueprint": {path.name: _sha(path) for path in sorted(blueprint_dir.glob("*.md"))},
        },
        "execution_id": result.execution_id,
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    scorecard_path.write_text(
        _render_release_scorecard(
            outcome,
            trial_by_id,
            criteria,
            code_identity=code_identity,
            improvements=improvements,
        ),
        encoding="utf-8",
        newline="\n",
    )
    return ReleaseResult(
        target=target,
        verdict=outcome.verdict,
        statement=outcome.statement,
        criteria=criteria,
        blockers=blockers,
        attestations=attestations,
        warnings=tuple(outcome.reported),
        improvements=improvements,
        scorecard_path=scorecard_path,
        evidence_path=evidence_path,
        execution_id=result.execution_id,
    )
