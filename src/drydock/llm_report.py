"""Read-only lifecycle-scoped LLM usage reporting for ``drydock score llm``."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from drydock.llm_usage import RunUsage, build_report, read_records

__all__ = [
    "LlmReportError",
    "LlmUsageRow",
    "LlmScoreReport",
    "build_llm_score_report",
]

_STAMP = re.compile(r"^(\d{8})\.(\d{6})\.(\d{3})Z$")


class LlmReportError(ValueError):
    """The requested lifecycle scope cannot be established from durable evidence."""


@dataclass(frozen=True)
class LlmUsageRow:
    """Usage roll-up for one lifecycle stage, subtype, and provider/model pair."""

    verb: str
    subclass: str
    model: str
    calls: int
    total_input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    first_started_at: str

    @property
    def fresh_input_tokens(self) -> int:
        return max(self.total_input_tokens - self.cached_input_tokens, 0)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.output_tokens


@dataclass(frozen=True)
class LlmScoreReport:
    """One Target's filtered LLM evidence and the roll-ups shown to the operator."""

    target: str
    since_init: bool
    init_stamp: str
    rows: tuple[LlmUsageRow, ...]
    runs: tuple[RunUsage, ...]
    excluded_before_init: int
    excluded_incomplete: int
    records_read: int
    invalid_records: int

    @property
    def calls(self) -> int:
        return len(self.runs)

    @property
    def total_input_tokens(self) -> int:
        return sum(run.total_input_tokens for run in self.runs)

    @property
    def cached_input_tokens(self) -> int:
        return sum(run.cached_input_tokens for run in self.runs)

    @property
    def fresh_input_tokens(self) -> int:
        return max(self.total_input_tokens - self.cached_input_tokens, 0)

    @property
    def output_tokens(self) -> int:
        return sum(run.output_tokens for run in self.runs)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.output_tokens


def build_llm_score_report(
    workspace: Path,
    target_dir: Path,
    target: str,
    *,
    all_history: bool = False,
    include_incomplete: bool = False,
) -> LlmScoreReport:
    """Return deduplicated usage after the Target's latest successful ``init``.

    The workspace journal is canonical, while selected commands also retain Target-local
    evidence.  Both sources are merged by execution ID so a mirrored record counts once.
    ``--all`` intentionally bypasses the lifecycle boundary and includes incomplete runs.
    """
    records, invalid = _merged_records(
        workspace / "logs" / "llm.jsonl", target_dir / "logs" / "llm.jsonl"
    )
    usage = build_report(records, target, invalid_records=invalid, include_activity=False)
    all_runs = usage.runs
    init_stamp = ""
    boundary = ""
    if not all_history:
        init_stamp = _latest_successful_init_stamp(workspace / "logs" / "history.jsonl", target)
        if not init_stamp:
            raise LlmReportError(
                f"No successful drydock init record for {target}. Run: drydock score llm {target} --all"
            )
        boundary = _stamp_to_iso(init_stamp)
        if not boundary:
            raise LlmReportError(
                f"The latest drydock init record for {target} has no usable timestamp. "
                f"Run: drydock score llm {target} --all"
            )

    scoped = tuple(run for run in all_runs if all_history or run.started_at >= boundary)
    excluded_before = len(all_runs) - len(scoped)
    if all_history or include_incomplete:
        selected = scoped
        excluded_incomplete = 0
    else:
        selected = tuple(run for run in scoped if _completed(run))
        excluded_incomplete = len(scoped) - len(selected)
    return LlmScoreReport(
        target=target,
        since_init=not all_history,
        init_stamp=init_stamp,
        rows=_rows(selected),
        runs=selected,
        excluded_before_init=excluded_before,
        excluded_incomplete=excluded_incomplete,
        records_read=len(records),
        invalid_records=invalid,
    )


def _merged_records(*paths: Path) -> tuple[list[dict[str, Any]], int]:
    records: list[dict[str, Any]] = []
    invalid = 0
    seen: set[str] = set()
    for path in paths:
        loaded, rejected = read_records(path)
        invalid += rejected
        for index, record in enumerate(loaded):
            execution_id = record.get("execution_id")
            key = (
                execution_id
                if isinstance(execution_id, str) and execution_id
                else f"{path}:{index}"
            )
            if key in seen:
                continue
            seen.add(key)
            records.append(record)
    return records, invalid


def _latest_successful_init_stamp(history_path: Path, target: str) -> str:
    try:
        lines = history_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except Exception:  # noqa: BLE001 - a damaged history row cannot invalidate later rows.
            continue
        if not isinstance(record, Mapping) or record.get("target") != target:
            continue
        argv = record.get("argv")
        is_init = isinstance(argv, list) and bool(argv) and argv[0] == "init"
        if not is_init and not str(record.get("command", "")).startswith("drydock init "):
            continue
        if record.get("return_code") == 0:
            stamp = record.get("stamp")
            return stamp if isinstance(stamp, str) else ""
    return ""


def _stamp_to_iso(stamp: str) -> str:
    match = _STAMP.fullmatch(stamp)
    if match is None:
        return ""
    day, moment, milliseconds = match.groups()
    return f"{day[:4]}-{day[4:6]}-{day[6:]}T{moment[:2]}:{moment[2:4]}:{moment[4:]}.{milliseconds}Z"


def _completed(run: RunUsage) -> bool:
    return run.status == "succeeded" and run.returncode == 0 and not run.timed_out and not run.error


def _model_label(run: RunUsage) -> str:
    if run.provider and run.model:
        return f"{run.provider} / {run.model}"
    return run.provider or run.model or "unknown"


def _rows(runs: tuple[RunUsage, ...]) -> tuple[LlmUsageRow, ...]:
    buckets: dict[tuple[str, str, str], dict[str, int | str]] = {}
    for run in runs:
        key = (run.verb, run.subclass, _model_label(run))
        bucket = buckets.setdefault(
            key,
            {
                "calls": 0,
                "total_input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "first_started_at": run.started_at,
            },
        )
        bucket["calls"] = int(bucket["calls"]) + 1
        bucket["total_input_tokens"] = int(bucket["total_input_tokens"]) + run.total_input_tokens
        bucket["cached_input_tokens"] = int(bucket["cached_input_tokens"]) + run.cached_input_tokens
        bucket["output_tokens"] = int(bucket["output_tokens"]) + run.output_tokens
        bucket["first_started_at"] = min(str(bucket["first_started_at"]), run.started_at)
    rows = [
        LlmUsageRow(
            verb=verb,
            subclass=subclass,
            model=model,
            calls=int(values["calls"]),
            total_input_tokens=int(values["total_input_tokens"]),
            cached_input_tokens=int(values["cached_input_tokens"]),
            output_tokens=int(values["output_tokens"]),
            first_started_at=str(values["first_started_at"]),
        )
        for (verb, subclass, model), values in buckets.items()
    ]
    rows.sort(key=lambda row: (row.first_started_at, row.verb, row.subclass, row.model))
    return tuple(rows)
