"""Target-scoped aggregation of LLM execution evidence recorded in ``logs/llm.jsonl``.

Every LLM-assisted command appends one record per execution through
:func:`drydock.execution.append_execution_record`. This module reads those records back,
attributes each one to a Target, normalizes provider-specific token accounting, and rolls
the result up for reporting. It performs no rendering and no filesystem writes.

Token accounting differs by provider and is normalized here:

* Codex reports ``input_tokens`` inclusive of ``cached_input_tokens``.
* Claude reports ``input_tokens`` exclusive of ``cache_read_input_tokens``.

Both are converted to a single contract: ``total_input`` is everything sent to the model,
``cached_input`` is the cache-read portion of it, and ``fresh_input`` is the remainder.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from drydock.execution import log_component

__all__ = [
    "RunActivity",
    "RunUsage",
    "GroupUsage",
    "UsageReport",
    "normalize_tokens",
    "read_records",
    "record_target",
    "scan_activity",
    "build_report",
    "usage_report",
    "iter_targets",
]

# Providers whose reported ``input_tokens`` already contains the cache-read tokens.
# Unknown providers are treated the same way, which never double-counts.
_CACHE_INCLUDED_IN_INPUT = {"codex": True, "claude": False}

# Raw transcripts above this size are not scanned for activity counts; the summary stays
# useful and a runaway transcript cannot stall a page render.
_MAX_ACTIVITY_SCAN_BYTES = 32 * 1024 * 1024

_ARTIFACT_SUFFIXES = (".prompt.md", ".raw.jsonl", ".output.txt", ".stderr.log")


@dataclass(frozen=True)
class RunActivity:
    """Agentic-loop counts recovered from one execution's raw transcript."""

    tool_calls: int = 0
    file_changes: int = 0
    events: int = 0
    messages: int = 0
    rate_limit_utilization: float | None = None
    scanned: bool = False


@dataclass(frozen=True)
class RunUsage:
    """One LLM execution, normalized for reporting."""

    execution_id: str
    target: str
    started_at: str
    completed_at: str
    command: str
    detail: str
    provider: str
    model: str
    status: str
    returncode: int | None
    timed_out: bool
    error: str
    total_input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    elapsed_ms: int
    prompt_tokens_estimate: int
    prompt_bytes: int
    activity: RunActivity = field(default_factory=RunActivity)
    full_cli: str | None = None
    sub_command: str | None = None
    client_elapsed_ms: int | None = None
    llm_server_duration_ms: int | None = None

    @property
    def fresh_input_tokens(self) -> int:
        return max(self.total_input_tokens - self.cached_input_tokens, 0)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.output_tokens

    @property
    def seconds(self) -> float:
        return self.elapsed_ms / 1000.0

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"

    @property
    def cache_hit_rate(self) -> float:
        """Cache-read share of everything sent to the model, 0.0 when nothing was sent."""
        if self.total_input_tokens <= 0:
            return 0.0
        return self.cached_input_tokens / self.total_input_tokens


@dataclass(frozen=True)
class GroupUsage:
    """Totals for one grouping key (a command, or a provider/model pair)."""

    key: str
    runs: int = 0
    total_input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    elapsed_ms: int = 0
    tool_calls: int = 0
    failures: int = 0

    @property
    def fresh_input_tokens(self) -> int:
        return max(self.total_input_tokens - self.cached_input_tokens, 0)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.output_tokens

    @property
    def seconds(self) -> float:
        return self.elapsed_ms / 1000.0


@dataclass(frozen=True)
class UsageReport:
    """Every recorded execution for one Target, newest first, with rollups."""

    target: str
    runs: tuple[RunUsage, ...] = ()
    by_command: tuple[GroupUsage, ...] = ()
    by_provider: tuple[GroupUsage, ...] = ()
    records_read: int = 0
    invalid_records: int = 0

    @property
    def run_count(self) -> int:
        return len(self.runs)

    @property
    def failures(self) -> tuple[RunUsage, ...]:
        return tuple(run for run in self.runs if not run.succeeded)

    @property
    def total_input_tokens(self) -> int:
        return sum(run.total_input_tokens for run in self.runs)

    @property
    def cached_input_tokens(self) -> int:
        return sum(run.cached_input_tokens for run in self.runs)

    @property
    def fresh_input_tokens(self) -> int:
        return sum(run.fresh_input_tokens for run in self.runs)

    @property
    def output_tokens(self) -> int:
        return sum(run.output_tokens for run in self.runs)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.output_tokens

    @property
    def prompt_tokens_estimate(self) -> int:
        return sum(run.prompt_tokens_estimate for run in self.runs)

    @property
    def elapsed_ms(self) -> int:
        return sum(run.elapsed_ms for run in self.runs)

    @property
    def seconds(self) -> float:
        return self.elapsed_ms / 1000.0

    @property
    def tool_calls(self) -> int:
        return sum(run.activity.tool_calls for run in self.runs)

    @property
    def file_changes(self) -> int:
        return sum(run.activity.file_changes for run in self.runs)

    @property
    def raw_events(self) -> int:
        return sum(run.activity.events for run in self.runs)

    @property
    def cache_hit_rate(self) -> float:
        if self.total_input_tokens <= 0:
            return 0.0
        return self.cached_input_tokens / self.total_input_tokens

    @property
    def peak_rate_limit_utilization(self) -> float | None:
        seen = [
            run.activity.rate_limit_utilization
            for run in self.runs
            if run.activity.rate_limit_utilization is not None
        ]
        return max(seen) if seen else None


# ── Reading ─────────────────────────────────────────────────────────────────────


def read_records(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Return the execution records in ``path`` and the count of unparsable lines."""
    records: list[dict[str, Any]] = []
    invalid = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return [], 0
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            invalid += 1
            continue
        if isinstance(record, dict):
            records.append(record)
        else:
            invalid += 1
    return records, invalid


def record_target(record: Mapping[str, Any]) -> str:
    """Return the Target a record belongs to, or an empty string when unattributable.

    Records written since ``job.target`` was added carry the Target directly. Older
    records are recovered from the artifact basename, which is composed as
    ``<stamp>_<target>_<command>_<provider>``: the stamp and the trailing two components
    are known from the record itself, so the remainder is the Target exactly.
    """
    job = record.get("job")
    if not isinstance(job, Mapping):
        return ""
    direct = job.get("target")
    if isinstance(direct, str) and direct:
        return direct
    parameters = job.get("parameters")
    if isinstance(parameters, Mapping):
        value = parameters.get("target")
        if isinstance(value, str) and value:
            return value
    return _target_from_artifacts(record, job)


def _target_from_artifacts(record: Mapping[str, Any], job: Mapping[str, Any]) -> str:
    stem = _artifact_stem(record)
    if not stem:
        return ""
    suffix = "_".join(
        part
        for part in (
            log_component(str(job.get("command_name") or "")),
            log_component(str(job.get("llm") or "")),
        )
        if part
    )
    if suffix and stem.endswith(f"_{suffix}"):
        stem = stem[: -(len(suffix) + 1)]
    _, separator, remainder = stem.partition("_")
    return remainder if separator else ""


def _artifact_stem(record: Mapping[str, Any]) -> str:
    artifacts = record.get("artifacts")
    if not isinstance(artifacts, Mapping):
        return ""
    for key in ("prompt", "raw", "output", "stderr"):
        value = artifacts.get(key)
        if not isinstance(value, str) or not value:
            continue
        name = Path(value).name
        for suffix in _ARTIFACT_SUFFIXES:
            if name.endswith(suffix):
                return name[: -len(suffix)]
    return ""


# ── Activity ────────────────────────────────────────────────────────────────────


def scan_activity(path: Path, provider: str) -> RunActivity:
    """Count agentic-loop activity in one raw provider transcript.

    Codex emits one ``item.completed`` event per finished tool call or file edit; Claude
    emits assistant messages carrying ``tool_use`` blocks. Both are reduced to the same
    counts so a Target's runs compare directly regardless of provider.
    """
    try:
        if not path.is_file() or path.stat().st_size > _MAX_ACTIVITY_SCAN_BYTES:
            return RunActivity()
    except OSError:
        return RunActivity()

    tool_calls = 0
    file_changes = 0
    events = 0
    messages = 0
    utilization: float | None = None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(event, dict):
                    continue
                events += 1
                kind = event.get("type")
                if kind == "item.completed":
                    item = event.get("item")
                    item_type = item.get("type") if isinstance(item, dict) else None
                    if item_type == "command_execution":
                        tool_calls += 1
                    elif item_type == "file_change":
                        file_changes += 1
                    elif item_type == "agent_message":
                        messages += 1
                elif kind == "assistant":
                    calls, texts = _claude_message_counts(event)
                    tool_calls += calls
                    messages += texts
                elif kind == "rate_limit_event":
                    value = _rate_limit_utilization(event)
                    if value is not None:
                        utilization = value if utilization is None else max(utilization, value)
    except OSError:
        return RunActivity()

    return RunActivity(
        tool_calls=tool_calls,
        file_changes=file_changes,
        events=events,
        messages=messages,
        rate_limit_utilization=utilization,
        scanned=True,
    )


def _claude_message_counts(event: Mapping[str, Any]) -> tuple[int, int]:
    message = event.get("message")
    if not isinstance(message, Mapping):
        return 0, 0
    content = message.get("content")
    if not isinstance(content, list):
        return 0, 0
    tool_calls = 0
    texts = 0
    for block in content:
        if not isinstance(block, Mapping):
            continue
        block_type = block.get("type")
        if block_type == "tool_use":
            tool_calls += 1
        elif block_type == "text":
            texts += 1
    return tool_calls, texts


def _rate_limit_utilization(event: Mapping[str, Any]) -> float | None:
    info = event.get("rate_limit_info")
    if not isinstance(info, Mapping):
        return None
    value = info.get("utilization")
    if isinstance(value, (int, float)):
        return float(value)
    return None


# ── Aggregation ─────────────────────────────────────────────────────────────────


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _detail(command: str, parameters: Mapping[str, Any]) -> str:
    """Return the short per-run subject: the build step, compacted source, or command."""
    step = parameters.get("step")
    if isinstance(step, str) and step:
        attempt = parameters.get("attempt")
        if isinstance(attempt, int) and attempt > 0:
            return f"{step} (attempt {attempt + 1})"
        return step
    for key in ("source", "prompt", "diagnosed_command"):
        value = parameters.get(key)
        if isinstance(value, str) and value:
            return Path(value).name if key != "diagnosed_command" else value
    return command


def normalize_tokens(provider: str, stats: Mapping[str, Any]) -> tuple[int, int, int]:
    """Return ``(total_input, cached_input, output)`` on the shared accounting contract."""
    reported_input = _int(stats.get("input_tokens"))
    cached = _int(stats.get("cached_input_tokens"))
    output = _int(stats.get("output_tokens"))
    if _CACHE_INCLUDED_IN_INPUT.get(provider.lower(), True):
        total_input = max(reported_input, cached)
    else:
        total_input = reported_input + cached
    return total_input, cached, output


def _run_from_record(record: Mapping[str, Any], target: str) -> RunUsage:
    job = record.get("job") if isinstance(record.get("job"), Mapping) else {}
    result = record.get("result") if isinstance(record.get("result"), Mapping) else {}
    stats = result.get("stats") if isinstance(result.get("stats"), Mapping) else {}
    timing = result.get("timing") if isinstance(result.get("timing"), Mapping) else {}
    prompt = record.get("prompt") if isinstance(record.get("prompt"), Mapping) else {}
    parameters = job.get("parameters") if isinstance(job.get("parameters"), Mapping) else {}

    provider = _text(job.get("llm"))
    command = _text(job.get("command_name"))
    total_input, cached, output = normalize_tokens(provider, stats)
    returncode = result.get("returncode")

    return RunUsage(
        execution_id=_text(record.get("execution_id")),
        target=target,
        started_at=_text(record.get("started_at")),
        completed_at=_text(record.get("completed_at")),
        command=command,
        detail=_detail(command, parameters),
        provider=provider,
        model=_text(job.get("model")),
        status=_text(record.get("status")) or "unknown",
        returncode=returncode if isinstance(returncode, int) else None,
        timed_out=bool(result.get("timed_out")),
        error=_text(result.get("error")),
        total_input_tokens=total_input,
        cached_input_tokens=cached,
        output_tokens=output,
        elapsed_ms=_int(stats.get("elapsed_ms")),
        prompt_tokens_estimate=_int(prompt.get("total_tokens_estimate")),
        prompt_bytes=_int(prompt.get("bytes")),
        full_cli=_text(job.get("full_cli")) or None,
        sub_command=_text(job.get("sub_command")) or None,
        client_elapsed_ms=_int(timing.get("client_elapsed_ms")) or None,
        llm_server_duration_ms=_int(timing.get("llm_server_duration_ms")) or None,
    )


def _group(runs: Iterable[RunUsage], key: str) -> tuple[GroupUsage, ...]:
    totals: dict[str, dict[str, int]] = {}
    for run in runs:
        name = run.command if key == "command" else _provider_label(run)
        bucket = totals.setdefault(
            name,
            {
                "runs": 0,
                "total_input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "elapsed_ms": 0,
                "tool_calls": 0,
                "failures": 0,
            },
        )
        bucket["runs"] += 1
        bucket["total_input_tokens"] += run.total_input_tokens
        bucket["cached_input_tokens"] += run.cached_input_tokens
        bucket["output_tokens"] += run.output_tokens
        bucket["elapsed_ms"] += run.elapsed_ms
        bucket["tool_calls"] += run.activity.tool_calls
        bucket["failures"] += 0 if run.succeeded else 1
    groups = [GroupUsage(key=name, **values) for name, values in totals.items()]
    groups.sort(key=lambda group: (-group.total_tokens, group.key))
    return tuple(groups)


def _provider_label(run: RunUsage) -> str:
    if run.provider and run.model:
        return f"{run.provider} · {run.model}"
    return run.provider or run.model or "unknown"


def _sort_key(entry: tuple[int, Mapping[str, Any], RunUsage]) -> tuple[str, int]:
    index, _record, run = entry
    return (run.started_at, index)


def build_report(
    records: Sequence[Mapping[str, Any]],
    target: str,
    *,
    invalid_records: int = 0,
    include_activity: bool = True,
) -> UsageReport:
    """Roll up every record belonging to ``target``, newest run first."""
    selected: list[tuple[int, Mapping[str, Any], RunUsage]] = []
    for index, record in enumerate(records):
        if record_target(record) != target:
            continue
        selected.append((index, record, _run_from_record(record, target)))
    selected.sort(key=_sort_key, reverse=True)

    runs: list[RunUsage] = []
    for _index, record, run in selected:
        raw = _raw_path(record)
        if include_activity and raw is not None:
            run = replace(run, activity=scan_activity(raw, run.provider))
        runs.append(run)

    return UsageReport(
        target=target,
        runs=tuple(runs),
        by_command=_group(runs, "command"),
        by_provider=_group(runs, "provider"),
        records_read=len(records),
        invalid_records=invalid_records,
    )


def _raw_path(record: Mapping[str, Any]) -> Path | None:
    artifacts = record.get("artifacts")
    if isinstance(artifacts, Mapping):
        value = artifacts.get("raw")
        if isinstance(value, str) and value:
            return Path(value)
    return None


def usage_report(logs_dir: Path, target: str, *, include_activity: bool = True) -> UsageReport:
    """Read ``logs_dir/llm.jsonl`` and report the executions belonging to ``target``."""
    records, invalid = read_records(logs_dir / "llm.jsonl")
    return build_report(
        records,
        target,
        invalid_records=invalid,
        include_activity=include_activity,
    )


def iter_targets(records: Iterable[Mapping[str, Any]]) -> Iterator[str]:
    """Yield each distinct Target present in ``records``, in first-seen order."""
    seen: set[str] = set()
    for record in records:
        target = record_target(record)
        if target and target not in seen:
            seen.add(target)
            yield target
