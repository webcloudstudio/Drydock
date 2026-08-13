"""The release gate fold: a pure function from run evidence to a terminal verdict.

This is steps 3 through 5 of the ``score release`` pipeline — pin what is settled, accept the
grader's verdicts, fold them into one answer — with no filesystem access, no LLM, and no
knowledge of how the evidence was gathered. Keeping it pure is the point: the policy can then be
replayed over recorded runs, so a change to the gate is validated against the whole corpus of
past evidence rather than against one fresh run.

The rules it implements:

* **Four terminal verdicts.** ``PASSED``, ``PENDING MANUAL VERIFICATION``, ``FAILED``, ``ERROR``.
  ``PENDING`` is not a failure and exits zero — a project with an open question is not a project
  that failed.
* **The asymmetric evidence rule.** MET may be reached by inference; NOT MET requires a
  demonstration. A grader verdict of NOT MET that cites no artifact exhibiting the failure is
  absence of evidence, and absence of evidence yields PENDING. Drydock can only fail a project by
  exhibiting a failure.
* **Deterministic evidence is input, not override.** A demonstrated failure bound to a criterion
  pins NOT MET and cannot be argued away; a governed gate pass pins MET; otherwise the grader's
  verdict stands. ``Verification:`` selects no mechanism of its own.
* **A guardrail is not a special kind of criterion.** ``Type: guardrail`` is reporting metadata.
  It gets no inference ban, no separate vocabulary, and no absolute-prohibition logic — the
  asymmetry rule already prevents a prohibition from failing for want of positive proof.
* **Hygiene is not project acceptance.** Git state, staleness, and Manifest closure are reported
  and never reach the verdict.
* **ERROR is computed first.** If Drydock could not execute the judgement, it claims nothing about
  the product rather than reporting a product failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MET = "MET"
NOT_MET = "NOT MET"
PENDING = "PENDING"
TRIAL_VERDICTS = (MET, NOT_MET, PENDING)

PASSED = "PASSED"
PENDING_MANUAL_VERIFICATION = "PENDING MANUAL VERIFICATION"
FAILED = "FAILED"
ERROR = "ERROR"
TERMINAL_VERDICTS = (PASSED, PENDING_MANUAL_VERIFICATION, FAILED, ERROR)

_EXIT_CODES = {PASSED: 0, PENDING_MANUAL_VERIFICATION: 0, FAILED: 1, ERROR: 1}


@dataclass(frozen=True)
class TrialFacts:
    """Everything the fold knows about one Sea Trial.

    ``graded`` is what the grader returned. ``demonstrated_failure`` and ``governed_pass`` are
    deterministic findings bound to this criterion, which take precedence over the grade.
    ``citations`` are the artifacts the grader named; a NOT MET grade with none is not a
    demonstration.
    """

    criterion_id: str
    graded: str = PENDING
    citations: tuple[str, ...] = ()
    demonstrated_failure: str = ""
    governed_pass: bool = False
    guardrail: bool = False
    criterion: str = ""

    def __post_init__(self) -> None:
        if self.graded not in TRIAL_VERDICTS:
            raise ValueError(f"{self.criterion_id}: invalid trial verdict {self.graded!r}")


@dataclass(frozen=True)
class RunFacts:
    """The evidence a single scored run offers the fold.

    ``kit_faults`` are reasons Drydock could not judge at all. ``reported`` carries hygiene and
    Manifest observations, which are surfaced to the operator and contribute nothing.
    """

    target: str
    trials: tuple[TrialFacts, ...] = ()
    kit_faults: tuple[str, ...] = ()
    reported: tuple[str, ...] = ()


@dataclass(frozen=True)
class TrialOutcome:
    """One trial's settled verdict and why it settled there."""

    criterion_id: str
    verdict: str
    basis: str
    citations: tuple[str, ...] = ()


@dataclass(frozen=True)
class GateOutcome:
    """The terminal verdict for one run."""

    target: str
    verdict: str
    trials: tuple[TrialOutcome, ...] = ()
    kit_faults: tuple[str, ...] = ()
    reported: tuple[str, ...] = ()
    statement: str = field(default="", compare=False)

    @property
    def exit_code(self) -> int:
        return _EXIT_CODES[self.verdict]

    def ids_with(self, verdict: str) -> tuple[str, ...]:
        return tuple(item.criterion_id for item in self.trials if item.verdict == verdict)


def settle_trial(facts: TrialFacts) -> TrialOutcome:
    """Apply the precedence rule and the asymmetric evidence rule to one trial.

    A demonstrated failure wins outright, then a governed gate pass, then the grade. The one
    correction applied to the grade is the asymmetry: NOT MET without a citation becomes PENDING.
    Nothing here consults ``guardrail`` — that is the whole content of the rule that a guardrail
    is an ordinary criterion.
    """
    if facts.demonstrated_failure:
        return TrialOutcome(
            facts.criterion_id,
            NOT_MET,
            f"demonstrated failure: {facts.demonstrated_failure}",
            facts.citations,
        )
    if facts.governed_pass:
        return TrialOutcome(facts.criterion_id, MET, "governed gate passed", facts.citations)
    if facts.graded == NOT_MET and not facts.citations:
        return TrialOutcome(
            facts.criterion_id,
            PENDING,
            "graded NOT MET without citing an artifact that exhibits the failure",
            (),
        )
    return TrialOutcome(facts.criterion_id, facts.graded, "grader judgement", facts.citations)


def fold(facts: RunFacts) -> GateOutcome:
    """Fold one run's evidence into a terminal verdict.

    ERROR is decided before any trial is examined; when Drydock cannot judge, it reports no trial
    verdicts at all rather than mixing an unexecutable judgement with a product claim.
    """
    if facts.kit_faults:
        outcome = GateOutcome(
            target=facts.target,
            verdict=ERROR,
            kit_faults=facts.kit_faults,
            reported=facts.reported,
        )
        return _with_statement(outcome)
    trials = tuple(settle_trial(item) for item in facts.trials)
    verdicts = {item.verdict for item in trials}
    if NOT_MET in verdicts:
        verdict = FAILED
    elif PENDING in verdicts:
        verdict = PENDING_MANUAL_VERIFICATION
    else:
        verdict = PASSED
    return _with_statement(
        GateOutcome(
            target=facts.target,
            verdict=verdict,
            trials=trials,
            reported=facts.reported,
        )
    )


def _with_statement(outcome: GateOutcome) -> GateOutcome:
    lines = [f"{outcome.target}: {outcome.verdict}"]
    if outcome.verdict == ERROR:
        lines[0] += " — Drydock could not judge; this says nothing about the product"
        lines.extend(f"  {reason}" for reason in outcome.kit_faults)
    else:
        met = outcome.ids_with(MET)
        lines[0] += f" — {len(met)} of {len(outcome.trials)} project criteria met"
        for item in outcome.trials:
            if item.verdict == MET:
                continue
            lines.append(f"  {item.criterion_id}: {item.verdict} — {item.basis}")
    lines.extend(f"  reported: {note}" for note in outcome.reported)
    return GateOutcome(
        target=outcome.target,
        verdict=outcome.verdict,
        trials=outcome.trials,
        kit_faults=outcome.kit_faults,
        reported=outcome.reported,
        statement="\n".join(lines),
    )
