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
#: application: the document describes the delivery, it is not part of it. Everything it
#: shows — including the delivered code — is copied in, so the directory is a frozen,
#: self-contained snapshot of the build at the moment the receipt was written.
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

_INVENTORY_TABS = {
    "Delivered code": ("delivered", "Code"),
    "Evidence": ("logs", "Evidence"),
    "Workspace": ("workspace", "Workspace"),
}

#: The delivered application is copied under the receipt, so its paths are addressed from
#: the report directory like every other tree the document carries.
_DELIVERED_PREFIX = "delivered"


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

    ``drydock score <Target>`` with no sub-verb is recorded under ``ac``: that is the score it
    ran before the sub-verb was required.
    """
    codes: dict[str, int] = {}
    for command in commands:
        argv = [str(part) for part in command.get("argv") or []][1:]  # drop the "drydock" shim
        if not argv or argv[0] != "score":
            continue
        code = command.get("returncode")
        if not isinstance(code, int):
            continue
        verb = next((token for token in argv[1:] if token in _SCORE_VERBS), "ac")
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


#: The lifecycle state each recorded command establishes. ``drydock plan`` names two states,
#: separated by its sub-verb; ``drydock score`` names one per sub-verb.
_VERB_LABELS = {
    "init": "INITIALIZED",
    "import": "IMPORTED",
    "analyze": "ANALYZED",
    "plan": "PLAN CREATED",
    "build": "BUILT",
}
_SCORE_LABELS = {
    "ac": "LLM ACCEPTANCE CHECKS OK",
    "build": "SCORE BUILD",
    "release": "SCORE RELEASE",
    "report": "FINALIZED",
}

#: Sub-verbs of ``drydock build`` that inspect a build rather than perform one.
_BUILD_SUBVERBS = frozenset({"status", "score"})

#: Exit 2 is a usage error or a deferred command. Neither reached the state its verb names,
#: so neither belongs on the ladder — as a pass or as a failure.
_NOT_AN_ATTEMPT = 2


def _ladder_label(argv: Sequence[object]) -> str:
    """The workflow state a recorded command establishes, or ``""`` if it establishes none."""
    tokens = [str(part) for part in argv][1:]  # drop the "drydock" shim
    if not tokens:
        return ""
    verb = tokens[0]
    if verb == "plan":
        return "PLAN REPAIRED" if "repair" in tokens[1:] else "PLAN CREATED"
    if verb == "build" and len(tokens) > 1 and tokens[1] in _BUILD_SUBVERBS:
        return ""  # `build status` and `build score` read a build; they do not make one
    if verb == "score":
        # A bare `drydock score <Target>` is the acceptance score, as `_score_exit_codes` reads it.
        sub = next((token for token in tokens[1:] if token in _SCORE_VERBS), "ac")
        return _SCORE_LABELS.get(sub, "")
    return _VERB_LABELS.get(verb, "")


def _workflow(
    target_dir: Path, commands: Sequence[Mapping[str, object]]
) -> list[dict[str, object]]:
    """The workflow ladder for this run: one row per state the Target actually attempted.

    Two sources, in increasing authority. Every recorded command names the state it
    establishes, which gives a ladder for Targets built before Drydock persisted one.
    ``PROJECT_STATUS.md`` then overrides what it holds, because a command that recorded its
    own outcome knows more than its exit code does — a build that exits 0 with stalled blocks
    is not BUILT.

    A state never attempted is absent. It is never rendered as a failure or as a claim.
    """
    from drydock.project_status import LABEL_LADDER, latest_per_label, read_status

    steps: dict[str, dict[str, object]] = {}
    for command in commands:
        label = _ladder_label(command.get("argv") or [])
        code = command.get("returncode")
        if not label or code == _NOT_AN_ATTEMPT:
            continue
        text = _command_text(command.get("argv") or [])
        steps[label] = {
            "label": label,
            "passed": code == 0,
            "at": _iso(str(command.get("stamp") or "")),
            "detail": "" if code == 0 else f"exited {code}",
            "command": text,
            "attempts": int(steps.get(label, {}).get("attempts", 0)) + 1,
        }

    entries = read_status(target_dir)
    attempts: dict[str, int] = {}
    for entry in entries:
        attempts[entry.label] = attempts.get(entry.label, 0) + 1
    for label, entry in latest_per_label(entries).items():
        steps[label] = {
            "label": label,
            "passed": entry.passed,
            "at": entry.at,
            "detail": entry.detail,
            "command": entry.command,
            "attempts": attempts.get(label, 1),
        }

    # BUILDING is the marker `drydock build` writes on entry. Once the build reported an
    # outcome it says nothing the BUILT row does not, so it is shown only while it stands alone.
    if "BUILT" in steps:
        steps.pop("BUILDING", None)

    # FINALIZED describes an earlier publication of this receipt, which the one being written
    # supersedes. Carrying it forward would let a second `drydock score report` finalize a run
    # on the strength of the first, so the state is only ever earned by `_finalize`.
    steps.pop("FINALIZED", None)

    return [steps[label] for label in LABEL_LADDER if label in steps]


def _workflow_state(workflow: Sequence[Mapping[str, object]]) -> str:
    """Grade the ladder: ``fail`` on any failed state, ``pass`` once finalized, else ``warn``."""
    if any(not step.get("passed") for step in workflow):
        return "fail"
    if any(step.get("label") == "FINALIZED" for step in workflow):
        return "pass"
    return "warn"


def _finalize(workflow: list[dict[str, object]], target: str) -> list[dict[str, object]]:
    """Add the FINALIZED row this receipt is itself earning, when the run has earned it.

    Publishing the receipt is the finalizing act, so the document cannot wait for a state it
    is in the middle of establishing. It is only claimed for a run that failed nothing and
    was scored: a receipt published over an unscored build reports an unfinished project,
    which is what the amber stamp is for.
    """
    if any(not step.get("passed") for step in workflow):
        return workflow
    scored = any(step.get("label") == "SCORE BUILD" for step in workflow)
    if not scored:
        return workflow
    workflow = [step for step in workflow if step.get("label") != "FINALIZED"]
    workflow.append({
        "label": "FINALIZED",
        "passed": True,
        "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + "000Z",
        "detail": "receipt published",
        "command": f"drydock score report {target}",
        "attempts": 1,
    })
    return workflow


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

    # The verdict is the lifecycle the Target recorded, not an inference from one artifact.
    # An acceptance failure is a failed state on the ladder like any other, so it lands in the
    # same place; a board that was never recorded withholds nothing, because the states that
    # did run still say exactly how far the project got.
    workflow = _workflow(target_dir, commands)
    if acceptance["failed"]:
        for step in workflow:
            if step["label"] == "LLM ACCEPTANCE CHECKS OK":
                step["passed"] = False
                step["detail"] = f"{len(acceptance['failures'])} criteria failed"
    workflow = _finalize(workflow, target)
    status = {"pass": "passed", "fail": "failed", "warn": "incomplete"}[_workflow_state(workflow)]

    from drydock import __version__

    return {
        "target": target,
        "run_id": start_key,
        "status": status,
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

    failures = [
        command
        for command in commands
        if command.get("returncode") not in (0, None) and _verb_of(command) != "status"
    ]
    checks.append(
        Check(
            "Every recorded command exited clean",
            "pass" if not failures else "fail",
            f"{len(commands)} commands recorded"
            + (
                "; every one exited 0."
                if not failures
                else f"; {len(failures)} exited nonzero, the last at {failures[-1].get('label')}."
            ),
            _RECORD_NAME,
        )
    )
    del report_root
    return tuple(checks)


def _verb_of(command: Mapping[str, object]) -> str:
    argv = [str(part) for part in command.get("argv") or []]
    return argv[1] if len(argv) > 1 else ""


# ── publishing ───────────────────────────────────────────────────────────────────────


def _copy_tree(source: Path, destination: Path, *, skip: Path | None = None) -> None:
    if not source.is_dir():
        return
    ignore = None
    if skip is not None:
        skipped = skip.resolve()

        def ignore(directory: str, names: list[str]) -> set[str]:
            return {name for name in names if (Path(directory) / name).resolve() == skipped}

    shutil.copytree(source, destination, dirs_exist_ok=True, symlinks=False, ignore=ignore)
    prune_generated(destination)


def _write_journal_slice(source: Path, destination: Path, keep) -> None:
    """Copy the records of one journal that belong to this run, in recorded order."""
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
    build_dir: Path,
    report_root: Path,
    result: Mapping[str, object],
) -> None:
    """Copy every artifact the receipt links into the report directory.

    Everything: transcripts, assembled prompts, provider output, the Target's own workspace,
    and the delivered application itself. A receipt that links a file it did not carry is a
    claim its reader cannot check, and the receipt now lives outside the build tree, so the
    delivered code has to travel with it. What the document shows is the build as it stood
    when the receipt was written, frozen; the operator's build directory is never modified.
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

    # The receipt's own previous edition lives inside the Target, so it is never copied into
    # the workspace tree: a receipt does not carry a copy of itself.
    _copy_tree(target_dir, report_root / _WORKSPACE_DIR, skip=report_root)
    _copy_tree(build_dir, report_root / _DELIVERED_PREFIX)

    record_path = report_root / _RECORD_NAME
    record_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # The journals record absolute paths on the machine that ran the build. A published receipt
    # states every path relative to itself, so the page reads the same anywhere it is copied.
    for path in (record_path, destination / _RECORDS_NAME):
        _make_portable(path, workspace)


def _report_groups(report_root: Path, target: str) -> tuple[ArtifactGroup, ...]:
    """The three trees a receipt shows, plus its own machine-readable record.

    Every file is hashed. The receipt is a published artifact in its own directory now, so it
    is sealed the way a UAT kit is: a reader who was handed the directory can verify it.
    """
    groups = [
        ArtifactGroup(
            "Delivered code",
            f"Application drydock build produced for {target}, as the build left it.",
            tuple(_iter_files(report_root / _DELIVERED_PREFIX, report_root, hidden=False)),
        ),
        ArtifactGroup(
            "Evidence",
            "Command transcripts, assembled prompts, model output, provider transcripts, and "
            "the command and execution journals for this run.",
            tuple(_iter_files(report_root / _LOGS_DIR, report_root, hidden=False)),
        ),
        ArtifactGroup(
            "Workspace",
            "The Target Drydock drove: Blueprint, Manifest, acceptance board, and evidence.",
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
    """The provenance a reader needs before reading anything else the run wrote."""
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


def _detail_line(result: Mapping[str, object]) -> str:
    """State how far the recorded lifecycle got, and stop there."""
    workflow = [step for step in result.get("workflow") or () if isinstance(step, dict)]
    target = html.escape(str(result.get("target") or ""))
    if not workflow:
        return (
            f"{target} has recorded no lifecycle state. The commands below are everything "
            "this receipt can show."
        )
    failed = [step for step in workflow if not step.get("passed")]
    reached = str(workflow[-1].get("label") or "")
    if failed:
        names = ", ".join(html.escape(str(step.get("label"))) for step in failed)
        return f"{target} reached {html.escape(reached)}; {names} failed."
    if reached == "FINALIZED":
        return f"{target} reached FINALIZED; every recorded state passed."
    return (
        f"{target} reached {html.escape(reached)}; every recorded state passed, but the "
        "project is not finished."
    )


def _ladder_table(workflow: Sequence[Mapping[str, object]]) -> str:
    """Render the workflow ladder: one row per state the Target attempted, in order."""
    rows = []
    for step in workflow:
        attempts = int(step.get("attempts") or 1)
        detail = str(step.get("detail") or "")
        if attempts > 1:
            detail = f"{detail}; " if detail else ""
            detail += f"attempt {attempts} of {attempts}"
        state = "pass" if step.get("passed") else "fail"
        label = "PASS" if step.get("passed") else "FAIL"
        rows.append([
            _cell(str(step.get("label") or "")),
            f'<td><span class="tag {state}">{label}</span></td>',
            _cell(_local_time(step.get("at")) or "unrecorded", css="nowrap"),
            f"<td><code>{html.escape(str(step.get('command') or ''))}</code></td>",
            _cell(detail, css="detail"),
        ])
    return (
        "<h2>Workflow</h2>"
        '<p class="note">Every lifecycle state this Target recorded, in order. A state that '
        "was never attempted is not listed.</p>"
        + _table(("State", "Result", "When", "Command", "Detail"), rows)
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


_PLAN_DOCUMENTS = (
    "METADATA.md",
    "ANALYSIS.md",
    "MANIFEST.md",
    "BUILD_COMPASS.md",
    "COMPASS.md",
    "TECHNOLOGY_STACK.md",
    "SEA_TRIALS.md",
    _SOUNDINGS_NAME,
    "SCORECARD.md",
    "PROJECT_STATUS.md",
)


def _plan_panel(
    report_root: Path, files: Sequence[FileRecord], result: Mapping[str, object]
) -> str:
    """The bookkeeping the plan was driven from, as this run left it."""
    sizes = {record.path: record.bytes for record in files}
    rows = []
    for name in _PLAN_DOCUMENTS:
        relative = f"{_WORKSPACE_DIR}/{name}"
        if relative not in sizes:
            continue
        rows.append([
            f"<td><code>{html.escape(name)}</code></td>",
            _cell(f"{sizes[relative]:,}", css="num"),
            _stream_link(report_root, relative, "open"),
        ])
    build = result.get("build") if isinstance(result.get("build"), dict) else {}
    acceptance = result.get("acceptance") if isinstance(result.get("acceptance"), dict) else {}
    summary = _meta([
        ("Blocks", html.escape(f"{build.get('blocks', 0)} recorded")),
        ("Unverified blocks", html.escape(str(len(build.get("failed") or ())))),
        ("Repaired blocks", html.escape(str(len(build.get("repaired") or ())))),
        ("Criteria", html.escape(str(acceptance.get("total", 0)))),
        ("Criteria passed", html.escape(str(acceptance.get("passed", 0)))),
        ("Criteria failed", html.escape(str(acceptance.get("failed", 0)))),
    ])
    return (
        "<h2>Plan of record</h2>"
        '<p class="note">The Manifest, Compass, acceptance board, and scorecard as this run '
        "left them, copied into this receipt.</p>"
        + summary
        + _table(("Document", "Bytes", ""), rows)
    )


def _under(files: Sequence[FileRecord], prefix: str) -> tuple[FileRecord, ...]:
    return tuple(record for record in files if record.path.startswith(prefix))


def _files_of(groups: Sequence[ArtifactGroup], name: str) -> tuple[FileRecord, ...]:
    return next((group.files for group in groups if group.name == name), ())


def _render(
    report_root: Path, result: Mapping[str, object], groups: Sequence[ArtifactGroup]
) -> str:
    """Render the receipt an operator opens from the Target's workspace."""
    target = str(result.get("target") or report_root.name)
    workflow = [step for step in result.get("workflow") or () if isinstance(step, dict)]
    state = _workflow_state(workflow)
    commands = [item for item in result.get("commands") or [] if isinstance(item, dict)]
    checks = _receipt_checks(report_root, result)

    calls = _llm_calls(report_root / _LOGS_DIR / _RECORDS_NAME, report_root)
    owned = _command_calls(commands, calls)
    models = _command_models(owned)
    notes = _rerun_notes(commands)

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
            _status_cell(
                command.get("returncode"),
                command.get("argv") or [],
                recorded_status_headline(report_root, stdout, command.get("argv") or []),
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

    failed = [
        command
        for command in commands
        if command.get("returncode") not in (0, None) and _verb_of(command) != "status"
    ]
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
            # reader cannot check.
            _stream_link(report_root, str(call["prompt"]), "prompt"),
            _stream_link(report_root, str(call["output"]), "output"),
            _stream_link(report_root, str(call["raw"]), "transcript"),
            _stream_link(report_root, str(call["llm_log"]), "llm"),
        ]
        for call in calls
    ]
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    llm_panel = (
        "".join([
            "<h2>LLM executions</h2>",
            '<p class="note">One row per model invocation, with the exact prompt sent, the '
            "output returned, and the raw provider transcript.</p>",
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
                    "",
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

    delivered = _files_of(groups, "Delivered code")
    delivered_tree = (
        "<h2>Delivered code</h2>"
        f'<p class="note">The application this receipt documents, {len(delivered)} files, '
        f"{sum(record.bytes for record in delivered):,} bytes, copied into this receipt as the "
        "build left it.</p>" + _tree(delivered, _DELIVERED_PREFIX, f"{target}/")
        if delivered
        else ""
    )

    workspace_files = _files_of(groups, "Workspace")
    blueprint = _under(workspace_files, f"{_WORKSPACE_DIR}/blueprint/")
    input_tree = (
        "<h2>Blueprint</h2>"
        f'<p class="note">The specification Drydock built from, including the user sources '
        f"imported under <code>sources/</code>. {len(blueprint)} files, "
        f"{sum(record.bytes for record in blueprint):,} bytes.</p>"
        + _tree(blueprint, f"{_WORKSPACE_DIR}/blueprint", "blueprint/")
        if blueprint
        else ""
    )
    evidence_files = _files_of(groups, "Evidence")
    evidence_tree = (
        "<h2>Evidence</h2>"
        f'<p class="note">Transcripts, prompts, model output, and the journals for this run. '
        f"{len(evidence_files)} files, {sum(record.bytes for record in evidence_files):,} "
        "bytes.</p>" + _tree(evidence_files, _LOGS_DIR, f"{_LOGS_DIR}/")
        if evidence_files
        else ""
    )
    workspace_tree = (
        "<h2>Workspace</h2>"
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
    status = str(result.get("status") or "")
    overview = "\n".join([
        _verdict(
            state == "pass",
            f"{target}: {status.upper()}",
            _detail_line(result),
        ),
        _ladder_table(workflow),
        _meta(_run_facts(result, f"{_DELIVERED_PREFIX}/")),
        run_notes(),
    ])
    build_panel = _tabs(
        [
            ("steps", "Commands", commands_table),
            ("error", "Error", excerpt),
            ("llm", "LLM", llm_panel),
            ("scores", "Scores", scores_panel),
            ("evidence", "Evidence", evidence_tree),
        ],
        group="build",
    )
    plan_panel = _tabs(
        [
            ("plan-docs", "Documents", _plan_panel(report_root, workspace_files, result)),
            ("plan-workspace", "Workspace", workspace_tree),
        ],
        group="plan",
    )
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
                    ("output", "OUTPUT", delivered_tree),
                    ("input", "INPUT", input_tree),
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
    result = collect_run(target, workspace, target_dir)
    report_root = target_dir / REPORT_DIRNAME
    _publish(target, workspace, target_dir, build_dir, report_root, result)
    groups = _report_groups(report_root, target)

    # Viewers are written before the receipt so every link it emits can point at one. The
    # delivered application is linked raw: it is source code, read in the reader's own tools.
    published = [
        record.path
        for group in groups
        for record in group.files
        if not record.path.startswith(f"{_DELIVERED_PREFIX}/")
    ]
    viewers = _write_viewers(report_root, published, "Run artifact", _INDEX_NAME)
    index = report_root / _INDEX_NAME
    with _viewers(viewers):
        index.write_text(_render(report_root, result, groups), encoding="utf-8")
    # Sealed last, once every file the inventory names is final. index.html is excluded by
    # `_iter_files`, so the page can be regenerated without invalidating the seal.
    _write_sums(report_root, groups)
    return index
