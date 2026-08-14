"""The release gate fold: a pure function from run evidence to a terminal verdict.

This is steps 3 through 5 of the ``score release`` pipeline — pin what is settled, accept the
grader's verdicts, fold them into one answer — with no filesystem access, no LLM, and no
knowledge of how the evidence was gathered. Keeping it pure is the point: the policy can then be
replayed over recorded runs, so a change to the gate is validated against the whole corpus of
past evidence rather than against one fresh run.

The rules it implements:

* **Three trial verdicts and three run verdicts.** A trial is ``MET``, ``NOT MET``, or ``MANUAL``;
  a run is ``PASSED``, ``FAILED``, or ``ERROR``. There is no waiting state. ``PENDING`` was doing
  two unrelated jobs — a criterion no machine can ever settle, and a project that is not built yet
  — and one word for both is how a finished, correct project came to be reported as though it had
  open questions. The first is ``MANUAL`` and terminal; the second is ``NOT MET``, because an
  unbuilt criterion gets an F.
* **The asymmetric evidence rule.** MET may be reached by inference; NOT MET requires the grader
  to have looked and to cite what it saw — including seeing nothing where something was required.
  A NOT MET that cites nothing is not a demonstration, and becomes ``MANUAL``: the grader's
  ability to observe was what was absent, not the capability.
* **Deterministic evidence is input, not override.** A demonstrated failure bound to a criterion
  pins NOT MET and cannot be argued away; a command Drydock ran green at grading time pins MET;
  otherwise the grader's verdict stands. ``Verification:`` selects no mechanism of its own.
* **A guardrail is not a special kind of criterion.** ``Type: guardrail`` is reporting metadata.
  It gets no inference ban, no separate vocabulary, and no absolute-prohibition logic — the
  asymmetry rule already prevents a prohibition from failing for want of positive proof.
* **Hygiene is not project acceptance.** Git state, staleness, and Manifest closure are reported
  and never reach the verdict.
* **ERROR is computed first.** If Drydock could not execute the judgement, it claims nothing about
  the product rather than reporting a product failure.

``MANUAL`` never blocks. A large MANUAL set is a defect in the criteria, not in the product: a
trial nobody made observable. It is attested and named, so the correction is visible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MET = "MET"
NOT_MET = "NOT MET"
#: No machine can settle this criterion, however finished the product is. A terminal answer that
#: names a human check, not a waiting state.
MANUAL = "MANUAL"
TRIAL_VERDICTS = (MET, NOT_MET, MANUAL)

PASSED = "PASSED"
FAILED = "FAILED"
ERROR = "ERROR"
TERMINAL_VERDICTS = (PASSED, FAILED, ERROR)

#: X-2 would exit 0 on FAILED and gate scripts with an explicit ``--require``, on the grounds that
#: a command reporting a failure did its job. That change belongs with the exit-semantics work and
#: is not adopted here: until it is, a failing release keeps its non-zero exit so every existing
#: caller — UAT above all — keeps reading the verdict it always did.
_EXIT_CODES = {PASSED: 0, FAILED: 1, ERROR: 1}


@dataclass(frozen=True)
class TrialFacts:
    """Everything the fold knows about one Sea Trial.

    ``graded`` is what the grader returned. ``demonstrated_failure`` and ``governed_pass`` are
    deterministic findings bound to this criterion — a command Drydock ran at grading time — and
    take precedence over the grade. ``citations`` are the artifacts the grader named; a NOT MET
    grade with none is not a demonstration.
    """

    criterion_id: str
    graded: str = MANUAL
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

    ``kit_faults`` are reasons Drydock could not judge at all. ``demonstrated_failures`` are
    product failures Drydock observed that bind to no single criterion — a governed acceptance
    gate that ran and came back red. ``reported`` carries hygiene observations, which are surfaced
    to the operator and contribute nothing.
    """

    target: str
    trials: tuple[TrialFacts, ...] = ()
    kit_faults: tuple[str, ...] = ()
    demonstrated_failures: tuple[str, ...] = ()
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
    demonstrated_failures: tuple[str, ...] = ()
    reported: tuple[str, ...] = ()
    statement: str = field(default="", compare=False)

    @property
    def exit_code(self) -> int:
        return _EXIT_CODES[self.verdict]

    def ids_with(self, verdict: str) -> tuple[str, ...]:
        return tuple(item.criterion_id for item in self.trials if item.verdict == verdict)


def settle_trial(facts: TrialFacts) -> TrialOutcome:
    """Apply the precedence rule and the asymmetric evidence rule to one trial.

    A demonstrated failure wins outright, then a green governed observation, then the grade. The
    one correction applied to the grade is the asymmetry: NOT MET without a citation becomes
    MANUAL, because a grader that did not look has reported on itself rather than on the product.
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
            MANUAL,
            "graded NOT MET without citing what was observed; the grader did not look",
            (),
        )
    return TrialOutcome(facts.criterion_id, facts.graded, "grader judgement", facts.citations)


def fold(facts: RunFacts) -> GateOutcome:
    """Fold one run's evidence into a terminal verdict.

    ERROR is decided before any trial is examined; when Drydock cannot judge, it reports no trial
    verdicts at all rather than mixing an unexecutable judgement with a product claim. After that
    the rule is one line: any NOT MET fails the run, and nothing else does.
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
    failing = NOT_MET in {item.verdict for item in trials} or bool(facts.demonstrated_failures)
    return _with_statement(
        GateOutcome(
            target=facts.target,
            verdict=FAILED if failing else PASSED,
            trials=trials,
            demonstrated_failures=facts.demonstrated_failures,
            reported=facts.reported,
        )
    )


def _with_statement(outcome: GateOutcome) -> GateOutcome:
    """Render the verdict as the listing a reader can act on.

    Every criterion is listed with what was observed, not only the ones that went wrong: the
    listing is the whole answer, and it is what makes ``score release`` useful mid-build as well
    as at the end. "Nothing is built yet" needs no state of its own — it reads as criteria that
    are NOT MET, each naming what is missing.
    """
    lines = [f"{outcome.target}: {outcome.verdict}"]
    if outcome.verdict == ERROR:
        lines[0] += " — Drydock could not judge; this says nothing about the product"
        lines.extend(f"  {reason}" for reason in outcome.kit_faults)
    else:
        met = outcome.ids_with(MET)
        lines[0] += f" — {len(met)} of {len(outcome.trials)}"
        lines.append("")
        width = max((len(item.criterion_id) for item in outcome.trials), default=0)
        for item in outcome.trials:
            detail = "; ".join(item.citations) or item.basis
            lines.append(f"  {item.criterion_id:<{width}}  {item.verdict:<8}  {detail}")
        lines.extend(f"  demonstrated failure: {item}" for item in outcome.demonstrated_failures)
    lines.extend(f"  reported: {note}" for note in outcome.reported)
    return GateOutcome(
        target=outcome.target,
        verdict=outcome.verdict,
        trials=outcome.trials,
        kit_faults=outcome.kit_faults,
        demonstrated_failures=outcome.demonstrated_failures,
        reported=outcome.reported,
        statement="\n".join(lines),
    )
