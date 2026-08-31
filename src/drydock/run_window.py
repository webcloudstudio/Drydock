"""The latest run of a Target: which commands it covers, and which evidence files it wrote.

A Target's history is a single journal. "The latest run" is the slice of it since the Target
was last created: everything after the most recent ``drydock init``. That window is what an
operator means when they ask what happened, and it is the same window a receipt publishes and
a diagnosis reads, so both resolve it here rather than each deciding for itself.

The three journals this module joins are written by unrelated commands and share no key but a
millisecond stamp:

* ``logs/history.jsonl`` — one record per CLI invocation, with its exit code and stamp.
* ``logs/llm.jsonl`` — one record per model execution, with its artifacts and accounting.
* ``logs/<stamp>_<target>_<command>_<llm>.*`` — the streams those two index.

Every function here reads. Nothing resolves configuration, executes a proof, or calls a model.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

#: ``20260815.085220.134Z_jq_build_codex.log`` — stamp, then the components ``log_basename``
#: joined. The stamp is fixed-width, so lexical order is chronological order.
LOG_NAME_RE = re.compile(r"^(?P<stamp>\d{8}\.\d{6}\.\d{3}Z)_(?P<rest>.+)$")

#: A run begins where the Target does. Everything the Target has recorded since its most recent
#: ``drydock init`` is one run; a Target initialised once therefore reports its whole life,
#: which is what an operator means by "the latest run" for a project they have built repeatedly.
RUN_START_VERB = "init"


def history_verb(record: Mapping[str, object]) -> str:
    """The Drydock verb a history record invoked, e.g. ``build`` for ``drydock build jq``."""
    tokens = history_tokens(record)
    return tokens[0] if tokens else ""


def history_tokens(record: Mapping[str, object]) -> list[str]:
    """The Drydock operands a journal record invoked, without the executable shim."""
    argv = record.get("argv")
    if isinstance(argv, list) and argv:
        tokens = [str(item) for item in argv]
        return tokens[1:] if tokens[0] == "drydock" else tokens
    return str(record.get("command") or "").split()[1:]


def stamp_key(record: Mapping[str, object]) -> str:
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


def stamp_to_iso(stamp: str) -> str:
    """Render a log stamp as the ISO instant the report's clock formatting expects."""
    try:
        moment = datetime.strptime(stamp, "%Y%m%d.%H%M%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        return ""
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def target_history(workspace: Path, target: str) -> list[Mapping[str, object]]:
    """Every command whose operands name one Target, oldest first.

    The journal's legacy ``target`` field held a score sub-verb for some score commands.
    Target resolution therefore follows the command operands, the same contract as
    ``drydock score <Target>``.
    """
    from drydock.config import read_command_history

    records = [
        record
        for record in read_command_history(workspace, limit=1_000_000)
        if target in history_tokens(record)[1:]
    ]
    return sorted(records, key=stamp_key)


def run_window(records: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    """Narrow a Target's history to its latest run: everything since the last ``init``.

    A Target whose history predates any recorded ``init`` reports all of it rather than
    nothing — the alternative is a receipt that silently omits the work it is meant to prove.
    """
    starts = [
        index for index, record in enumerate(records) if history_verb(record) == RUN_START_VERB
    ]
    return list(records[starts[-1] :] if starts else records)


def sibling_prefixes(targets_root: Path, target: str) -> tuple[str, ...]:
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


def run_logs(
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
        match = LOG_NAME_RE.match(path.name)
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


def llm_records(records_path: Path, target: str, start_key: str) -> list[Mapping[str, object]]:
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
