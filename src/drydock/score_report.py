"""``drydock score report`` — the build receipt for a real Target.

``drydock uat --report`` publishes a self-contained page proving what a UAT run did. A real
Target deserves the same document, and needs no new bookkeeping to get one: Drydock already
journals every command it runs and every model call those commands make.

* ``logs/history.jsonl`` — one record per CLI invocation, with its exit code, and (since the
  journal was widened for this command) the millisecond stamp its transcript is named from.
* ``logs/llm.jsonl`` — one record per model execution, with its prompt, output, transcript,
  token accounting, and elapsed time.
* ``logs/<stamp>_<target>_<command>_<llm>.*`` — the streams and artifacts those two index.

:func:`collect_run` joins them into the same record shape ``uat_report`` renders; the two
differ only in what a verdict means. A UAT run passes when the harness worked, so a product
failure Drydock reported correctly is a UAT pass. This report inverts that: it stamps PASSED
only when the product met its acceptance criteria.

Reading is the whole contract. Nothing here executes a proof, calls a model, or rescores
anything: it reports what the run recorded. A stale board is reported as stale, never
refreshed silently, because a receipt that re-measures is describing a different moment than
the run it claims to document.
"""

from __future__ import annotations

import html
import json
import re
import shutil
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from drydock.markdown_render import render_markdown
from drydock.report_render import (
    ArtifactGroup,
    Check,
    FileRecord,
    _anchor,
    _cell,
    _command_by_suffix,
    _command_text,
    _exit_state,
    _hash_file,
    _iter_files,
    _letterhead,
    _llm_calls,
    _local_time,
    _make_portable,
    _meta,
    _page,
    _render_receipt,
    _status_cell,
    _stream_link,
    _table,
    _tabs,
    _tail,
    _tokens,
    _tree,
    _verdict,
    _viewers,
    _write_sums,
    _write_viewers,
    local_run_window,
    prune_generated,
    recorded_status_headline,
    run_notes,
)

__all__ = ["REPORT_DIRNAME", "collect_run", "write_report"]

#: The receipt is published in the Target's own workspace, not inside the delivered
#: application: the document describes the delivery, it is not part of it. It is a web page
#: an operator hosts and keeps in version control, so it carries the account of the run and
#: what that account cites — not the delivered code, and not the machine-to-machine streams a
#: person cannot read.
REPORT_DIRNAME = "drydock_receipt"

_INDEX_NAME = "index.html"
_RECORD_NAME = "result.json"
_HISTORY_NAME = "history.jsonl"
_RECORDS_NAME = "llm.jsonl"
_LOGS_DIR = "logs"
_WORKSPACE_DIR = "workspace"
_SOUNDINGS_NAME = "SOUNDINGS.md"

#: ``20260815.085220.134Z_jq_build_codex.log`` — stamp, then the components ``log_basename``
#: joined. The stamp is fixed-width, so lexical order is chronological order.
_LOG_NAME_RE = re.compile(r"^(?P<stamp>\d{8}\.\d{6}\.\d{3}Z)_(?P<rest>.+)$")

#: A run begins where the Target does. Everything the Target has recorded since its most recent
#: ``drydock init`` is one run; a Target initialised once therefore reports its whole life,
#: which is what an operator means by "the latest run" for a project they have built repeatedly.
_RUN_START_VERB = "init"

#: Evidence a person reads: the command transcript and the output that came back. What is left
#: out is what a run writes most of. The provider's wire transcript (``*.raw.jsonl``) is
#: machine IO. The assembled prompt (``*.prompt.md``) is readable but not this audit's subject:
#: it injects the specification and Blueprint on every call, so a build repeats substantially
#: the same payload once per block and is by itself larger than everything else combined. Both
#: stay in the Target's own ``logs/``, where the operator can still reach them.
_LOG_SUFFIXES = (".log", ".output.txt")

#: The Target subtrees the receipt carries. Top-level artifacts — Manifest, Metadata, board,
#: status — come with them.
#:
#: The Blueprint is among them. Every Manifest block names the specification it implements and
#: the sources it was given context from; a receipt that shows the plan without carrying what
#: the plan cites is a document whose central claim cannot be checked. The Blueprint is a
#: versioned input, but in a receipt it is evidence, so it travels with the run it governed.
_WORKSPACE_SUBDIRS = ("blueprint", "evidence", "QuarterDeck")

#: Never copied into a receipt: caches a reader cannot use and a seal should not cover.
_SKIP_NAMES = frozenset({"__pycache__", "node_modules", ".venv"})


#: A claim the run never settled is reported as not run, never as a verdict over the product:
#: nothing was measured, so there is nothing to be unproven about.
_RECEIPT_TAGS = {"pass": "PASS", "fail": "FAIL", "unknown": "NOT RUN"}


class ReportError(Exception):
    """The Target has recorded nothing this command could report."""


# ── the recorded run ─────────────────────────────────────────────────────────────────


def _verb(record: Mapping[str, object]) -> str:
    """The Drydock verb a history record invoked, e.g. ``build`` for ``drydock build jq``."""
    argv = record.get("argv")
    tokens = (
        [str(item) for item in argv]
        if isinstance(argv, list) and argv
        else str(record.get("command") or "").split()[1:]
    )
    return tokens[0] if tokens else ""


def _stamp_key(record: Mapping[str, object]) -> str:
    """A sortable stamp for a history record, whatever vintage it is.

    Records written before the journal carried ``stamp`` keep only a minute-resolution ``time``.
    Widening that to the stamp format puts them in the right order relative to stamped records
    and to the log files on disk; it cannot recover the second they actually ran.
    """
    stamp = str(record.get("stamp") or "")
    if stamp:
        return stamp
    try:
        moment = datetime.strptime(str(record.get("time") or ""), "%Y-%m-%d %H:%M")
    except ValueError:
        return ""
    return f"{moment:%Y%m%d.%H%M}00.000Z"


def _iso(stamp: str) -> str:
    """Render a log stamp as the ISO instant the report's clock formatting expects."""
    try:
        moment = datetime.strptime(stamp, "%Y%m%d.%H%M%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        return ""
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def _target_history(workspace: Path, target: str) -> list[Mapping[str, object]]:
    """Every recorded command for one Target, oldest first."""
    from drydock.config import read_command_history

    records = read_command_history(workspace, target=target, limit=1_000_000)
    return sorted(records, key=_stamp_key)


def _run_window(records: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    """Narrow a Target's history to its latest run: everything since the last ``init``.

    A Target whose history predates any recorded ``init`` reports all of it rather than
    nothing — the alternative is a receipt that silently omits the work it is meant to prove.
    """
    starts = [index for index, record in enumerate(records) if _verb(record) == _RUN_START_VERB]
    return list(records[starts[-1] :] if starts else records)


def _sibling_prefixes(targets_root: Path, target: str) -> tuple[str, ...]:
    """Log-name prefixes belonging to other Targets whose names extend this one.

    ``commonmark`` and ``commonmark_2`` are different Targets that share a filename prefix, so
    matching on ``_commonmark_`` alone would pull a neighbour's transcripts into this receipt.
    """
    from drydock.execution import log_component

    component = log_component(target)
    if not targets_root.is_dir():
        return ()
    return tuple(
        f"{other}_"
        for other in sorted(log_component(path.name) for path in targets_root.iterdir())
        if other != component and other.startswith(f"{component}_")
    )


def _run_logs(
    logs_dir: Path, target: str, start_key: str, siblings: Sequence[str] = ()
) -> list[Path]:
    """Every log file this Target wrote at or after the window opened, oldest first."""
    from drydock.execution import log_component

    component = log_component(target)
    if not logs_dir.is_dir() or not component:
        return []
    chosen: list[Path] = []
    for path in sorted(logs_dir.iterdir()):
        if not path.is_file():
            continue
        match = _LOG_NAME_RE.match(path.name)
        if match is None or match.group("stamp") < start_key:
            continue
        rest = match.group("rest")
        if not rest.startswith(f"{component}_"):
            continue
        remainder = rest[len(component) + 1 :]
        if any(remainder.startswith(sibling[len(component) + 1 :]) for sibling in siblings):
            continue  # a longer Target name that merely starts with this one
        chosen.append(path)
    return chosen


def _llm_records(records_path: Path, target: str, start_key: str) -> list[Mapping[str, object]]:
    """Recorded model executions for one Target inside the window, oldest first."""
    from drydock.llm_usage import read_records, record_target

    records, _invalid = read_records(records_path)
    chosen = [
        record
        for record in records
        if record_target(record) == target
        and str(record.get("execution_id") or "").split("-")[0] >= start_key
    ]
    return sorted(chosen, key=lambda record: str(record.get("execution_id") or ""))


def _usage_totals(records: Sequence[Mapping[str, object]]) -> dict[str, int]:
    """Aggregate token and time accounting the way the provider bills it."""
    from drydock.llm_usage import normalize_tokens

    totals = {
        "calls": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "fresh_input_tokens": 0,
        "output_tokens": 0,
        "llm_elapsed_ms": 0,
    }
    for record in records:
        job = record.get("job") if isinstance(record.get("job"), dict) else {}
        result = record.get("result") if isinstance(record.get("result"), dict) else {}
        stats = result.get("stats") if isinstance(result.get("stats"), dict) else {}
        total, cached, output = normalize_tokens(str(job.get("llm") or ""), stats)
        totals["calls"] += 1
        totals["input_tokens"] += total
        totals["cached_input_tokens"] += cached
        totals["fresh_input_tokens"] += max(total - cached, 0)
        totals["output_tokens"] += output
        try:
            totals["llm_elapsed_ms"] += int(stats.get("elapsed_ms") or 0)
        except (TypeError, ValueError):
            pass
    return totals


def _acceptance(target_dir: Path) -> dict[str, object]:
    """Read the recorded acceptance board. Verifies nothing; reports what ``score ac`` left.

    An absent board is reported as absent. Re-running the proofs here would measure the product
    as it is now rather than as the run left it, and would make a report command execute the
    Target's test suite.
    """
    from drydock.standard_artifacts import (
        VERIFIED_FAIL,
        VERIFIED_PASS,
        VERIFIED_PREPASSED,
        VERIFIED_UNVERIFIED,
        load_soundings,
    )

    board = load_soundings(target_dir / _SOUNDINGS_NAME)
    states = {
        VERIFIED_PASS: "passed",
        VERIFIED_FAIL: "failed",
        VERIFIED_UNVERIFIED: "unverified",
        VERIFIED_PREPASSED: "prepassed",
    }
    tally = {"passed": 0, "failed": 0, "unverified": 0, "prepassed": 0, "unrecognized": 0}
    verified_at = ""
    for sounding in board.values():
        tally[states.get(sounding.verified, "unrecognized")] += 1
        verified_at = max(verified_at, sounding.verified_at or "")
    return {
        "recorded": bool(board),
        "total": len(board),
        "verified_at": verified_at,
        "failures": tuple(
            sounding.criterion_id
            for sounding in board.values()
            if sounding.verified == VERIFIED_FAIL
        ),
        **tally,
    }


def _build_facts(target: str, target_dir: Path, records_path: Path) -> dict[str, object]:
    """Summarize what the recorded build evidence says about the blocks the Manifest holds."""
    from drydock.build_report import build_score_report

    try:
        report = build_score_report(target, target_dir, records_path=records_path)
    except (OSError, ValueError):
        return {"recorded": False, "blocks": 0, "failed": (), "repaired": (), "calls": 0}
    return {
        "recorded": bool(report.blocks),
        "blocks": len(report.blocks),
        "failed": tuple(block.block_id for block in report.failed_blocks),
        "repaired": tuple(block.block_id for block in report.repaired_blocks),
        "calls": report.calls,
    }


#: Sub-verbs of ``drydock score``. Named rather than positional because the operand order has
#: changed over the life of the journal: ``drydock score jq release`` and
#: ``drydock score release jq`` are both on record and mean the same thing.
_SCORE_VERBS = frozenset({"spec", "ac", "build", "release", "report", "drydock"})


def _score_exit_codes(commands: Sequence[Mapping[str, object]]) -> dict[str, int]:
    """The exit code each score last reported, keyed by its sub-verb.

    ``drydock score <Target>`` names no sub-verb — it summarizes the others and scores nothing —
    so it contributes no exit code to any of them.
    """
    codes: dict[str, int] = {}
    for command in commands:
        argv = [str(part) for part in command.get("argv") or []][1:]  # drop the "drydock" shim
        if not argv or argv[0] != "score":
            continue
        code = command.get("returncode")
        if not isinstance(code, int):
            continue
        verb = next((token for token in argv[1:] if token in _SCORE_VERBS), "")
        if not verb:
            continue
        codes[verb] = code
    return codes


def _transcript_index(logs: Sequence[Path]) -> dict[tuple[str, str], str]:
    """Map ``(minute, command)`` to the transcript that command wrote.

    Records written before the journal carried its transcript path can still be joined to one:
    the filename holds the same minute and the same command name, which together identify it
    for every history this project has. Where they do not, the row simply has no link — a wrong
    transcript beside a command is worse than none.
    """
    index: dict[tuple[str, str], str] = {}
    seen: set[tuple[str, str]] = set()
    for path in logs:
        if path.suffix != ".log" or path.name.endswith(".llm.log"):
            continue
        match = _LOG_NAME_RE.match(path.name)
        if match is None:
            continue
        parts = match.group("rest").removesuffix(".log").split("_")
        if len(parts) < 2:
            continue
        key = (match.group("stamp")[:13], parts[1])
        if key in seen:
            index.pop(key, None)  # ambiguous within the minute: link neither
            continue
        seen.add(key)
        index[key] = path.name
    return index


def _command_llm_logs(
    commands: Sequence[Mapping[str, object]], calls: Sequence[Mapping[str, object]]
) -> tuple[tuple[str, ...], ...]:
    """Attach each recorded LLM activity log to the command that produced it.

    Drydock runs one command at a time, so a call belongs to the last command that started at
    or before it. A call that predates every command — a record carried over from an earlier
    window — is attached to nothing rather than to the wrong row.
    """
    starts = [str(command.get("stamp") or "") for command in commands]
    logs: list[list[str]] = [[] for _ in commands]
    for call in calls:
        path = str(call.get("llm_log") or "")
        if not path:
            continue
        stamp = str(call.get("execution_id") or "").split("-")[0]
        owner = max(
            (index for index, start in enumerate(starts) if start and start <= stamp),
            default=None,
        )
        if owner is not None:
            logs[owner].append(path)
    return tuple(tuple(paths) for paths in logs)


def _workflow(target_dir: Path) -> list[dict[str, object]]:
    """The workflow ladder: the states ``PROJECT_STATUS.jsonl`` holds, in ladder order.

    One receipt row per state row, and nothing else. The state machine is the only source:
    it already drops the states a re-authored plan or build invalidated, so there is nothing
    to reduce and no second opinion to reconcile. A state it does not hold was either never
    attempted or was voided; either way the receipt has no claim to make about it.
    """
    from drydock.project_status import read_status

    return [_row_of(entry) for entry in read_status(target_dir)]


def _standing_row(target_dir: Path) -> dict[str, object]:
    """The standing state as a receipt row: the blocking rung, else the last good one."""
    from drydock.project_status import read_status, standing_state

    entry = standing_state(read_status(target_dir))
    return _row_of(entry) if entry is not None else {}


def _row_of(entry) -> dict[str, object]:
    """One :class:`~drydock.project_status.StatusEntry` as the receipt's row shape."""
    return {
        "label": entry.label,
        "passed": entry.passed,
        "at": entry.at,
        "detail": entry.detail,
        "command": entry.command,
        "attempts": entry.attempts,
    }


def _workflow_state(result: Mapping[str, object]) -> str:
    """Grade the run from the state the machine holds: ``fail``, ``pass``, or ``warn``.

    ``state`` is the standing state, which is the blocking rung whenever one exists, so a
    failure anywhere on the ladder reaches this as a failure.
    """
    state = result.get("state")
    if not isinstance(state, Mapping) or not state.get("label"):
        return "warn"
    if not state.get("passed"):
        return "fail"
    return "pass" if state.get("label") == "FINALIZED" else "warn"


def _reconcile_acceptance(target: str, target_dir: Path, acceptance: Mapping[str, object]) -> None:
    """Fail SCORE AC in the machine when the evidence contradicts it.

    ``drydock score ac`` owns that state and normally records its own failure. This catches
    the case where the board on disk reports failures the recorded state does not, and it
    corrects the machine rather than the rendered page, so the file and the receipt cannot
    disagree. The failure invalidates acceptance only: no evidence changed, so the scores
    taken on top of it keep whatever standing they had. What it does move is the last good
    state, which now stops below acceptance.
    """
    from drydock.project_status import latest_per_label, read_status, record_status

    if not acceptance.get("failed"):
        return
    standing = latest_per_label(read_status(target_dir))
    entry = standing.get("SCORE AC")
    if entry is None or not entry.passed:
        return
    failures = acceptance.get("failures") or ()
    record_status(
        target_dir,
        "SCORE AC",
        passed=False,
        detail=f"{len(failures)} criteria failed",
        command=f"drydock score report {target}",
    )


def _earn_finalized(target: str, target_dir: Path) -> None:
    """Record FINALIZED when publishing this receipt is what earns it.

    Publishing is the finalizing act, so the state is written before the document renders and
    the document then reads it like any other. It is earned only by a ladder that failed
    nothing and was scored: a receipt published over an unscored build leaves the project
    unfinished, which is what the amber stamp reports.
    """
    from drydock.project_status import read_status, record_status

    entries = read_status(target_dir)
    if not entries or any(not entry.passed for entry in entries):
        return
    if not any(entry.label == "SCORE BUILD" for entry in entries):
        return
    record_status(
        target_dir,
        "FINALIZED",
        passed=True,
        detail="",
        command=f"drydock score report {target}",
    )


def collect_run(target: str, workspace: Path, target_dir: Path) -> dict:
    """Assemble the Target's latest run as the record a receipt renders.

    Reads the three journals and the Target's own artifacts; writes nothing. Raises
    :class:`ReportError` when the Target has no recorded command to report.
    """
    logs_dir = workspace / _LOGS_DIR
    history = _run_window(_target_history(workspace, target))
    if not history:
        raise ReportError(
            f"No recorded commands for Target '{target}' in {logs_dir / _HISTORY_NAME}."
        )

    start_key = _stamp_key(history[0])
    siblings = _sibling_prefixes(target_dir.parent, target)
    logs = _run_logs(logs_dir, target, start_key, siblings)
    log_names = {path.name for path in logs}
    transcripts = _transcript_index(logs)

    commands: list[dict[str, object]] = []
    for index, record in enumerate(history, start=1):
        verb = _verb(record)
        argv = record.get("argv")
        tokens = (
            [str(item) for item in argv]
            if isinstance(argv, list) and argv
            else str(record.get("command") or "").split()[1:]
        )
        transcript = str(record.get("transcript") or "")
        name = Path(transcript).name if transcript else ""
        if not name:
            name = transcripts.get((_stamp_key(record)[:13], verb), "")
        commands.append({
            "label": f"{index:02d}-{verb or 'command'}",
            "argv": ["drydock", *tokens],
            "returncode": record.get("return_code"),
            "elapsed_ms": record.get("elapsed_ms") or 0,
            "stdout_path": f"{_LOGS_DIR}/{name}" if name in log_names else "",
            "stderr_path": "",
            "time": record.get("time") or "",
            # The sortable stamp is carried into the record so the receipt can attach each
            # model call's activity log to the command that made it.
            "stamp": _stamp_key(record),
        })

    llm_records = _llm_records(logs_dir / _RECORDS_NAME, target, start_key)
    last_job = next(
        (record["job"] for record in reversed(llm_records) if isinstance(record.get("job"), dict)),
        {},
    )
    finish_key = max(
        (_stamp_key(record) for record in history),
        default=start_key,
    )
    acceptance = _acceptance(target_dir)
    build = _build_facts(target, target_dir, logs_dir / _RECORDS_NAME)

    # The verdict is the state the machine holds, not an inference from one artifact. An
    # acceptance failure is a failed state on the ladder like any other, so it lands in the
    # same place; a board that was never recorded withholds nothing, because the states that
    # did run still say exactly how far the project got.
    workflow = _workflow(target_dir)
    state = _standing_row(target_dir)
    status = {"pass": "passed", "fail": "failed", "warn": "incomplete"}[
        _workflow_state({"state": state, "workflow": workflow})
    ]

    from drydock import __version__

    return {
        "target": target,
        "run_id": start_key,
        "status": status,
        "state": state,
        "workflow": workflow,
        "commands": commands,
        "score_exit_codes": _score_exit_codes(commands),
        "acceptance": dict(acceptance),
        "build": build,
        "usage": _usage_totals(llm_records),
        "environment": {
            "drydock_version": __version__,
            "provider": str(last_job.get("llm") or ""),
            "model": str(last_job.get("model") or ""),
            "started_at": _iso(start_key),
            "finished_at": _iso(finish_key),
        },
        "elapsed_ms": sum(int(command.get("elapsed_ms") or 0) for command in commands),
    }


# ── receipt claims ───────────────────────────────────────────────────────────────────


def _receipt_checks(report_root: Path, result: Mapping[str, object]) -> tuple[Check, ...]:
    """Derive the five claims a delivered build either earned or did not, in fixed order."""
    commands = [item for item in result.get("commands") or [] if isinstance(item, dict)]
    acceptance = result.get("acceptance") if isinstance(result.get("acceptance"), dict) else {}
    build = result.get("build") if isinstance(result.get("build"), dict) else {}
    scores = (
        result.get("score_exit_codes") if isinstance(result.get("score_exit_codes"), dict) else {}
    )
    board = f"{_WORKSPACE_DIR}/{_SOUNDINGS_NAME}"

    checks: list[Check] = []

    if not acceptance.get("recorded"):
        checks.append(
            Check(
                "Acceptance criteria verified",
                "unknown",
                "No acceptance board is recorded for this Target; run drydock score ac.",
            )
        )
    else:
        failed = int(acceptance.get("failed") or 0)
        unverified = int(acceptance.get("unverified") or 0)
        detail = (
            f"{acceptance.get('passed', 0)} of {acceptance.get('total', 0)} criteria passed"
            f"{f'; {failed} failed' if failed else ''}"
            f"{f'; {unverified} carry no executable proof' if unverified else ''}"
            f", verified {acceptance.get('verified_at') or 'at an unrecorded time'}."
        )
        checks.append(
            Check("Acceptance criteria verified", "fail" if failed else "pass", detail, board)
        )

    if not build.get("recorded"):
        checks.append(
            Check("Build blocks verified", "unknown", "No build evidence is recorded for this run.")
        )
    else:
        failed_blocks = tuple(str(item) for item in build.get("failed") or ())
        repaired = tuple(build.get("repaired") or ())
        unverified = (
            "; unverified: " + ", ".join(failed_blocks) if failed_blocks else "; all verified"
        )
        detail = (
            f"{build.get('blocks', 0)} blocks recorded"
            f"{f'; {len(repaired)} needed repair' if repaired else ''}"
            f"{unverified}."
        )
        checks.append(
            Check(
                "Build blocks verified",
                "fail" if failed_blocks else "pass",
                detail,
                f"{_WORKSPACE_DIR}/evidence",
            )
        )

    for name, key in (
        ("Acceptance score passed", "ac"),
        ("Release score passed", "release"),
    ):
        command = _command_by_suffix(commands, "-score")
        code = scores.get(key)
        if code is None:
            checks.append(Check(name, "unknown", f"No {key} score is recorded for this run."))
            continue
        evidence = str(command.get("stdout_path") or "") if command else ""
        checks.append(
            Check(name, _exit_state(code), f"drydock score {key} exited {code}.", evidence)
        )

    failures = _outstanding_failures(commands)
    checks.append(
        Check(
            "Every recorded command exited clean",
            "pass" if not failures else "fail",
            f"{len(commands)} commands recorded"
            + (
                "; every one either exited 0 or was rerun clean."
                if not failures
                else f"; {len(failures)} exited nonzero with no later clean rerun, the last at "
                f"{failures[-1].get('label')}."
            ),
            _RECORD_NAME,
        )
    )
    del report_root
    return tuple(checks)


def _is_status_query(command: Mapping[str, object]) -> bool:
    """True for ``drydock status`` and ``drydock <verb> status``.

    A status query's exit code reports the Target's state, not a fault in the command. Counting
    one as a failure would report the work Drydock has not finished yet as an error in the run.
    """
    key = _command_key(command).split()
    return "status" in key[1:3]


def _command_key(command: Mapping[str, object]) -> str:
    """The command's identity for supersession: its verb chain and Target, without options.

    Options are dropped so a rerun that changed provider, model, or attempt budget still counts
    as the same command being run again — the operator reran the same step.
    """
    key: list[str] = []
    for part in _command_text(command.get("argv") or []).split():
        if part.startswith("-"):
            break
        key.append(part)
    return " ".join(key)


def _outstanding_failures(
    commands: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    """The nonzero exits no later clean rerun of the same command cleared.

    A step Drydock ran, failed, and ran again to green is history, not a defect: the run's
    outcome is the last attempt's. Both rows stay in the Commands table with their own results;
    only a failure nothing later cleared is still an error. ``--help`` never clears anything —
    it exits 0 without doing the work.
    """
    cleared: set[str] = set()
    failures: list[Mapping[str, object]] = []
    for command in reversed(list(commands)):
        key = _command_key(command)
        argv = [str(part) for part in command.get("argv") or []]
        if command.get("returncode") == 0:
            if "--help" not in argv:
                cleared.add(key)
            continue
        if command.get("returncode") is None or _is_status_query(command):
            continue
        if key not in cleared:
            failures.append(command)
    failures.reverse()
    return failures


# ── publishing ───────────────────────────────────────────────────────────────────────


def _ignore_hidden(directory: str, names: list[str]) -> set[str]:
    """Never copy a dot entry. ``.git`` above all: the receipt excludes hidden files from its
    inventory, so a copied one is unhashed, unlisted weight a reader is never shown. Build
    caches go the same way, for the same reason."""
    del directory
    return {name for name in names if name.startswith(".") or name in _SKIP_NAMES}


def _copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        return
    shutil.copytree(source, destination, dirs_exist_ok=True, symlinks=False, ignore=_ignore_hidden)
    prune_generated(destination)


def _copy_workspace(target_dir: Path, destination: Path) -> None:
    """Copy the Target's own account of itself: its top-level artifacts and the subtrees the
    receipt reports over — its Blueprint, its evidence, and its QuarterDeck.

    The only thing deliberately left behind is the receipt's own previous edition. A receipt
    does not carry a copy of itself.
    """
    if not target_dir.is_dir():
        return
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(target_dir.iterdir()):
        if path.name.startswith("."):
            continue
        if path.is_file():
            shutil.copy2(path, destination / path.name)
        elif path.is_dir() and path.name in _WORKSPACE_SUBDIRS:
            _copy_tree(path, destination / path.name)
    prune_generated(destination)


def _write_journal_slice(source: Path, destination: Path, keep) -> None:
    """Copy the records of one journal that belong to this run, in recorded order.

    ``history.jsonl`` and ``llm.jsonl`` are the only JSON Lines the receipt carries, and only
    because the page is rendered from them — ``llm.jsonl`` drives the LLM table. Sliced to this
    run, they are small; the wire transcripts they index are not, and are left behind.
    """
    if not source.is_file():
        return
    lines = []
    for line in source.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if keep(record):
            lines.append(json.dumps(record))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _publish(
    target: str,
    workspace: Path,
    target_dir: Path,
    report_root: Path,
    result: Mapping[str, object],
) -> None:
    """Copy every artifact the receipt links into the report directory.

    What that is, and only that: the readable transcripts, the model output, the two
    journals the page is rendered from, and the Target's top-level artifacts
    with its evidence and QuarterDeck. A receipt that links a file it did not carry is a claim
    its reader cannot check — so what is not carried is not linked, and ``_stream_link`` drops
    the link for any artifact this pass left behind.

    The delivered application is not copied. The receipt documents the delivery; the code is
    committed in the build directory, which the receipt names and never modifies.
    """
    if report_root.exists():
        shutil.rmtree(report_root)
    report_root.mkdir(parents=True)

    logs_dir = workspace / _LOGS_DIR
    start_key = str(result.get("run_id") or "")
    siblings = _sibling_prefixes(target_dir.parent, target)
    destination = report_root / _LOGS_DIR
    destination.mkdir(parents=True, exist_ok=True)
    for path in _run_logs(logs_dir, target, start_key, siblings):
        if path.name.endswith(_LOG_SUFFIXES):
            shutil.copy2(path, destination / path.name)

    _write_journal_slice(
        logs_dir / _HISTORY_NAME,
        destination / _HISTORY_NAME,
        lambda record: record.get("target") == target and _stamp_key(record) >= start_key,
    )
    from drydock.llm_usage import record_target

    _write_journal_slice(
        logs_dir / _RECORDS_NAME,
        destination / _RECORDS_NAME,
        lambda record: (
            record_target(record) == target
            and str(record.get("execution_id") or "").split("-")[0] >= start_key
        ),
    )

    _copy_workspace(target_dir, report_root / _WORKSPACE_DIR)

    record_path = report_root / _RECORD_NAME
    record_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # The journals record absolute paths on the machine that ran the build. A published receipt
    # states every path relative to itself, so the page reads the same anywhere it is copied.
    for path in (record_path, destination / _RECORDS_NAME):
        _make_portable(path, workspace)


def _report_groups(report_root: Path, target: str) -> tuple[ArtifactGroup, ...]:
    """The two trees a receipt shows, plus its own machine-readable record.

    Every file is hashed. The receipt is a published artifact in its own directory now, so it
    is sealed the way a UAT kit is: a reader who was handed the directory can verify it.
    """
    del target
    groups = [
        ArtifactGroup(
            "Evidence",
            "Command transcripts, model output, and the command and execution journals for "
            "this run.",
            tuple(_iter_files(report_root / _LOGS_DIR, report_root, hidden=False)),
        ),
        ArtifactGroup(
            "Workspace",
            "The Target Drydock drove: Manifest, Metadata, acceptance board, QuarterDeck, "
            "and build evidence.",
            tuple(_iter_files(report_root / _WORKSPACE_DIR, report_root, hidden=False)),
        ),
        ArtifactGroup(
            "Run record",
            "Machine-readable outcome for this run.",
            tuple(
                _hash_file(path, report_root)
                for path in sorted(report_root.glob("*"))
                if path.is_file() and path.name == _RECORD_NAME
            ),
        ),
    ]
    return tuple(group for group in groups if group.files)


def _run_facts(result: Mapping[str, object], delivered: str) -> list[tuple[str, str]]:
    """The provenance a reader needs before reading anything else the run wrote.

    ``delivered`` is the build directory the application was written to. It is named, not
    carried: the code is under version control where it was built, and copying it into every
    receipt is what made this document unpublishable.
    """
    environment = result.get("environment") if isinstance(result.get("environment"), dict) else {}
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    build = result.get("build") if isinstance(result.get("build"), dict) else {}
    acceptance = result.get("acceptance") if isinstance(result.get("acceptance"), dict) else {}
    tokens = _tokens(dict(usage))
    _, _, tokens = tokens.partition(" · ")  # the call count is already its own field

    def recorded(key: str) -> str:
        return html.escape(str(environment.get(key) or "not recorded"))

    criteria = (
        f"{acceptance.get('passed', 0)} passed / {acceptance.get('failed', 0)} failed / "
        f"{acceptance.get('unverified', 0)} unverified"
        if acceptance.get("recorded")
        else "no board recorded"
    )
    # Ran, Provider, and Model are omitted: the ladder below carries a local timestamp per
    # state, and the letterhead already states the provider and model this run used.
    return [
        ("Verdict", html.escape(str(result.get("status") or "").upper())),
        ("Target", f"<code>{html.escape(str(result.get('target') or ''))}</code>"),
        ("Run", f"<code>{html.escape(str(result.get('run_id') or ''))}</code>"),
        ("Drydock", recorded("drydock_version")),
        ("Commands", html.escape(str(len(result.get("commands") or ())))),
        ("Elapsed", f"{int(result.get('elapsed_ms') or 0) / 1000:.1f}s"),
        ("LLM calls", html.escape(str(usage.get("calls", "not recorded")))),
        ("Tokens", html.escape(tokens)),
        ("Blocks", html.escape(f"{build.get('blocks', 0)} recorded")),
        ("Criteria", html.escape(criteria)),
        ("Code", f"<code>{html.escape(delivered)}</code>" if delivered else ""),
    ]


def _state_headline(result: Mapping[str, object]) -> str:
    """The project's state name, standing in for a pass/fail verdict word.

    The overview leads with the one state the project holds, not with a completion word:
    ``INCOMPLETE`` describes the ladder, not the state, and reads as a verdict this receipt
    does not make.
    """
    target = html.escape(str(result.get("target") or ""))
    state = result.get("state")
    label = state.get("label") if isinstance(state, Mapping) else None
    return f"{target}: {html.escape(str(label))}" if label else f"{target}: NO STATE"


def _detail_line(result: Mapping[str, object]) -> str:
    """Name the datestamp the state was recorded at, and stop there."""
    state = result.get("state")
    if not isinstance(state, Mapping) or not state.get("label"):
        return "No lifecycle state is recorded. The commands below are everything this receipt can show."
    when = _local_time(state.get("at")) or "time not recorded"
    if not state.get("passed"):
        detail = html.escape(str(state.get("detail") or ""))
        return f"{when}{f' — {detail}' if detail else ''}"
    return when


def _ladder_table(workflow: Sequence[Mapping[str, object]]) -> str:
    """Render every legitimate workflow state, in lifecycle order.

    ``PROJECT_STATUS.jsonl`` holds only states the Target established.  A receipt must also
    show the unestablished rungs, otherwise a table of passing held states can look complete
    even though the score and publication gates have never run.
    """
    from drydock.project_status import LABEL_LADDER

    held = {str(step.get("label") or ""): step for step in workflow if isinstance(step, Mapping)}
    rows = []
    for lifecycle_state in LABEL_LADDER:
        step = held.get(lifecycle_state)
        if step is None:
            rows.append([
                _cell(lifecycle_state),
                '<td><span class="tag raw">NOT ESTABLISHED</span></td>',
                _cell("—", css="nowrap"),
                _cell("—"),
                _cell("This lifecycle gate has not run.", css="detail"),
            ])
            continue
        attempts = int(step.get("attempts") or 1)
        detail = str(step.get("detail") or "")
        if attempts > 1:
            detail = f"{detail}; " if detail else ""
            detail += f"attempt {attempts} of {attempts}"
        state = "pass" if step.get("passed") else "fail"
        label = "PASS" if step.get("passed") else "FAIL"
        rows.append([
            _cell(lifecycle_state),
            f'<td><span class="tag {state}">{label}</span></td>',
            _cell(_local_time(step.get("at")) or "unrecorded", css="nowrap"),
            f"<td><code>{html.escape(str(step.get('command') or ''))}</code></td>",
            _cell(detail, css="detail"),
        ])
    return (
        "<h2>Workflow</h2>"
        '<p class="note">Every lifecycle state, in order. States not held in '
        "<code>PROJECT_STATUS.jsonl</code> are marked <em>not established</em>; they are not "
        "failures.</p>" + _table(("State", "Result", "When", "Command", "Detail"), rows)
    )


def _command_calls(
    commands: Sequence[Mapping[str, object]], calls: Sequence[Mapping[str, object]]
) -> tuple[tuple[Mapping[str, object], ...], ...]:
    """Attach each recorded model call to the command that made it.

    Drydock runs one command at a time, so a call belongs to the last command that started at
    or before it. A call that predates every command — a record carried over from an earlier
    window — is attached to nothing rather than to the wrong row.
    """
    starts = [str(command.get("stamp") or "") for command in commands]
    owned: list[list[Mapping[str, object]]] = [[] for _ in commands]
    for call in calls:
        stamp = str(call.get("execution_id") or "").split("-")[0]
        owner = max(
            (index for index, start in enumerate(starts) if start and start <= stamp),
            default=None,
        )
        if owner is not None:
            owned[owner].append(call)
    return tuple(tuple(group) for group in owned)


def _command_models(groups: Sequence[Sequence[Mapping[str, object]]]) -> tuple[str, ...]:
    """The models each command drove, named once even when it called one of them repeatedly."""
    names = []
    for group in groups:
        seen = dict.fromkeys(
            f"{call.get('provider') or ''}/{call.get('model') or ''}".strip("/")
            for call in group
            if call.get("provider") or call.get("model")
        )
        names.append(", ".join(seen))
    return tuple(names)


def _rerun_notes(commands: Sequence[Mapping[str, object]]) -> tuple[str, ...]:
    """Label each command that was run more than once with which attempt it is.

    A command Drydock ran, failed, and ran again is two rows, both kept. The final row carries
    its own result — green when the rerun fixed it — and the note says which attempt it was, so
    a reader is never left thinking a failure was hidden or that a pass was the first try.
    """
    keys = [_command_text(command.get("argv") or []) for command in commands]
    totals: dict[str, int] = {}
    for key in keys:
        totals[key] = totals.get(key, 0) + 1
    seen: dict[str, int] = {}
    notes = []
    for key in keys:
        seen[key] = seen.get(key, 0) + 1
        notes.append(f"rerun {seen[key]} of {totals[key]}" if totals[key] > 1 else "")
    return tuple(notes)


def _repaired_command_indices(commands: Sequence[Mapping[str, object]]) -> frozenset[int]:
    """Return failed command rows that a later clean run of the same step repaired."""
    cleared: set[str] = set()
    repaired: set[int] = set()
    for index in range(len(commands) - 1, -1, -1):
        command = commands[index]
        key = _command_key(command)
        argv = [str(part) for part in command.get("argv") or []]
        if command.get("returncode") == 0:
            if "--help" not in argv:
                cleared.add(key)
            continue
        if command.get("returncode") is None or _is_status_query(command):
            continue
        if key in cleared:
            repaired.add(index)
    return frozenset(repaired)


def _receipt_command_status_cell(
    command: Mapping[str, object], *, repaired: bool, headline: str
) -> str:
    """Render a receipt Commands result, retaining repaired failures as visible history."""
    returncode = command.get("returncode")
    argv = command.get("argv") or []
    if repaired:
        return (
            f'<td><span class="tag pass" title="exit {html.escape(str(returncode))}; '
            'later rerun exited 0"><span class="failure-history">FAIL<br>'
            '<span class="rerun">RE-RUN</span></span></span></td>'
        )
    if returncode not in (0, None) and not _is_status_query(command):
        return (
            f'<td><span class="tag fail" title="exit {html.escape(str(returncode))}">'
            f"FAIL<br>rc={html.escape(str(returncode))}</span></td>"
        )
    return _status_cell(returncode, argv, headline)


#: One tab per plan document, in reading order: ``(slug, label, filename, note)``.
#:
#: These are rendered in the page, not listed as links. A table of file names with byte counts
#: is an index to documents nobody opens; the documents themselves are what the reader came
#: for. Everything the Target holds that is not listed here stays reachable through the
#: Workspace tree, which is the complete, hashed inventory.
_PLAN_DOCUMENTS = (
    (
        "analysis",
        "Analysis",
        "ANALYSIS.md",
        "What the analysis pass read the Blueprint to ask for.",
    ),
    ("metadata", "Metadata", "METADATA.md", "The Target's identity and lifecycle state."),
    ("compass", "Compass", "COMPASS.md", "The standing guidance every block was built under."),
    (
        "build-compass",
        "Build Compass",
        "BUILD_COMPASS.md",
        "Build-time guidance layered over the Compass.",
    ),
    ("stack", "Stack", "TECHNOLOGY_STACK.md", "The technology the plan committed to."),
    ("sea-trials", "Sea Trials", "SEA_TRIALS.md", "The trials declared for this Target."),
    ("soundings", "Soundings", _SOUNDINGS_NAME, "What the run measured about itself."),
)


def _workspace_text(report_root: Path, name: str) -> str | None:
    """Read a carried workspace document, or ``None`` when it is absent or empty."""
    path = report_root / _WORKSPACE_DIR / name
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _document_head(name: str, note: str) -> str:
    """The heading every rendered document panel opens with, citing the carried file."""
    relative = f"{_WORKSPACE_DIR}/{name}"
    return f'<h2>{html.escape(name)}</h2><p class="note">{note} Source: {_anchor(relative)}.</p>'


def _document_panel(report_root: Path, name: str, note: str, lead: str = "") -> str:
    """Render one carried Markdown artifact into the receipt's own typography."""
    text = _workspace_text(report_root, name)
    if text is None:
        return ""
    return (
        _document_head(name, note)
        + lead
        + f'<article class="doc">{render_markdown(text)}</article>'
    )


def _manifest_panel(report_root: Path, result: Mapping[str, object]) -> str:
    """Render the Manifest as the Chair renders it: stat cards over a story board.

    The Manifest is the one plan document nobody reads as text — it is tens of thousands of
    bytes of block front matter. What a reader wants from it is the shape of the plan and the
    state each block reached, which is exactly what the QuarterDeck renderers produce, so
    those renderers are called here rather than reimplemented.
    """
    path = report_root / _WORKSPACE_DIR / "MANIFEST.md"
    if not path.is_file():
        return ""
    from drydock.build_plan import parse_build_plan
    from drydock.build_status import build_status
    from drydock.quarterdeck_state import _build_story_list, _manifest_story_list, _stat_cards

    try:
        plan = parse_build_plan(path)
    except Exception:  # noqa: BLE001 — a receipt reports; it never fails over a document
        return ""
    try:
        status = build_status(plan)
        # Deliberately not the Chair's "% complete", which is the verified fraction. A Target
        # whose blocks close as ``closed/implemented`` — built, with no governed acceptance
        # command covering them — verifies through its criteria, not its block states, so a
        # finalized receipt would head its plan with 0%. The criteria are on the Scorecard tab;
        # this row counts blocks, and says which kind of closure each of them reached.
        cards = _stat_cards([
            (None, str(status.steps_total), "Blocks"),
            (None, str(status.steps_verified), "Verified"),
            (None, str(status.steps_built + status.steps_implemented), "Built"),
            (None, str(status.steps_failed), "Failed"),
        ])
        board = _build_story_list(status)
    except Exception:  # noqa: BLE001 — an unbuilt plan still has a shape worth showing
        stories = [block for block in plan.blocks if block.block_type in ("story", "spike")]
        cards = _stat_cards([
            (None, str(len(stories)), "Stories"),
            (None, str(plan.state).capitalize(), "Plan state"),
        ])
        board = _manifest_story_list(plan)

    build = result.get("build") if isinstance(result.get("build"), dict) else {}
    summary = _meta([
        ("Blocks", html.escape(f"{build.get('blocks', 0)} recorded")),
        ("Unverified blocks", html.escape(str(len(build.get("failed") or ())))),
        ("Repaired blocks", html.escape(str(len(build.get("repaired") or ())))),
    ])
    return (
        _document_head(
            "MANIFEST.md",
            "Every block the plan carries, grouped by feature, with the state this run left it in.",
        )
        + f'<div class="stats">{cards}</div>'
        + summary
        + board
    )


def _scorecard_panel(report_root: Path, result: Mapping[str, object]) -> str:
    """Render SCORECARD.md as the Chair's verdict board."""
    from drydock.quarterdeck_state import _scorecard_html

    board = _scorecard_html(report_root / _WORKSPACE_DIR)
    if not board:
        return ""
    acceptance = result.get("acceptance") if isinstance(result.get("acceptance"), dict) else {}
    summary = _meta([
        ("Criteria", html.escape(str(acceptance.get("total", 0)))),
        ("Criteria passed", html.escape(str(acceptance.get("passed", 0)))),
        ("Criteria failed", html.escape(str(acceptance.get("failed", 0)))),
    ])
    return (
        _document_head(
            "SCORECARD.md",
            "The completion gate and every project acceptance criterion, as this run last "
            "scored them.",
        )
        + summary
        + board
    )


def _analysis_lead(report_root: Path) -> str:
    """The Chair's story-shape breakdown, shown above the analysis text."""
    from drydock.quarterdeck_state import _render_story_breakdown_html

    text = _workspace_text(report_root, "ANALYSIS.md")
    return _render_story_breakdown_html(text) if text else ""


def _plan_panels(report_root: Path, result: Mapping[str, object]) -> list[tuple[str, str, str]]:
    """One panel per plan artifact, each rendered rather than linked."""
    panels = [
        ("plan-manifest", "Manifest", _manifest_panel(report_root, result)),
        ("plan-scorecard", "Scorecard", _scorecard_panel(report_root, result)),
    ]
    for slug, label, name, note in _PLAN_DOCUMENTS:
        lead = _analysis_lead(report_root) if name == "ANALYSIS.md" else ""
        panels.append((f"plan-{slug}", label, _document_panel(report_root, name, note, lead)))
    return panels


def _files_of(groups: Sequence[ArtifactGroup], name: str) -> tuple[FileRecord, ...]:
    return next((group.files for group in groups if group.name == name), ())


def _render(
    report_root: Path,
    result: Mapping[str, object],
    groups: Sequence[ArtifactGroup],
    delivered: str,
) -> str:
    """Render the receipt an operator opens from the Target's workspace."""
    target = str(result.get("target") or report_root.name)
    workflow = [step for step in result.get("workflow") or () if isinstance(step, dict)]
    state = _workflow_state(result)
    commands = [item for item in result.get("commands") or [] if isinstance(item, dict)]
    checks = _receipt_checks(report_root, result)

    calls = _llm_calls(report_root / _LOGS_DIR / _RECORDS_NAME, report_root)
    owned = _command_calls(commands, calls)
    models = _command_models(owned)
    notes = _rerun_notes(commands)
    repaired = _repaired_command_indices(commands)

    command_rows: list[list[str]] = []
    for index, command in enumerate(commands):
        stdout = str(command.get("stdout_path") or "")
        model = models[index]
        note = notes[index]
        text = html.escape(_command_text(command.get("argv") or []))
        annotation = f' <span class="tag raw">{html.escape(model)}</span>' if model else ""
        rerun = f' <span class="tag">{html.escape(note)}</span>' if note else ""
        command_rows.append([
            _cell(index + 1, css="num"),
            _cell(
                _local_time(_iso(str(command.get("stamp") or ""))) or command.get("time") or "",
                css="nowrap",
            ),
            f"<td><code>{text}</code>{annotation}{rerun}</td>",
            _receipt_command_status_cell(
                command,
                repaired=index in repaired,
                headline=recorded_status_headline(report_root, stdout, command.get("argv") or []),
            ),
            _cell(f"{int(command.get('elapsed_ms') or 0) / 1000:.1f}s", css="num"),
            _stream_link(report_root, stdout, "transcript"),
        ])
    commands_table = (
        "<h2>Commands</h2>"
        '<p class="note">Every command Drydock ran for this Target in this run, in order, with '
        "the model it drove and its captured transcript.</p>"
        + _table(("#", "When", "Command", "Result", "Elapsed", "Transcript"), command_rows)
    )

    failed = _outstanding_failures(commands)
    excerpt = ""
    if failed:
        last = failed[-1]
        relative = str(last.get("stdout_path") or "")
        text = _tail(report_root / relative) if relative else ""
        if text:
            excerpt = (
                "<h2>Recorded failure output</h2>"
                f'<p class="note">Command <code>'
                f"{html.escape(_command_text(last.get('argv') or []))}</code> exited "
                f"{html.escape(str(last.get('returncode')))}. The text below is quoted verbatim "
                "from its captured transcript.</p>"
                f'<p class="note">Tail of <code>{html.escape(relative)}</code>.</p>'
                f"<pre>{html.escape(text[-4000:])}</pre>"
            )

    call_rows = [
        [
            _cell(call["command"]),
            _cell(f"{call['provider']}/{call['model']}"),
            _status_cell(call["returncode"]),
            _cell(_local_time(_iso(str(call["execution_id"]).split("-")[0])), css="nowrap"),
            _cell(f"{int(call['elapsed_ms'] or 0) / 1000:.1f}s", css="num"),
            _cell(f"{int(call['cached_input_tokens']):,}", css="num"),
            _cell(
                f"{max(int(call['input_tokens']) - int(call['cached_input_tokens']), 0):,}",
                css="num",
            ),
            _cell(f"{int(call['output_tokens']):,}", css="num"),
            # Linked through the existence check, not blindly: a record can name an artifact
            # the run never wrote, and a receipt that links a missing file makes a claim its
            # reader cannot check. The assembled prompt and the wire transcript are named by
            # the record but are not carried, so neither is offered here.
            _stream_link(report_root, str(call["output"]), "output"),
            _stream_link(report_root, str(call["llm_log"]), "llm"),
        ]
        for call in calls
    ]
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    llm_panel = (
        "".join([
            "<h2>LLM executions</h2>",
            '<p class="note">One row per model invocation, with its token accounting and the '
            "output it returned.</p>",
            _meta([
                ("Calls", html.escape(str(usage.get("calls", 0)))),
                ("Usage", html.escape(_tokens(dict(usage)))),
                (
                    "Model time",
                    f"{int(usage.get('llm_elapsed_ms') or 0) / 1000:.1f}s",
                ),
            ]),
            _table(
                (
                    "Command",
                    "Model",
                    "Result",
                    "When",
                    "Elapsed",
                    "Cached",
                    "Uncached",
                    "Output",
                    "",
                    "llm",
                ),
                call_rows,
            ),
        ])
        if call_rows
        else ""
    )

    scores = (
        result.get("score_exit_codes") if isinstance(result.get("score_exit_codes"), dict) else {}
    )
    score_rows = [[_cell(name), _status_cell(code)] for name, code in sorted(scores.items())]
    scores_block = (
        "<h2>Recorded scores</h2>"
        '<p class="note">The exit code each score last reported for this Target.</p>'
        + _table(("Score", "Result"), score_rows)
        if score_rows
        else ""
    )
    scores_panel = scores_block + _render_receipt(report_root, checks, tags=_RECEIPT_TAGS)

    workspace_files = _files_of(groups, "Workspace")
    workspace_tree = (
        "<h2>Output</h2>"
        f'<p class="note">The Target Drydock drove. {len(workspace_files)} files, '
        f"{sum(record.bytes for record in workspace_files):,} bytes.</p>"
        + _tree(workspace_files, _WORKSPACE_DIR, f"{_WORKSPACE_DIR}/")
        if workspace_files
        else ""
    )

    environment = result.get("environment") if isinstance(result.get("environment"), dict) else {}
    docline = " · ".join(
        part
        for part in (
            f"Run {result.get('run_id') or ''}",
            f"Target {target}",
            f"{environment.get('provider') or ''}/{environment.get('model') or ''}"
            if environment.get("provider") or environment.get("model")
            else "",
            local_run_window(environment),
        )
        if part
    )
    marks = {"pass": "Accepted", "fail": "Not accepted", "warn": "In progress"}
    overview = "\n".join([
        _verdict(
            state == "pass",
            _state_headline(result),
            _detail_line(result),
        ),
        _ladder_table(workflow),
        _meta(_run_facts(result, delivered)),
        run_notes(),
    ])
    build_panel = _tabs(
        [
            ("steps", "Commands", commands_table),
            ("error", "Error", excerpt),
            ("llm", "LLM", llm_panel),
            ("scores", "Scores", scores_panel),
            ("output", "Output", workspace_tree),
        ],
        group="build",
    )
    plan_panel = _tabs(_plan_panels(report_root, result), group="plan")
    return _page(
        f"Drydock build receipt — {target}",
        "\n".join([
            _letterhead(
                "Build Receipt",
                target,
                docline,
                state,
                marks[state],
                "Drydock",
            ),
            _tabs(
                [
                    ("overview", "OVERVIEW", overview),
                    ("build", "BUILD", build_panel),
                    ("plan", "PLAN", plan_panel),
                ],
                group="receipt",
            ),
            "<footer>Generated by <code>drydock score report</code> from the command and "
            "execution journals this Target recorded. Every file listed is carried in this "
            "directory and hashed in "
            f"{_anchor('SHA256SUMS')}. Record: {_anchor(_RECORD_NAME)}</footer>",
        ]),
    )


def write_report(target: str, workspace: Path, target_dir: Path, build_dir: Path) -> Path:
    """Publish the Target's latest run as a receipt under ``<Target>/drydock_receipt/``.

    Returns the written ``index.html``. Raises :class:`ReportError` when the Target has
    recorded nothing to report.
    """
    # The machine is settled before the record is collected, so the document only ever
    # reports states the file holds — including the FINALIZED this publication earns.
    _reconcile_acceptance(target, target_dir, _acceptance(target_dir))
    _earn_finalized(target, target_dir)

    result = collect_run(target, workspace, target_dir)
    report_root = target_dir / REPORT_DIRNAME
    _publish(target, workspace, target_dir, report_root, result)
    groups = _report_groups(report_root, target)

    # Viewers are written before the receipt so every link it emits can point at one.
    published = [record.path for group in groups for record in group.files]
    viewers = _write_viewers(report_root, published, "Run artifact", _INDEX_NAME)
    index = report_root / _INDEX_NAME
    with _viewers(viewers):
        index.write_text(_render(report_root, result, groups, str(build_dir)), encoding="utf-8")
    # Sealed last, once every file the inventory names is final. index.html is excluded by
    # `_iter_files`, so the page can be regenerated without invalidating the seal.
    _write_sums(report_root, groups)
    return index
