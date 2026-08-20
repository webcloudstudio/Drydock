"""``drydock score <Target>`` — what every other score command last reported.

The score family is five separate commands writing five separate artifacts, and an operator
returning to a Target has no way to see which of them have run, which of them still stand, and
where their output went without opening each one. This command answers that in one screen.

Two independent records are joined, because they answer different questions:

* ``logs/history.jsonl`` — the last invocation of each score sub-verb and the exit code it
  reported. This is *what the command did*.
* ``PROJECT_STATUS.jsonl`` — the workflow states the Target currently stands in. This is
  *whether that result still holds*. A score is voided when a later command re-authors the
  plan or the build it was taken against, so a passing run can stop standing without ever
  being re-run. Another score running — or failing — never does that to it.

Reading is the whole contract: nothing here rescores, executes a proof, or calls a model.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

__all__ = ["ScoreRun", "ScoreSummary", "render_summary", "summarize_scores"]

#: The score sub-verbs, in the order an operator runs them.
SCORE_VERBS = ("spec", "ac", "build", "release", "report")

#: The workflow state each score establishes, where it establishes one. ``score spec`` audits
#: imported sources and claims no ladder state, so it has no standing to report.
_VERB_STATE = {
    "ac": "SCORE AC",
    "build": "SCORE BUILD",
    "release": "SCORE RELEASE",
    "report": "FINALIZED",
}

#: State labels an operator cannot read at face value, and the plain words this command shows
#: instead. Display only: the recorded label in ``PROJECT_STATUS.jsonl`` is unchanged.
_STATE_DISPLAY = {"FINALIZED": "PROJECT COMPLETE"}

#: Scores an operator is not obliged to run, so their absence is not a missing step to report.
_OPTIONAL_VERBS = ("spec",)

#: The artifact each score writes, relative to the Target directory. ``score build`` is a
#: console report over evidence already on disk and writes nothing of its own.
_VERB_OUTPUT = {
    "spec": "SPECIFICATION_SCORECARD.md",
    "ac": "SOUNDINGS.md",
    "release": "SCORECARD.md",
    "report": "drydock_receipt/index.html",
}


@dataclass(frozen=True)
class ScoreRun:
    """What one score sub-verb last did, and whether that result still stands."""

    verb: str
    at: str  # local "YYYY-MM-DD HH:MM" of the last invocation; "" if never run
    result: str  # "pass", "fail", or "not run"
    standing: str  # "held", "voided", "failed", or "" when the verb claims no state
    attempts: int  # attempts at the state since it was last voided; 0 when none stands
    output: str  # Target-relative artifact path; "" when the command writes no file
    output_at: str  # local modification time of that artifact; "" when absent
    note: str  # one line of what the artifact currently says


@dataclass(frozen=True)
class ScoreSummary:
    """The Target's score standing: its workflow state and one row per score sub-verb."""

    target: str
    state: str  # current workflow state label; "" when none is recorded
    state_result: str  # "pass" or "fail"; "" when no state is recorded
    state_at: str
    state_attempts: int
    runs: tuple[ScoreRun, ...]


def summarize_scores(target: str, workspace: Path, target_dir: Path) -> ScoreSummary:
    """Join the command journal, the state machine, and the artifacts on disk. Writes nothing."""
    from drydock.project_status import latest_per_label, read_status, standing_state

    entries = read_status(target_dir)
    standing = latest_per_label(entries)
    current = standing_state(entries)
    last_runs = _last_score_runs(workspace, target)

    runs = tuple(
        _row(verb, last_runs.get(verb), standing.get(_VERB_STATE.get(verb, "")), target_dir)
        for verb in SCORE_VERBS
    )
    return ScoreSummary(
        target=target,
        state=current.label if current else "",
        state_result=("pass" if current.passed else "fail") if current else "",
        state_at=_local(current.at) if current else "",
        state_attempts=current.attempts if current else 0,
        runs=runs,
    )


def _row(verb: str, record: Mapping[str, object] | None, entry, target_dir: Path) -> ScoreRun:
    """Build one score's row from its journal record, its workflow state, and its artifact."""
    # The journal writes ``return_code``; the receipt's own record shape normalizes it to
    # ``returncode``. Accept either so this reads both without a conversion step.
    code = _exit_code(record)
    result = "not run" if record is None else ("pass" if code == 0 else "fail")

    # A verb that claims a ladder state reports three outcomes, not two: the state is held, it
    # was voided by later work, or the attempt that established it failed. A verb that claims
    # no state reports none of them — there is nothing for a later command to invalidate.
    if verb not in _VERB_STATE:
        standing = ""
    elif entry is None:
        standing = "voided" if record is not None else ""
    elif not entry.passed:
        standing = "failed"
    else:
        standing = "held"

    output = _VERB_OUTPUT.get(verb, "")
    path = target_dir / output if output else None
    exists = bool(path and path.exists())
    return ScoreRun(
        verb=verb,
        at=_journal_time(record),
        result=result,
        standing=standing,
        attempts=entry.attempts if entry is not None else 0,
        output=output,
        output_at=_file_time(path) if exists else "",
        note=_note(verb, target_dir, exists),
    )


def _exit_code(record: Mapping[str, object] | None) -> int | None:
    """The exit code a journal record reported, under either of the field's two names."""
    if record is None:
        return None
    for key in ("return_code", "returncode"):
        value = record.get(key)
        if isinstance(value, int):
            return value
    return None


def _note(verb: str, target_dir: Path, exists: bool) -> str:
    """One line of what this score's artifact currently says."""
    if verb == "build":
        return "console report; writes no file"
    if not exists:
        return "not written"
    if verb == "ac":
        return _acceptance_note(target_dir)
    return ""


def _acceptance_note(target_dir: Path) -> str:
    """Tally the recorded acceptance board without re-verifying anything on it."""
    from drydock.score_report import _acceptance

    board = _acceptance(target_dir)
    if not board.get("recorded"):
        return "no criteria recorded"
    parts = [
        f"{board[key]} {name}"
        for key, name in (
            ("passed", "passed"),
            ("prepassed", "prepassed"),
            ("failed", "failed"),
            ("unverified", "unverified"),
        )
        if board.get(key)
    ]
    return f"{board['total']} criteria: " + ", ".join(parts)


def _last_score_runs(workspace: Path, target: str) -> dict[str, Mapping[str, object]]:
    """The most recent journal record for each score sub-verb, oldest record losing.

    Records are matched on the Target named in the invocation, not on the journal's ``target``
    field: that field held the sub-verb for score commands journaled before the field was
    corrected, so filtering on it would silently drop a Target's whole score history.
    """
    from drydock.config import read_command_history
    from drydock.score_report import _stamp_key

    records = sorted(read_command_history(workspace, limit=1_000_000), key=_stamp_key)
    latest: dict[str, Mapping[str, object]] = {}
    for record in records:
        tokens = _tokens(record)
        if not tokens or target not in tokens[1:]:
            continue
        if tokens[0] == "init":
            latest.clear()  # a re-initialised Target starts a new run; earlier scores are not it
            continue
        if tokens[0] != "score":
            continue
        verb = next((token for token in tokens[1:] if token in SCORE_VERBS), "")
        if verb:
            latest[verb] = record
    return latest


def _tokens(record: Mapping[str, object]) -> Sequence[str]:
    """The drydock operands a journal record invoked, without the ``drydock`` shim."""
    argv = record.get("argv")
    if isinstance(argv, list) and argv:
        tokens = [str(item) for item in argv]
        return tokens[1:] if tokens[0] == "drydock" else tokens
    return str(record.get("command") or "").split()[1:]


def _journal_time(record: Mapping[str, object] | None) -> str:
    """The local minute a journal record ran, preferring its millisecond stamp."""
    if record is None:
        return ""
    stamp = str(record.get("stamp") or "")
    if stamp:
        try:
            moment = datetime.strptime(stamp, "%Y%m%d.%H%M%S.%fZ").replace(tzinfo=UTC)
        except ValueError:
            pass
        else:
            return moment.astimezone().strftime("%Y-%m-%d %H:%M")
    return str(record.get("time") or "")


def _file_time(path: Path) -> str:
    """The local minute an artifact was last written."""
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError:
        return ""


def _local(at: str) -> str:
    """Render a recorded ISO instant in the operator's own clock."""
    try:
        return datetime.fromisoformat(at).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return at


def render_summary(summary: ScoreSummary) -> list[str]:
    """Render the summary as console lines."""
    lines = [f"Target: {summary.target}"]
    if summary.state:
        attempts = f" · attempt {summary.state_attempts}" if summary.state_attempts > 1 else ""
        lines.append(f"State:  {_STATE_DISPLAY.get(summary.state, summary.state)}")
        lines.append(f"{'':<8}{summary.state_result.upper()} · {summary.state_at}{attempts}")
    else:
        lines.append("State:  none recorded")
    lines.append("")
    lines.append(f"{'Score':<9}{'Last run':<18}{'Result':<9}{'Standing':<10}Output")
    for run in summary.runs:
        output = run.output or "—"
        lines.append(
            f"{run.verb:<9}{run.at or '—':<18}{run.result:<9}{run.standing or '—':<10}{output}"
        )
        detail = " · ".join(part for part in (run.output_at, run.note) if part)
        if detail:
            lines.append(f"{'':<46}{detail}")
    lines.append("")
    missing = [
        run.verb
        for run in summary.runs
        if run.result == "not run" and run.verb not in _OPTIONAL_VERBS
    ]
    if missing:
        lines.append("Not yet run: " + ", ".join(f"drydock score {verb}" for verb in missing))
    return lines
