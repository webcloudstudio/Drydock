"""What ``drydock diagnose`` reads, and the bounded bundle it hands the model.

The report has to be repair-grade: someone who never saw the run must be able to fix the code
from it alone. That rules out a bundle of conclusions. It has to carry the failing text itself,
the criteria that disagreed, the governed inputs a correction would amend, and the exact local
paths of every stream a reader might want to open next.

It also has to fit in a prompt. Every excerpt here is line-bounded, and the bounds are stated in
the bundle so the model never presents a truncated file as a whole one.

Reading only. Nothing here calls a model, executes a proof, or writes to the Target.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from drydock.diagnose_ladder import LadderRow, StopPoint, build_ladder, stop_point_of
from drydock.project_status import StatusEntry, read_status
from drydock.run_window import (
    history_tokens,
    llm_records,
    run_logs,
    run_window,
    sibling_prefixes,
    stamp_key,
    target_history,
)

#: Per-excerpt line budgets. A diagnosis reads the end of a transcript, where the failure is,
#: and the start of a governed input, where its rules are.
MAX_TRANSCRIPT_LINES = 120
MAX_SCORECARD_LINES = 80
MAX_BLOCKERS_LINES = 60
MAX_GOVERNED_LINES = 400
MAX_BLUEPRINT_LINES = 600

#: Repairs include decision-linked and unfinished consumers' Blueprints. A Blueprint the prompt
#: did not carry in full cannot be verified.
MAX_BLUEPRINTS = 6
BLUEPRINT_PREFIX = "blueprint/"
REPAIR_STATES = frozenset({"blocked/questions", "closed/failed", "closed/implemented", "pending"})

#: The files an amendment may target. ``MANIFEST.md`` is included: an acceptance criterion that
#: cannot pass, or a stage that must be rerun, is a Manifest-level correction.
AMENDABLE = ("COMPASS.md", "PLAN_COMPASS.md", "ANALYZE_COMPASS.md", "MANIFEST.md")

#: Log roles carried into the report, in the order a reader would open them.
LOG_ROLES = ("llm_log", "prompt", "output", "raw")

#: Model executions whose artifacts the report cites, counted back from the stop. A run can
#: record hundreds; a reader opening evidence wants the calls around the failure, and a table
#: of every call the run ever made is a table nobody reads.
MAX_CITED_EXECUTIONS = 6


@dataclass(frozen=True)
class LogFile:
    """One local evidence file the report cites by path, so the reader can open it."""

    role: str
    path: str
    exists: bool
    size: int = 0
    sha256: str = ""


@dataclass(frozen=True)
class Excerpt:
    """A bounded slice of a file, honest about being a slice."""

    name: str
    path: str
    text: str
    truncated: bool = False
    total_lines: int = 0


@dataclass(frozen=True)
class Bundle:
    """Everything the diagnosis prompt is given, and everything the report header states."""

    target: str
    target_dir: Path
    run_stamp: str
    ladder: tuple[LadderRow, ...]
    stop: StopPoint | None
    superseded: tuple[StatusEntry, ...]
    commands: tuple[Mapping[str, object], ...]
    logs: tuple[LogFile, ...]
    transcripts: tuple[Excerpt, ...]
    scorecard: Excerpt | None
    blockers: Excerpt | None
    decisions: tuple[Mapping[str, object], ...]
    governed: tuple[Excerpt, ...]
    missing: tuple[str, ...] = field(default_factory=tuple)
    #: Repairable Blueprints, named ``blueprint/<file>``.
    blueprints: tuple[Excerpt, ...] = field(default_factory=tuple)
    execution: tuple[str, str] = ("unknown", "not collected")

    @property
    def failed_commands(self) -> tuple[Mapping[str, object], ...]:
        return tuple(
            command for command in self.commands if int(command.get("return_code") or 0) != 0
        )


def collect(target: str, workspace: Path, target_dir: Path, *, run: str = "") -> Bundle:
    """Assemble the evidence bundle for a Target's latest run.

    Every input is optional and independently guarded. A Target missing its scorecard, its
    logs, or its governed files still produces a bundle; what is absent is named in
    ``missing`` so the report says so rather than implying the evidence was examined.
    """
    missing: list[str] = []
    entries = read_status(target_dir)
    stop = stop_point_of(entries)
    from drydock.diagnose_ladder import superseded_failures

    history = run_window(target_history(workspace, target))
    if run:
        history = [record for record in history if stamp_key(record) >= run]
    start_key = stamp_key(history[0]) if history else ""
    run_stamp = stamp_key(history[-1]) if history else ""
    if not history:
        missing.append("logs/history.jsonl has no commands for this Target")

    calls = llm_records(workspace / "logs" / "llm.jsonl", target, start_key) if start_key else []
    logs = _log_files(calls, history)
    transcripts = _transcripts(workspace, target, start_key, history)
    if not transcripts:
        missing.append("no command transcript found in logs/")

    scorecard = _excerpt(target_dir / "SCORECARD.md", "SCORECARD.md", MAX_SCORECARD_LINES)
    if scorecard is None:
        missing.append("SCORECARD.md")
    blockers = _excerpt(target_dir / "BLOCKERS.md", "BLOCKERS.md", MAX_BLOCKERS_LINES)

    governed = tuple(
        excerpt
        for name in AMENDABLE
        if (excerpt := _excerpt(target_dir / name, name, MAX_GOVERNED_LINES)) is not None
    )
    for name in AMENDABLE:
        if not (target_dir / name).is_file():
            missing.append(name)

    from drydock.status import execution_state

    decisions = open_decisions(target_dir)
    return Bundle(
        target=target,
        target_dir=target_dir,
        run_stamp=run_stamp,
        ladder=build_ladder(target_dir, ladder_notes(target_dir)),
        stop=stop,
        superseded=superseded_failures(entries),
        commands=tuple(history),
        logs=logs,
        transcripts=transcripts,
        scorecard=scorecard,
        blockers=blockers,
        decisions=decisions,
        governed=governed,
        missing=tuple(missing),
        blueprints=failing_blueprints(target_dir, decisions=decisions),
        execution=execution_state(target_dir),
    )


def failing_blueprints(
    target_dir: Path,
    *,
    decisions: Sequence[Mapping[str, object]] | None = None,
) -> tuple[Excerpt, ...]:
    """Decision-linked Blueprints, then failed, blocked, and unfinished consumers' inputs.

    These are what a repair can specify more precisely. Imported sources and change tickets are
    never candidates, and a compact derivative resolves to its source, which is what a repair edits.
    """
    from drydock.build_plan import compact_source, parse_build_plan
    from drydock.config import blueprint_dir_for

    blueprint_dir = blueprint_dir_for(target_dir)
    names: list[str] = []
    candidates = [
        str(row["blueprint"])
        for row in (open_decisions(target_dir) if decisions is None else decisions)
        if not row.get("archived")
        and (
            row.get("severity") == "blocking"
            or str(row.get("id", "")).startswith(("build-skip-", "build-env-unresolved-"))
        )
    ]
    try:
        plan = parse_build_plan(target_dir / "MANIFEST.md")
    except Exception:  # noqa: BLE001 — decision-linked files remain repairable
        plan = None
    priority = {"closed/failed": 0, "blocked/questions": 1, "closed/implemented": 2, "pending": 3}
    for block in sorted(plan.blocks if plan else (), key=lambda item: priority.get(item.state, 4)):
        if block.state not in REPAIR_STATES:
            continue
        candidates.extend(str(name) for name in block.fields.get("implements", ()))
    for name in candidates:
        source = compact_source(name.removeprefix(BLUEPRINT_PREFIX))
        if (
            "/" in source
            or "\\" in source
            or source in names
            or not source.endswith(".md")
            or not (blueprint_dir / source).is_file()
            or (blueprint_dir / source).resolve().parent != blueprint_dir.resolve()
        ):
            continue
        names.append(source)
    return tuple(
        excerpt
        for name in names[:MAX_BLUEPRINTS]
        if (excerpt := _excerpt(blueprint_dir / name, BLUEPRINT_PREFIX + name, MAX_BLUEPRINT_LINES))
        is not None
    )


def ladder_notes(target_dir: Path) -> dict[str, str]:
    """Short deterministic annotations for the milestone rows, drawn from Target artifacts.

    Purely cosmetic: a missing or malformed artifact yields no note, never an error.
    """
    notes: dict[str, str] = {}
    stories = _manifest_story_count(target_dir / "MANIFEST.md")
    if stories:
        notes["ANALYZE"] = f"{stories} stories"
    acceptance = _acceptance_tally(target_dir / "ACCEPTANCE.json")
    if acceptance:
        notes["SCORE"] = acceptance
    return notes


def open_decisions(target_dir: Path) -> tuple[Mapping[str, object], ...]:
    """Complete decision records, including Commander answers and system disclosures.

    A blocking decision is frequently the actual reason a stage stopped, and is invisible in a
    transcript. A malformed file loads as no decisions rather than failing the diagnosis.
    """
    try:
        from drydock.decisions import load_decisions, render_decisions

        decisions = load_decisions(target_dir / "DECISIONS.json")
    except Exception:
        return ()
    return tuple(json.loads(render_decisions(decisions)))


def _log_files(
    calls: Sequence[Mapping[str, object]], history: Sequence[Mapping[str, object]]
) -> tuple[LogFile, ...]:
    """The local evidence files the run's *failing* model executions recorded.

    Paths come from each record's ``artifacts`` map, so the report cites what Drydock wrote
    rather than a path this module reconstructed and might get wrong.

    Only the executions belonging to a failed command are cited, and only the last
    :data:`MAX_CITED_EXECUTIONS` of those. Drydock runs one command at a time, so a call
    belongs to the last command that started at or before it.
    """
    starts = [(stamp_key(record), int(record.get("return_code") or 0)) for record in history]
    chosen: list[Mapping[str, object]] = []
    for call in calls:
        stamp = str(call.get("execution_id") or "").split("-")[0]
        owner = max(
            (index for index, (start, _) in enumerate(starts) if start and start <= stamp),
            default=None,
        )
        if owner is not None and starts[owner][1] != 0:
            chosen.append(call)
    if not chosen:
        chosen = list(calls)
    seen: dict[str, LogFile] = {}
    for call in chosen[-MAX_CITED_EXECUTIONS:]:
        artifacts = call.get("artifacts")
        if not isinstance(artifacts, Mapping):
            continue
        for role in LOG_ROLES:
            raw = artifacts.get(role)
            if not isinstance(raw, str) or not raw:
                continue
            seen[raw] = _log_file(role, Path(raw))
    return tuple(seen.values())


def _log_file(role: str, path: Path) -> LogFile:
    try:
        data = path.read_bytes()
    except OSError:
        return LogFile(role=role, path=str(path), exists=False)
    return LogFile(
        role=role,
        path=str(path),
        exists=True,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def _transcripts(
    workspace: Path, target: str, start_key: str, history: Sequence[Mapping[str, object]]
) -> tuple[Excerpt, ...]:
    """The tail of each failed command's transcript.

    A failure is at the end of a transcript, so the tail is what a diagnosis needs; the head is
    the assembled context, which the reader can open from the cited path when they want it.
    """
    logs_dir = workspace / "logs"
    failed = [record for record in history if int(record.get("return_code") or 0) != 0]
    chosen: list[Excerpt] = []
    for record in failed[-3:]:
        named = str(record.get("transcript") or "")
        path = (workspace / named) if named else None
        if path is None or not path.is_file():
            candidates = run_logs(
                logs_dir, target, stamp_key(record), sibling_prefixes(workspace / "targets", target)
            )
            path = next((item for item in candidates if item.suffix == ".log"), None)
        if path is None:
            continue
        excerpt = _excerpt(
            path, " ".join(history_tokens(record)) or path.name, MAX_TRANSCRIPT_LINES, tail=True
        )
        if excerpt is not None:
            chosen.append(excerpt)
    return tuple(chosen)


def _excerpt(path: Path, name: str, limit: int, *, tail: bool = False) -> Excerpt | None:
    """A bounded slice of a file, or ``None`` when it cannot be read.

    Unreadable is reported by the caller as missing evidence. It is never an error: a Target
    that never reached a stage has no artifact from it, which is a finding, not a fault.
    """
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    lines = content.splitlines()
    if len(lines) <= limit:
        return Excerpt(name=name, path=str(path), text=content, total_lines=len(lines))
    kept = lines[-limit:] if tail else lines[:limit]
    return Excerpt(
        name=name,
        path=str(path),
        text="\n".join(kept),
        truncated=True,
        total_lines=len(lines),
    )


def _manifest_story_count(path: Path) -> int:
    """Story rows in the Manifest, counted from its block headings."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return sum(1 for line in content.splitlines() if line.startswith("### "))


def _acceptance_tally(path: Path) -> str:
    """``6 of 45 criteria failed``, or an empty string when the file says nothing usable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(data, Mapping):
        return ""
    criteria = data.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        return ""
    failed = sum(
        1
        for item in criteria
        if isinstance(item, Mapping) and str(item.get("status") or "").lower() == "fail"
    )
    return f"{failed} of {len(criteria)} criteria failed" if failed else f"{len(criteria)} criteria"
