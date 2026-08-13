"""Extraction of gate-policy evidence facts from recorded UAT runs.

The 18 recorded runs under ``uat/<Fixture>/runs/`` were produced by materially different
software, so their *verdicts* are not comparable across versions and a run cannot be replayed
through the lifecycle. What survives version drift is the evidence, and the release gate is a pure
function over it — so the corpus supports policy replay, not lifecycle replay: extract the recorded
evidence facts, run the current fold over them, and assert the verdict each run should produce.

``uat/*/runs/`` is not committed, so extraction is a one-time step whose result is frozen into
``tests/fixtures/uat_corpus.json``. That keeps the regression suite portable, deterministic, and
free of token cost. Run this module as a script to regenerate the fixture from a live corpus.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from drydock.gate_policy import MET, NOT_MET, PENDING, RunFacts, TrialFacts

REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_CORPUS_ROOT = REPO_ROOT / "uat"
CORPUS_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "uat_corpus.json"

# The recorded grader vocabulary, which V-3 retires in favour of one three-word vocabulary shared
# by the grader and the guardrail reporter.
_RECORDED_VERDICTS = {"PASS": MET, "FAIL": NOT_MET, "INCONCLUSIVE": PENDING}

# An evidence line that names a check which exhibited the failure. This is the demonstration the
# asymmetric evidence rule requires before a criterion may be graded NOT MET.
_FAILING_CITATION = re.compile(r"=FAIL\b")

# Blockers that mean Drydock could not execute the judgement at all.
_KIT_FAULT_MARKERS = (
    "Staged build asset was modified",
    "Governed acceptance gate could not run",
    "Unknown Sea Trial references",
)

# Blockers that are hygiene or plan state. Under V-6 these leave the release path and are
# reported: each run is independent evidence, and git state is not project acceptance.
_REPORTED_MARKERS = (
    "Build directory has uncommitted changes",
    "Build directory has no usable Git code identity",
    "Applied Blueprint specifications are stale",
    "Manifest work is not closed/verified",
    "Sea Trials has unresolved QUESTIONS",
)

# Blockers already retired before this work: the averaged 0..100 rubric, and the old fold's own
# restatement of its per-criterion verdicts. Neither is evidence, so neither is extracted.
_RETIRED_MARKERS = (
    "Technical score",
    "Technical dimensions below",
    "Required Sea Trial",
    "Guardrail",
)

KIT_FAULT = "kit_fault"
REPORTED = "reported"
RETIRED = "retired"


def classify_blocker(text: str) -> str:
    """Sort a recorded blocker into the fault domain the verdict model assigns it."""
    for marker in _KIT_FAULT_MARKERS:
        if marker in text:
            return KIT_FAULT
    for marker in _REPORTED_MARKERS:
        if marker in text:
            return REPORTED
    for marker in _RETIRED_MARKERS:
        if text.startswith(marker):
            return RETIRED
    return REPORTED


def extract_run_facts(record: dict, *, target: str) -> RunFacts:
    """Map one recorded ``score-release.json`` payload onto gate-policy facts.

    Only the grader's per-criterion verdicts and the artifacts it cited are carried across. The
    old fold's blocker list is not evidence about the product and is re-sorted rather than trusted.
    """
    guardrail_ids = {str(item) for item in record.get("guardrail_ids", ()) if isinstance(item, str)}
    trials: list[TrialFacts] = []
    for item in record.get("criteria", []):
        recorded = str(item.get("verdict", "INCONCLUSIVE")).upper()
        if recorded not in _RECORDED_VERDICTS:
            raise ValueError(f"unrecognized recorded verdict {recorded!r}")
        evidence = tuple(str(value) for value in item.get("evidence", ()))
        criterion_id = str(item["criterion_id"])
        trials.append(
            TrialFacts(
                criterion_id=criterion_id,
                graded=_RECORDED_VERDICTS[recorded],
                citations=tuple(value for value in evidence if _FAILING_CITATION.search(value)),
                guardrail=criterion_id in guardrail_ids,
            )
        )
    kit_faults: list[str] = []
    reported: list[str] = []
    for blocker in record.get("blockers", []):
        text = str(blocker)
        kind = classify_blocker(text)
        if kind == KIT_FAULT:
            kit_faults.append(text)
        elif kind == REPORTED:
            reported.append(text)
    gate = record.get("governed_gate")
    if isinstance(gate, dict) and gate.get("passed") and not gate.get("blocks"):
        trials = [TrialFacts(**{**vars(trial), "governed_pass": True}) for trial in trials]
    return RunFacts(
        target=target,
        trials=tuple(trials),
        kit_faults=tuple(kit_faults),
        reported=tuple(reported),
    )


def facts_to_dict(facts: RunFacts) -> dict:
    return {
        "target": facts.target,
        "trials": [vars(trial) | {"citations": list(trial.citations)} for trial in facts.trials],
        "kit_faults": list(facts.kit_faults),
        "reported": list(facts.reported),
    }


def facts_from_dict(payload: dict) -> RunFacts:
    return RunFacts(
        target=payload["target"],
        trials=tuple(
            TrialFacts(**{**item, "citations": tuple(item.get("citations", ()))})
            for item in payload.get("trials", [])
        ),
        kit_faults=tuple(payload.get("kit_faults", ())),
        reported=tuple(payload.get("reported", ())),
    )


def load_corpus(path: Path = CORPUS_FIXTURE) -> list[dict]:
    """Load the frozen corpus, decoding each entry's facts."""
    entries = json.loads(path.read_text(encoding="utf-8"))["runs"]
    for entry in entries:
        if entry.get("facts") is not None:
            entry["facts"] = facts_from_dict(entry["facts"])
    return entries


def iter_live_runs(root: Path = LIVE_CORPUS_ROOT):
    """Yield ``(fixture, run_id, score_record_or_None)`` for every recorded run under ``uat/``.

    A run with no ``score-release.json`` never reached the release gate, so it offers the fold no
    facts at all. That is a real and common corpus outcome, not a missing file.
    """
    for run_dir in sorted(root.glob("*/runs/*"), key=lambda p: (p.parents[1].name, p.name)):
        if not (run_dir / "result.json").is_file():
            continue
        fixture = run_dir.parents[1].name
        records = sorted(run_dir.glob("workspace/targets/*/evidence/score-release.json"))
        if not records:
            yield fixture, run_dir.name, None
            continue
        yield fixture, run_dir.name, json.loads(records[0].read_text(encoding="utf-8"))


def _regenerate() -> None:
    existing = {(item["fixture"], item["run_id"]): item for item in load_corpus()}
    runs = []
    for fixture, run_id, record in iter_live_runs():
        previous = existing.get((fixture, run_id), {})
        if record is None:
            runs.append({
                "fixture": fixture,
                "run_id": run_id,
                "reached_gate": False,
                "facts": None,
                "expected_verdict": None,
                "note": previous.get("note", ""),
            })
            continue
        runs.append({
            "fixture": fixture,
            "run_id": run_id,
            "reached_gate": True,
            "facts": facts_to_dict(extract_run_facts(record, target=fixture)),
            "expected_verdict": previous.get("expected_verdict"),
            "note": previous.get("note", ""),
        })
    CORPUS_FIXTURE.write_text(
        json.dumps({"runs": runs}, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"wrote {len(runs)} runs to {CORPUS_FIXTURE}")


if __name__ == "__main__":
    _regenerate()
